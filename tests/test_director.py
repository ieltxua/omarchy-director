from __future__ import annotations
import io, json, os, stat, tempfile, time, unittest
from pathlib import Path
from unittest.mock import Mock, patch
from director.desktop import desktop_entries, launch
from director.hyprland import Hyprland
from director.jev import Jev, JevError
from director.models import Plan, Step
from director.service import Director
from director.store import Store
from director.cli import main
from director.capabilities import NativeResult

CLIENTS = [{"address":"0xaaa","title":"Terminal","class":"term","workspace":{"id":1},"at":[10,20],"size":[800,600],"floating":False,"fullscreen":False},{"address":"0xbbb","title":"Browser","class":"chromium","workspace":{"id":2},"at":[30,40],"size":[900,700],"floating":False,"fullscreen":False}]
class Result:
 def __init__(self, stdout="", returncode=0, stderr=""): self.stdout,self.returncode,self.stderr=stdout,returncode,stderr
class FakeHypr:
 def __init__(self, states=None): self.runner=Mock(); self.calls=[]; self.states=states or []; self.moved={}; self.floated={}; self.resized={}; self.workspace=1
 def state(self):
  if self.states: return self.states.pop(0)
  clients=json.loads(json.dumps(CLIENTS))
  for client in clients:
   if client["address"] in self.moved: client["workspace"]={"id":self.moved[client["address"]]}
   if client["address"] in self.floated: client["floating"]=self.floated[client["address"]]
   if client["address"] in self.resized: client["size"]=self.resized[client["address"]]
  return {"clients":clients,"workspaces":[{"id":1,"windows":1},{"id":2,"windows":0},{"id":3,"windows":1}],"monitors":[{"focused":True,"activeWorkspace":{"id":self.workspace,"name":str(self.workspace)}}],"active":clients[0]}
 def focus_window(self,address): self.calls.append(("focus_window",address))
 def move_window(self,address,workspace,follow=False): self.calls.append(("move_window",address,workspace,follow)); self.moved[address]=workspace
 def focus_workspace(self,workspace): self.calls.append(("focus_workspace",workspace)); self.workspace=workspace
 def set_floating(self,address,floating): self.calls.append(("set_floating",address,floating)); self.floated[address]=floating
 def set_fullscreen(self,address,fullscreen): self.calls.append(("set_fullscreen",address,fullscreen))
 def restore_geometry(self,address,at,size): self.calls.append(("restore_geometry",address,at,size))
 def resize_window(self,address,width,height): self.calls.append(("resize_window",address,width,height)); self.resized[address]=[width,height]
 def swap_window(self,address,direction): self.calls.append(("swap_window",address,direction))
class FakeJev:
 def __init__(self, answers): self.answers=answers
 def decide(self,state,questions): self.state,self.questions=state,questions; return self.answers
class FakeNative:
 def __init__(self): self.executed=[]
 def themes(self): return ["Nord","Osaka Jade"]
 def build_step(self,capability,query,theme=None): return Step("native",capability,label=capability,params={"capability":capability,"summary":capability,"theme":theme})
 def execute(self,step): self.executed.append(step.target); return NativeResult(step.target or "")
def answers(intent, windows=(), apps=(), workspace="keep", layout="keep", workspace_view="stay"):
 result={"intent":{"type":"choice","choice":intent,"confidence":.95,"probabilities":{}},"layout":{"type":"choice","choice":layout,"confidence":.95,"probabilities":{}},"workspace":{"type":"choice","choice":workspace,"confidence":.95,"probabilities":{}},"workspace_view":{"type":"choice","choice":workspace_view,"confidence":.95,"probabilities":{}}}
 result.update({f"window:{v}":{"type":"noul","noul":.95} for v in windows}); result.update({f"app:{v}":{"type":"noul","noul":.95} for v in apps}); return result

class DirectorTests(unittest.TestCase):
 def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.store=Store(self.tmp.name); self.hypr=FakeHypr()
 def tearDown(self): self.tmp.cleanup()
 def make(self,a,launcher=Mock()): return Director(self.hypr,FakeJev(a),self.store,launcher=launcher,sleeper=lambda _:None)
 def test_typed_answers_make_multi_move_and_step_summaries(self):
  plan=self.make(answers("move",["0xaaa","0xbbb"],workspace="next_empty")).plan("move")
  self.assertTrue(plan.executable); self.assertEqual([s.workspace for s in plan.steps],[2,2]); self.assertIn("Terminal",plan.steps[0].to_dict()["summary"])
 def test_ambiguity_blocks_execution(self):
  a=answers("focus",["0xaaa"]); a["intent"]["confidence"]=.2
  plan=self.make(a).plan("focus")
  self.assertFalse(plan.executable); self.assertTrue(any("confianza" in w for w in plan.warnings))
 def test_explicit_all_terminals_move_is_not_split_by_follow_behavior(self):
  old=CLIENTS[:]; CLIENTS[:] = [{"address":f"0x{i}","title":"Foot","class":"foot","workspace":{"id":2},"floating":False} for i in range(4)]
  try:
   response=answers("move",["0x0","0x1","0x2","0x3"],workspace="workspace:1",workspace_view="stay")
   response["intent"]["confidence"]=.82
   for index,probability in enumerate((.89,.78,.90,.81)): response[f"window:0x{index}"]["noul"]=probability
   plan=self.make(response).plan("pone todas las terminales en el workspace 1")
   self.assertTrue(plan.executable); self.assertEqual(len(plan.steps),4); self.assertTrue(all(step.operation == "move" and step.workspace == 1 for step in plan.steps))
  finally: CLIENTS[:] = old
 def test_explicit_follow_is_a_separate_decision(self):
  plan=self.make(answers("move",["0xaaa"],workspace="workspace:2",workspace_view="switch")).plan("llevame con esta terminal al workspace 2")
  self.assertTrue(plan.executable); self.assertEqual(plan.steps[0].operation,"isolate")
 def test_existing_app_focus_accepts_one_strong_target_at_branch_threshold(self):
  response=answers("focus",["0xbbb"]); response["intent"]["confidence"]=.70; response["window:0xbbb"]["noul"]=.86
  plan=self.make(response).plan("take me to x app")
  self.assertTrue(plan.executable); self.assertEqual([(step.operation,step.target) for step in plan.steps],[("focus","0xbbb")])
 def test_exact_x_resize_is_typed_bounded_and_reversible(self):
  director=self.make(answers("resize_smaller",["0xbbb"])); plan=director.plan("can you make x 20% smaller?")
  self.assertTrue(plan.executable); self.assertEqual((plan.steps[0].operation,plan.steps[0].params["width"],plan.steps[0].params["height"]),("window_resize",720,560))
  director.execute(plan.token); self.assertIn(("resize_window","0xbbb",720,560),self.hypr.calls)
  director.undo(); self.assertEqual(self.hypr.calls[-1],("resize_window","0xbbb",900,700))
 def test_exact_x_name_is_resolved_when_jev_window_probability_varies(self):
  old=CLIENTS[1]["title"]; CLIENTS[1]["title"]="Home / X"
  try:
   response=answers("resize_smaller"); response["window:0xbbb"]={"type":"noul","noul":.52}
   plan=self.make(response).plan("can you make x smaller?")
   self.assertTrue(plan.executable); self.assertEqual(plan.steps[0].target,"0xbbb")
  finally: CLIENTS[1]["title"]=old
 def test_resize_rejects_ambiguous_multiple_windows(self):
  plan=self.make(answers("resize_larger",["0xaaa","0xbbb"])).plan("make them larger")
  self.assertFalse(plan.executable); self.assertIn("Necesito una sola ventana para esa acción",plan.warnings)
 def test_move_x_left_plans_native_swap_and_undoes_right(self):
  old=CLIENTS[1]["title"]; CLIENTS[1]["title"]="Home / X"
  try:
   director=self.make(answers("swap_left")); plan=director.plan("MOVE X TO THE LEFT")
   self.assertTrue(plan.executable); self.assertEqual((plan.steps[0].operation,plan.steps[0].target,plan.steps[0].params["direction"]),("window_swap","0xbbb","l"))
   before=self.hypr.state(); after=json.loads(json.dumps(before)); after["clients"][1]["at"]=[0,0]
   self.hypr.states=[before,after]; inverse=director._execute_step(plan.steps[0],{})
   self.assertEqual(inverse.params["direction"],"r")
   self.hypr.states=[after,before]; director._execute_step(inverse,{})
   self.assertIn(("swap_window","0xbbb","l"),self.hypr.calls); self.assertEqual(self.hypr.calls[-1],("swap_window","0xbbb","r"))
  finally: CLIENTS[1]["title"]=old
 def test_swap_without_neighbor_records_no_inverse(self):
  state=self.hypr.state(); self.hypr.states=[state,state]
  director=self.make({}); inverse=director._execute_step(Step("window_swap","0xbbb",label="Browser",params={"direction":"l"}),{})
  self.assertIsNone(inverse); self.assertTrue(any("vecina" in warning for warning in director._step_warnings))
 def test_gateway_failure_is_persisted_for_diagnostics(self):
  jev=Mock(); jev.decide.side_effect=JevError("gateway failed")
  director=Director(self.hypr,jev,self.store,launcher=Mock(),sleeper=lambda _:None)
  plan=director.plan("do something")
  self.assertFalse(plan.executable); self.assertEqual(self.store.get_plan(plan.token)["warnings"],["gateway failed"])
 def test_focus_rejects_multiple_targets_even_with_high_confidence(self):
  plan=self.make(answers("focus",["0xaaa","0xbbb"])).plan("focus the apps")
  self.assertFalse(plan.executable); self.assertTrue(any("una sola ventana" in warning for warning in plan.warnings))
 def test_multi_launch_and_deferred_arrangement_warns_without_new_windows(self):
  launcher=Mock(); apps={"slack":{"id":"slack","name":"Slack","startup_wm_class":"slack"},"chromium":{"id":"chromium","name":"Chromium","startup_wm_class":"chromium"}}
  with patch("director.service.desktop_entries",return_value=apps):
   director=self.make(answers("launch_arrange",apps=["slack","chromium"],layout="tile"),launcher)
   plan=director.plan("Abrí Slack y Chromium lado a lado")
   result=director.execute(plan.token)
  self.assertEqual(launcher.call_count,2); self.assertTrue(result["warnings"]); self.assertEqual(plan.steps[-1].operation,"arrange")
 def test_exact_installed_app_launches_on_named_workspace_without_jev_app_vote(self):
  apps={"slack":{"id":"slack","name":"Slack","startup_wm_class":"Slack","generic_name":"Slack Client","comment":"","keywords":""}}
  response=answers("launch",workspace="workspace:2")
  with patch("director.service.desktop_entries",return_value=apps): plan=self.make(response).plan("open Slack on workspace 2")
  self.assertTrue(plan.executable); self.assertEqual([(step.operation,step.target,step.workspace) for step in plan.steps],[("launch","slack",None),("place_launch","slack",2)])
 def test_explicit_new_workspace_is_not_silently_dropped(self):
  apps={"slack":{"id":"slack","name":"Slack","startup_wm_class":"Slack","generic_name":"","comment":"","keywords":""}}
  with patch("director.service.desktop_entries",return_value=apps): plan=self.make(answers("launch")).plan("open Slack on workspace 9")
  self.assertTrue(plan.executable); self.assertEqual(plan.steps[-1].workspace,9)
 def test_existing_launched_app_is_placed_and_undo_restores_workspace(self):
  apps={"slack":{"id":"slack","name":"Slack","startup_wm_class":"Slack","generic_name":"Slack Client","comment":"","keywords":""}}
  CLIENTS.append({"address":"0xccc","title":"Slack","class":"Slack","workspace":{"id":3},"at":[0,0],"size":[800,600],"floating":False,"fullscreen":False,"focusHistoryID":0})
  try:
   director=self.make(answers("launch",workspace="workspace:2"),launcher=Mock())
   with patch("director.service.desktop_entries",return_value=apps):
    plan=director.plan("open Slack on workspace 2"); director.execute(plan.token); director.undo()
   self.assertIn(("move_window","0xccc",2,False),self.hypr.calls); self.assertIn(("move_window","0xccc",3,False),self.hypr.calls)
  finally: CLIENTS.pop()
 def test_new_app_window_is_preferred_over_existing_instance(self):
  apps={"foot":{"id":"foot","name":"Foot","startup_wm_class":"foot"}}
  old={"address":"0xold","class":"foot","workspace":{"id":1},"focusHistoryID":0}; new={"address":"0xnew","class":"foot","workspace":{"id":1},"focusHistoryID":0}
  current={"clients":[old,new],"workspaces":[],"monitors":[],"active":old}; self.hypr.states=[current]
  self.assertTrue(self.make({})._place_launched_app({"0xold":old},"foot",2,apps)); self.assertEqual(self.hypr.calls[-1],("move_window","0xnew",2,False))
 def test_named_multi_launch_accepts_distributed_jev_evidence(self):
  apps={"slack":{"id":"slack","name":"Slack","startup_wm_class":"slack"},"chromium":{"id":"chromium","name":"Chromium","startup_wm_class":"chromium"}}
  response=answers("launch_arrange",apps=["slack","chromium"],layout="tile")
  response["intent"]["confidence"]=.43
  response["app:slack"]["noul"]=.63; response["app:chromium"]["noul"]=.54
  with patch("director.service.desktop_entries",return_value=apps):
   plan=self.make(response).plan("Abrí Slack y Chromium lado a lado")
  self.assertTrue(plan.executable); self.assertEqual([step.target for step in plan.steps[:2]],["chromium","slack"])
 def test_execute_rechecks_stale_targets(self):
  plan=Plan("x","",1,"",[Step("focus","0xgone")],executable=True); self.store.save_plan({**plan.to_dict(),"query":"","created_at":time.time(),"snapshot":{}})
  with self.assertRaisesRegex(ValueError,"state changed"): self.make({}).execute("x")
 def test_arrangement_never_pixel_moves_tiled_windows(self):
  plan=Plan("x","",1,"",[Step("arrange","0xaaa",layout="tile")],executable=True); self.store.save_plan({**plan.to_dict(),"query":"","created_at":time.time(),"snapshot":{}})
  self.make({}).execute("x"); self.assertIn(("set_floating","0xaaa",False),self.hypr.calls); self.assertFalse(any("geometry" in c[0] for c in self.hypr.calls))
 def test_arrange_moves_and_switches_to_selected_workspace(self):
  plan=Plan("x","",1,"",[Step("arrange","0xaaa",2,"tile")],executable=True); self.store.save_plan({**plan.to_dict(),"query":"","created_at":time.time(),"snapshot":{}})
  self.make({}).execute("x"); self.assertIn(("move_window","0xaaa",2,False),self.hypr.calls); self.assertIn(("focus_workspace",2),self.hypr.calls)
 def test_isolate_switches_to_destination(self):
  plan=Plan("x","",1,"",[Step("isolate","0xaaa",2)],executable=True); self.store.save_plan({**plan.to_dict(),"query":"","created_at":time.time(),"snapshot":{}})
  self.make({}).execute("x"); self.assertIn(("focus_workspace",2),self.hypr.calls)
 def test_ranked_app_candidates_preserve_strong_query_matches(self):
  apps={"aaa":{"id":"aaa","name":"Other"},"slack":{"id":"slack","name":"Slack"},"chromium":{"id":"chromium","name":"Chromium"}}
  self.assertEqual(Director._rank_apps("Abrí Slack y Chromium lado a lado",apps)[:2],["chromium","slack"])
  self.assertEqual(Director._explicit_apps("open Slack on workspace 2",apps),["slack"])
  nested={"firefox":{"id":"firefox","name":"Firefox"},"firefox-dev":{"id":"firefox-dev","name":"Firefox Developer Edition"}}
  self.assertEqual(Director._explicit_apps("open Firefox Developer Edition",nested),["firefox-dev"])
 def test_spanish_gather_three_terminals_uses_calibrated_nouls_and_tile(self):
  old=CLIENTS[:]; CLIENTS[:] = [{"address":f"0x{i}","title":"Foot","class":"foot","workspace":{"id":1},"floating":False} for i in range(3)]
  try:
   response=answers("arrange",["0x0","0x1","0x2"],workspace="workspace:2",layout="no_match")
   for key,value in response.items():
    if key.startswith("window:"): value["noul"]=.69
   plan=self.make(response).plan("Juntá las tres terminales en el workspace 2")
   self.assertTrue(plan.executable); self.assertEqual([(s.operation,s.workspace,s.layout) for s in plan.steps],[("arrange",2,"tile")]*3)
  finally: CLIENTS[:] = old
 def test_undo_restores_float_and_focus(self):
  self.store.append_history({"token":"old","snapshot":{"active":"0xbbb","windows":{"0xaaa":{"workspace":{"id":1},"floating":True,"fullscreen":False,"at":[1,2],"size":[3,4]}}}})
  result=self.make({}).undo(); self.assertEqual(result["message"],"Undo completed"); self.assertIn(("set_floating","0xaaa",True),self.hypr.calls); self.assertIn(("focus_window","0xbbb"),self.hypr.calls)
 def test_undo_restores_named_special_workspace_and_is_single_use(self):
  self.store.append_history({"token":"old","snapshot":{"windows":{"0xaaa":{"workspace":{"id":-1337,"name":"mac"},"floating":False,"fullscreen":False}}}})
  result=self.make({}).undo(); self.assertTrue(result["undone"]); self.assertIn(("move_window","0xaaa","name:mac",False),self.hypr.calls)
  with self.assertRaisesRegex(ValueError,"no reversible"): self.make({}).undo()
 def test_failed_execution_rolls_back_snapshot(self):
  class FailingHypr(FakeHypr):
   def set_floating(self,address,floating): raise RuntimeError("boom")
  self.hypr=FailingHypr()
  plan=Plan("x","",1,"",[Step("arrange","0xaaa",2,"tile")],executable=True,snapshot={"windows":{"0xaaa":{"workspace":{"id":1},"floating":False,"fullscreen":False}}})
  self.store.save_plan({**plan.to_dict(),"query":"","created_at":time.time(),"snapshot":plan.snapshot})
  with self.assertRaisesRegex(RuntimeError,"previous window state was restored"): self.make({}).execute("x")
  self.assertIn(("move_window","0xaaa",1,False),self.hypr.calls)
 def test_store_private_and_bounded(self):
  self.store.save_plan({"token":"x"}); self.assertEqual(stat.S_IMODE(os.stat(self.store.base/"plans.json").st_mode),0o600)
  for i in range(55): self.store.append_history({"i":i})
  self.assertEqual(len(self.store.history()),50)
  self.store.save_plan({"token":"expired","created_at":time.time()-601}); self.assertIsNone(self.store.get_plan("expired")); self.assertFalse(any(plan.get("token") == "expired" for plan in self.store.plans()))
 def test_scene_save_and_semantic_restore_are_executable_without_jev(self):
  director=self.make({})
  saved=director.plan("save this setup as coding")
  self.assertTrue(saved.executable); director.execute(saved.token)
  self.assertEqual(director.scene_manager.get("coding")["name"],"coding")
  self.hypr.moved["0xaaa"]=2
  restore=director.plan("activate coding")
  self.assertTrue(restore.executable); director.execute(restore.token)
  self.assertIn(("move_window","0xaaa",1,False),self.hypr.calls)
 def test_normal_action_can_save_result_as_scene(self):
  director=self.make(answers("move",["0xaaa"],workspace="workspace:2"))
  plan=director.plan("move Terminal to workspace 2 and save as focus desk")
  self.assertTrue(plan.executable); self.assertEqual(plan.steps[-1].operation,"scene_save")
  director.execute(plan.token); self.assertIsNotNone(director.scene_manager.get("focus-desk"))
 def test_workspace_focus_uses_top_level_native_router(self):
  response=answers("keep",workspace="workspace:2"); response["capability"]={"type":"choice","choice":"workspace_focus","confidence":.96}
  plan=self.make(response).plan("go to workspace 2")
  self.assertTrue(plan.executable); self.assertEqual(plan.steps[0].operation,"workspace_focus")
  self.make(response).execute(plan.token); self.assertIn(("focus_workspace",2),self.hypr.calls)
 def test_workspace_focus_can_be_undone_to_the_focused_monitor_workspace(self):
  response=answers("keep",workspace="workspace:2"); response["capability"]={"type":"choice","choice":"workspace_focus","confidence":.96}
  director=self.make(response); plan=director.plan("go to workspace 2"); director.execute(plan.token)
  self.assertEqual(self.hypr.workspace,2)
  director.undo(); self.assertEqual(self.hypr.workspace,1)
 def test_native_capability_executes_registry_step(self):
  response=answers("keep"); response["capability"]={"type":"choice","choice":"nightlight_toggle","confidence":.96}
  native=FakeNative(); director=Director(self.hypr,FakeJev(response),self.store,launcher=Mock(),sleeper=lambda _:None,native=native)
  plan=director.plan("toggle night light"); self.assertTrue(plan.executable)
  director.execute(plan.token); self.assertEqual(native.executed,["nightlight_toggle"])

class DesktopTests(unittest.TestCase):
 def test_safe_allowlist_never_parses_exec(self):
  with tempfile.TemporaryDirectory() as temp:
   path=Path(temp)/".local/share/applications"; path.mkdir(parents=True); (path/"safe.desktop").write_text("[Desktop Entry]\nType=Application\nName=Safe\nExec=bad;cmd\nStartupWMClass=safe\n")
   self.assertEqual(desktop_entries(temp)["safe"]["startup_wm_class"],"safe")
 def test_launch_exact_argv(self):
  spawner=Mock(); launch("safe",{"safe":{"id":"safe"}},spawner); spawner.assert_called_once_with(["gtk-launch","safe"],stdin=-3,stdout=-3,stderr=-3,start_new_session=True,close_fds=True)
 def test_launch_reports_immediate_nonzero_exit(self):
  process=Mock(); process.wait.return_value=1; spawner=Mock(return_value=process)
  with self.assertRaisesRegex(RuntimeError,"status 1"): launch("safe",{"safe":{"id":"safe"}},spawner)

class JevTests(unittest.TestCase):
 def test_real_schema_and_answers(self):
  response=Mock(status=200); response.read.return_value=b'{"answers":{"intent":{"type":"choice","choice":"focus","confidence":0.9,"probabilities":{"focus":0.9,"keep":0.1}},"window:0xaaa":{"type":"noul","noul":0.95}}}'
  conn=Mock(); conn.return_value.getresponse.return_value=response
  result=Jev("/tmp/j",conn).decide({"request":"x"},{"intent":{"type":"choice","instructions":"Choose","criteria":{"focus":"Focus","keep":"No action"}},"window:0xaaa":{"type":"noul","instructions":"Select?","criteria":{"true":"yes","false":"no"}}})
  body=json.loads(conn.return_value.request.call_args.kwargs["body"]); self.assertEqual(set(body),{"model","state","questions"}); self.assertIsInstance(body["questions"],dict); self.assertEqual(body["questions"]["intent"]["criteria"]["focus"],"Focus"); self.assertEqual(result["window:0xaaa"]["noul"],.95)
 def test_gateway_failure(self):
  with self.assertRaises(JevError): Jev("/tmp/j",Mock(side_effect=OSError())).decide({},[])
class HyprTests(unittest.TestCase):
 def test_no_shell(self):
  runner=Mock(return_value=Result("[]")); self.assertEqual(Hyprland(runner).json("clients"),[]); runner.assert_called_once_with(["hyprctl","-j","clients"],capture_output=True,text=True,check=False)
 def test_typed_lua_move_dispatch(self):
  runner=Mock(return_value=Result("true")); Hyprland(runner).move_window("0xAaA",2)
  argv=runner.call_args.args[0]; self.assertEqual(argv[:2],["hyprctl","eval"]); self.assertIn('workspace = "2"',argv[2]); self.assertIn('window = hl.get_window("address:0xaaa")',argv[2])
 def test_named_workspace_is_validated(self):
  runner=Mock(return_value=Result("true")); Hyprland(runner).move_window("0xaaa","name:mac")
  self.assertIn('workspace = "name:mac"',runner.call_args.args[0][2])
  with self.assertRaisesRegex(Exception,"invalid Hyprland workspace"): Hyprland(runner).move_window("0xaaa","name:bad); os.execute('x')")
 def test_floating_setter_only_toggles_when_state_differs(self):
  def run(argv,**kwargs):
   if argv[:3]==["hyprctl","-j","clients"]: return Result('[{"address":"0xaaa","floating":false}]')
   return Result("true")
  runner=Mock(side_effect=run); hypr=Hyprland(runner); hypr.set_floating("0xaaa",False)
  self.assertEqual(runner.call_count,1)
  hypr.set_floating("0xaaa",True)
  self.assertEqual(runner.call_count,3); self.assertIn('action = "toggle"',runner.call_args.args[0][2])
 def test_fullscreen_setter_only_toggles_when_state_differs(self):
  def run(argv,**kwargs):
   if argv[:3]==["hyprctl","-j","clients"]: return Result('[{"address":"0xaaa","fullscreen":1}]')
   return Result("true")
  runner=Mock(side_effect=run); hypr=Hyprland(runner); hypr.set_fullscreen("0xaaa",True)
  self.assertEqual(runner.call_count,1)
  hypr.set_fullscreen("0xaaa",False)
  self.assertEqual(runner.call_count,3); self.assertIn('action = "toggle"',runner.call_args.args[0][2])
 def test_resize_window_validates_bounds_and_uses_typed_dispatch(self):
  clients=[{"address":"0xaaa","at":[967,38],"size":[941,1030],"floating":False,"workspace":{"id":2}},{"address":"0xbbb","at":[12,38],"size":[941,1030],"floating":False,"workspace":{"id":2}}]
  def run(argv,**kwargs):
   if argv[:3]==["hyprctl","-j","clients"]: return Result(json.dumps(clients))
   if argv[:3]==["hyprctl","-j","activewindow"]: return Result(json.dumps(clients[1]))
   return Result("ok")
  runner=Mock(side_effect=run); hypr=Hyprland(runner); hypr.resize_window("0xAaA",800,1030)
  evals=[call.args[0][2] for call in runner.call_args_list if call.args[0][:2]==["hyprctl","eval"]]
  self.assertIn('x = 141, y = 0, relative = true',evals[1]); self.assertIn('address:0xaaa',evals[0]); self.assertIn('address:0xbbb',evals[2])
  with self.assertRaisesRegex(Exception,"invalid window size"): hypr.resize_window("0xaaa",1,560)
 def test_swap_window_focuses_target_uses_typed_direction_and_restores_focus(self):
  def run(argv,**kwargs):
   if argv[:3]==["hyprctl","-j","activewindow"]: return Result(json.dumps({"address":"0xbbb"}))
   return Result("ok")
  runner=Mock(side_effect=run); Hyprland(runner).swap_window("0xaaa","l")
  evals=[call.args[0][2] for call in runner.call_args_list if call.args[0][:2]==["hyprctl","eval"]]
  self.assertIn('address:0xaaa',evals[0]); self.assertIn('direction = "l"',evals[1]); self.assertIn('address:0xbbb',evals[2])

class CliTests(unittest.TestCase):
 def test_history_limit_returns_top_level_items(self):
  fake=Mock(); fake.store.history.return_value=[{"n":1},{"n":2},{"n":3}]
  stream=io.StringIO()
  with patch("director.cli.Director",return_value=fake), patch("sys.stdout",stream): self.assertEqual(main(["history","--limit","2"]),0)
  self.assertEqual(json.loads(stream.getvalue()),{"ok":True,"items":[{"n":2},{"n":3}]})
 def test_diagnostics_omits_snapshots_and_returns_recent_evidence(self):
  fake=Mock(); fake.store.plans.return_value=[{"query":"bad","warnings":["why"],"snapshot":{"secret":"large"}}]; fake.store.history.return_value=[{"summary":"done","snapshot":{"large":True}}]
  stream=io.StringIO()
  with patch("director.cli.Director",return_value=fake), patch("sys.stdout",stream): self.assertEqual(main(["diagnostics"]),0)
  output=json.loads(stream.getvalue()); self.assertNotIn("snapshot",output["plans"][0]); self.assertEqual(output["history"],[{"at":None,"summary":"done","undo_of":None}])
  stream=io.StringIO()
  with patch("director.cli.Director",return_value=fake), patch("sys.stdout",stream): self.assertEqual(main(["diagnostics","--limit","0"]),0)
  self.assertEqual(json.loads(stream.getvalue()),{"ok":True,"plans":[],"history":[]})
