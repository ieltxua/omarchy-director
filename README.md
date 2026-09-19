# Director for Omarchy

Director is a theme-native Omarchy shell plugin that turns natural language into
typed, previewable Hyprland actions. It can arrange windows, navigate workspaces,
control selected Omarchy features, and capture entire desktops as reusable scenes.

This repository is an experimental release candidate (`2.1.0-rc.5`): it is
AI-assisted/vibe-coded software, provided for hands-on evaluation. It is local-first,
collects no telemetry, and is not marketplace-verified. Omarchy shell plugins are
unsandboxed code; review the source and trust the checkout before enabling it.

Jev interprets intent from closed candidate sets. Local deterministic code owns
permissions, validation, exact arguments, execution, verification, and undo.
Prompt text is never executed as shell.

## Highlights

- **Programmable desktops:** capture, update, invoke, list, and delete named scenes.
- **Address-free restore:** scenes match semantic window identity instead of stale
  Hyprland addresses and can launch identifiable missing applications.
- **Composition:** say `float ChatGPT and save as review` in one request.
- **Native control:** focus, move, resize, tile, float, fullscreen, launch, themes, audio,
  brightness, global window rounding, night light, notification silencing,
  capture, reminders, and lock.
- **Real undo:** restores observed window, workspace, scene, theme, volume, and
  brightness state instead of blindly issuing the opposite command.
- **Omarchy UI:** uses the current shell theme, typography, spacing, borders, and
  animation primitives. There is no separate Director theme to maintain.
- **Voice adapter:** optional Voxtype preview and guarded hands-free execution.

## Requirements

Required:

- Omarchy with shell-plugin support (`omarchy`/`omarchy-shell`) and typed
  Hyprland dispatchers.
- Python 3.10 or newer and `hyprctl`.
- An OpenRouter API key for the bundled local Jev gateway. Jev is required for
  semantic planning; the pinned model is `typesafe/jev-1.13`.

Optional:

- `voxtype` for voice commands.
- A microphone helper accepting `start` and `stop`, configured through
  `DIRECTOR_MIC_CONTROL_BIN`, for Bluetooth/profile bridges.

Director has no TypeSafe credential. Its setup command stores the OpenRouter key
in a user-only file; within Director, only the bundled gateway opens it for
provider authentication. The QML plugin and planning process never receive it.
Because Omarchy plugins are unsandboxed under the same Unix account, another
same-user plugin could still read that file. Use a dedicated, low-limit key.

## Installation

Omarchy plugins are git repositories. Install Director with:

```bash
omarchy plugin add https://github.com/ieltxua/omarchy-director --enable
```

The Omarchy installer intentionally executes no plugin hooks. Run Director's
single explicit setup step from the managed checkout; it installs the CLI links,
then configures and starts the private user service:

```bash
cd ~/.config/omarchy/plugins/io.github.ieltxua.director
./install.sh --setup
omarchy-director doctor
```

`doctor` probes both the local socket and the provider's authentication endpoint;
it does not spend a Jev inference request.

`setup` reads `OPENROUTER_API_KEY` when it is already exported; otherwise it asks
for the key with hidden input. For automation without an environment variable,
pipe it to `omarchy-director setup --key-stdin`. Never place the key in an argument.

### Providers and adapters

The RC currently ships one supported adapter:

| Provider | Credential | Endpoint | Model policy |
| --- | --- | --- | --- |
| `openrouter` | `OPENROUTER_API_KEY` | OpenRouter Decisions API | pinned `typesafe/jev-1.13` |

It can be selected explicitly with `omarchy-director setup --provider openrouter`.
Provider authentication and HTTP details live behind
`director.providers.ProviderAdapter`; the Unix-socket protocol, typed validation,
policy, and Director client remain provider-neutral. Adding a provider requires a
new adapter, one registry entry, credential metadata, contract tests, and docs.
Unknown providers and model overrides fail closed. The current adapter neither
requests nor assumes a direct TypeSafe credential.

Setup is the supported path for preparing local dependencies. Left-click opens the text
palette; right-click starts voice in preview mode when Voxtype is installed.

### Optional CLI, launcher, man page, and shortcuts

The official Omarchy plugin installer intentionally runs no hooks. Director's
optional integration script must therefore be invoked explicitly:

```bash
cd ~/.config/omarchy/plugins/io.github.ieltxua.director
./install.sh                 # CLI, launcher, and man page
./install.sh --setup         # above plus the bundled Jev gateway
```

This adds user-owned CLI links, a desktop launcher, and `man omarchy-director`.
It does not edit Hyprland configuration unless you opt in:

```bash
./install.sh --bindings         # F10 and Super+Alt+J
./install.sh --voice-bindings   # above plus F8 preview and Super+Alt+V YOLO
```

The script refuses to overwrite unrelated commands or desktop entries and backs
up `bindings.lua` before changing its marked Director block.

## Jev configuration

The bundled gateway listens on
`$XDG_RUNTIME_DIR/omarchy-director/jev.sock`. Director searches, in order:

1. `JEV_SOCKET_PATH`;
2. the saved `jev_socket_path`;
3. `$XDG_RUNTIME_DIR/jev-gateway/jev.sock`;
4. `$XDG_RUNTIME_DIR/agent-lab/jev.sock`;
5. `$XDG_RUNTIME_DIR/jev.sock`.

If setup is unavailable or you need a manual override, set the socket explicitly
and verify the runtime:

```bash
export JEV_SOCKET_PATH=/run/user/1000/jev-gateway/jev.sock
omarchy-director doctor
```

The CLI also retains the explicit configuration command:

```bash
omarchy-director configure --jev-socket /run/user/1000/jev-gateway/jev.sock
```

When Jev is unavailable, deterministic status, scene listing, and undo still work;
Director will not guess a new consequential plan.

## Usage

Open the palette and speak or type normally:

```text
move all terminals to workspace 3
make X 20% smaller
make the current window larger
make all window borders rounded
make every window square
move X to the left
open Slack on workspace 2
put Slack and Chromium side by side
take me to X
float ChatGPT
go to workspace 2
save this setup as deep-work
activate deep-work
move the terminals to workspace 4 and save as backend
toggle night light
silence notifications
raise volume 5 percent
change to the next wallpaper
take a fullscreen screenshot
remind me in 20 minutes to stretch
```

The preview updates as you type. Press **Enter** to execute, **Ctrl+Z** to undo the
latest reversible execution, and **Escape** to close.

Saved scenes appear on Director's home view as click-to-run entries. A scene stores
semantic application/window identity, workspace, tiled/floating/fullscreen state,
floating geometry, and the focused window. It never stores temporary window
addresses.

### CLI

```bash
omarchy-director status
omarchy-director plan --query 'put X and ChatGPT side by side'
omarchy-director diagnostics --limit 20
omarchy-director undo
omarchy-director history --limit 10

omarchy-director scenes save --name deep-work
omarchy-director scenes list
omarchy-director scenes apply --name deep-work
omarchy-director scenes update --name deep-work
omarchy-director scenes delete --name deep-work
```

See `omarchy-director --help` or `man omarchy-director` for the complete interface.

### Declarative customization

Aliases and voice defaults live in the private XDG config file and can be changed
without editing the plugin:

```bash
omarchy-director configure --app-alias 'browser=firefox.desktop'
omarchy-director configure --window-alias 'chat=Slack'
omarchy-director configure --voice-mode preview
omarchy-director configure --yolo-allow 'focus,move,arrange,volume_up,volume_down'
omarchy-director configure --show
```

App aliases target an installed desktop-entry ID. Window aliases target a unique
class/title substring. The YOLO list can only narrow Director's compiled hard
safety policy; adding an unsafe operation does not make it auto-executable. The
bar's right-click mode is also configurable through its native widget setting.

## Voice and YOLO

Voice preview is the public default:

```bash
omarchy-director-voice toggle --preview
```

Explicit YOLO asks Director to execute after transcription:

```bash
omarchy-director-voice toggle --yolo
```

YOLO does not bypass policy. Actions without a complete local undo boundary remain
in preview and require Enter. This includes application launches, scene application
that may launch apps, screenshots, recordings, reminders, audio-output switching,
wallpaper changes, and lock. Voice uses Voxtype's file-output mode and never types
into the application that currently has focus.

## Safety, privacy, and undo boundaries

Omarchy shell plugins are unsandboxed code running as your user. Review the source
before enabling any third-party plugin.

Director sends the user's command plus a compact inventory of window/application
candidates to the configured local Jev gateway. It does not send credentials,
clipboard contents, browser/page contents, environment variables, or arbitrary
files, and collects no telemetry. Jev returns typed choices and never grants
execution authority.

Director rejects and redacts common credential formats and assignment syntax,
but no pattern matcher can recognize every secret. Do not put passwords, tokens,
keys, or private configuration in desktop commands.

Customization is declarative through the plugin's typed configuration and scene
data; it does not provide arbitrary shell hooks. YOLO cannot bypass hard safety
validation or turn an ineligible action into automatic execution.

Execution uses a fixed action registry:

- desktop applications and themes come from live installed allowlists;
- window addresses and workspace values are validated before typed dispatch;
- numeric volume, brightness, duration, and message inputs are bounded;
- each plan is stored behind an expiring random token and rechecks stale windows;
- partial failures roll back the captured state when possible.

Undo is intentionally honest. It restores recorded local state, but does not close
newly launched applications or delete screenshots, recordings, or reminder
artifacts. See [SECURITY.md](SECURITY.md) for the complete trust model.

## Storage

Director follows XDG directories:

- configuration: `$XDG_CONFIG_HOME/omarchy-director/config.json`;
- scenes/history: `$XDG_STATE_HOME/omarchy-director/`;
- voice transients: `$XDG_RUNTIME_DIR/omarchy-director/`.

Configuration, scenes, history, and temporary transcripts use user-only
permissions. Removal preserves scenes and history unless the user deletes them.
The local diagnostics ring keeps the latest 500 compact plan outcomes, including
the typed command, warnings, and selected steps but no desktop snapshots.
Credential-like values are redacted before plan or diagnostic persistence. Use
the ring to turn real failures into regression cases.

## Update and removal

Update through Omarchy's reviewed fast-forward flow:

```bash
omarchy plugin update io.github.ieltxua.director
```

Remove optional integrations first, while the checkout still exists:

```bash
cd ~/.config/omarchy/plugins/io.github.ieltxua.director
./uninstall.sh
omarchy plugin remove io.github.ieltxua.director
```

`./uninstall.sh` stops and removes the bundled user service but preserves the
credential, scenes, history, and configuration. Use `./uninstall.sh --purge-key`
only when you also want the stored OpenRouter key removed.

The uninstall script removes only artifacts it can identify as Director-managed,
moves the man page/desktop entry and binding backup into Director's state directory,
and leaves scenes and history intact.

## Troubleshooting

Run:

```bash
omarchy-director doctor
omarchy plugin validate ~/.config/omarchy/plugins/io.github.ieltxua.director
omarchy plugin list --json | jq '.[] | select(.id == "io.github.ieltxua.director")'
journalctl --user --since '10 minutes ago' | grep -i director
```

- **No plan:** verify the Jev socket and local gateway with `doctor`.
- **CLI not found:** run the optional `./install.sh` or use
  `~/.config/omarchy/plugins/io.github.ieltxua.director/bin/omarchy-director` directly.
- **Voice unavailable:** install Voxtype and verify an input source; text mode is
  independent of voice.
- **Shortcut missing:** shortcuts are optional; run `./install.sh --bindings`.
- **Theme name rejected:** use an exact value from `omarchy theme list`.

## Development and release

```bash
./tests/director-lab fast
./tests/director-lab stress
./tests/director-lab api-audit --report ~/.local/state/omarchy-director/api-audit.json
```

The fast suite runs unit, policy, voice-adapter, packaging, Python compile, JSON,
shell-syntax, and symlink checks, including more than 5,000 generated desktop
states and action sequences. The stress gate raises that deterministic population
to at least 10,000 cases. Replay any failure with its reported seed:

```bash
DIRECTOR_GENERATIVE_SEED=20260919 DIRECTOR_GENERATED_CASES=10000 \
  ./tests/director-lab stress
```

Two explicit gates exercise real integrations and therefore do not run in the
portable GitHub job:

```bash
# Real pinned Jev; plans against a synthetic desktop and never executes them.
./tests/director-lab semantic --report ~/.local/state/omarchy-director/semantic-report.json

# Exhaustive 242-phrase bilingual capability, paraphrase, ambiguity, and
# unsupported-action corpus. Defaults to 90 requests/minute.
./tests/director-lab semantic-all --report ~/.local/state/omarchy-director/semantic-all-report.json

# Real Omarchy/Hyprland; owns only two Foot fixtures on reserved workspaces 91-92.
./tests/director-lab live --report ~/.local/state/omarchy-director/e2e-report.json
```

`semantic-all` reports semantic and infrastructure failures separately. It retries
one transient gateway failure by default, records recovered cases, and never retries
a semantic mismatch. During development, repeat `--id-prefix FAMILY` to run only
affected families without changing their order. `api-audit` inventories the installed
Omarchy and Hyprland command surfaces, verifies every supported capability mapping,
and lists available-but-unimplemented opportunities and explicit policy exclusions.

The live runner aborts if its workspaces are occupied or stale fixtures exist,
checks the effect and exact undo after every case, kills only processes it started,
and restores the previously focused workspace. On Omarchy the fast suite also
invokes the native plugin validator. A stable release requires all four gates plus
bar, F10, and one real microphone smoke test when voice behavior changed.

The current headless acceptance run passes 9 of 10 live compositor cases. Exact window
focus is the remaining acceptance gap: the typed Hyprland dispatcher returns
success and the target workspace is selected, but a compositor session without
an active input seat does not update `activewindow`. Validate focus once through
the real Moonlight/keyboard session before treating this candidate as stable.

See [CONTRIBUTING.md](CONTRIBUTING.md), [CHANGELOG.md](CHANGELOG.md), and
[SECURITY.md](SECURITY.md).

## License

0BSD © 2026 Director contributors. See [LICENSE](LICENSE).
