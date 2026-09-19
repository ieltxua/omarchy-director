import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui as Ui

Item {
  id: root

  property bool opened: false
  property bool busy: false
  property bool executing: false
  property bool autoExecutePending: false
  property bool syncingQuery: false
  property string query: ""
  property string plannedQuery: ""
  property string queuedQuery: ""
  property string phase: "idle"
  property string message: ""
  property string errorMessage: ""
  property var plan: null
  property var historyItems: []
  property var sceneItems: []
  property var examples: [
    "Guardá este setup como deep-work",
    "Activá deep-work",
    "Poné X y ChatGPT lado a lado y guardalo como social",
    "Activá modo sin notificaciones",
    "Cambiá al siguiente fondo",
    "Recordame en 20 minutos estirar"
  ]

  readonly property string commandPath: decodeURIComponent(String(Qt.resolvedUrl("bin/omarchy-director")).replace("file://", ""))
  readonly property color background: Color.menu.background
  readonly property color foreground: Color.menu.text
  readonly property color borderColor: Color.menu.border
  readonly property color scrim: Color.menu.scrim
  readonly property color selectedBackground: Color.menu.selectedBackground
  readonly property color selectedText: Color.menu.selectedText
  readonly property var borderSpec: Border.surfaceSpec("menu", "border", borderColor, Math.max(1, Style.space(2)))
  readonly property int cornerRadius: Style.cornerRadius
  readonly property string fontFamily: Style.font.menuFamily
  readonly property int cardWidth: Math.min(Style.space(850), panel.width - Style.gapsOut * 2)
  readonly property int cardHeight: Math.min(Style.space(610), panel.height - Style.gapsOut * 2)
  readonly property var planSteps: plan && plan.steps ? plan.steps : []
  readonly property bool canExecute: plan && plan.executable === true && !!plan.token && !busy
  readonly property string statusLabel: {
    if (phase === "listening") return "ESCUCHANDO"
    if (executing) return "APLICANDO"
    if (busy) return "ENTENDIENDO"
    if (phase === "ready") return "LISTO"
    if (phase === "done") return "HECHO"
    if (phase === "error") return "REVISAR"
    return "JEV"
  }

  function setQuery(value, planNow) {
    syncingQuery = true
    query = String(value || "")
    commandField.text = query
    commandField.cursorPosition = commandField.text.length
    syncingQuery = false
    if (planNow && query.trim()) requestPlan(true)
  }

  function open(payloadJson) {
    var payload = {}
    if (payloadJson) {
      try { payload = JSON.parse(payloadJson) || {} } catch (e) { payload = {} }
    }
    opened = true
    errorMessage = ""
    message = ""
    phase = "idle"
    plan = null
    autoExecutePending = payload.execute === true
    loadHistory()
    loadScenes()
    setQuery(payload.query || "", false)
    if (payload.voice === "recording") {
      phase = "listening"
      message = "Hablá normal. Volvé a activar voz para terminar y ejecutar."
    }
    Qt.callLater(function() {
      commandField.forceActiveFocus()
      if (payload.query) requestPlan(true)
    })
  }

  function close() {
    previewTimer.stop()
    opened = false
  }

  function toggle(payloadJson) {
    if (opened) close()
    else open(payloadJson)
  }

  function requestPlan(immediate) {
    var next = commandField.text.trim()
    query = next
    if (!next) {
      plan = null
      phase = "idle"
      errorMessage = ""
      return
    }
    if (planProc.running) {
      queuedQuery = next
      return
    }
    queuedQuery = ""
    plannedQuery = next
    busy = true
    executing = false
    phase = "planning"
    errorMessage = ""
    planProc.command = [commandPath, "plan", "--query", next]
    planProc.running = true
  }

  function consumePlan(raw) {
    busy = false
    try {
      var result = JSON.parse(raw)
      if (result.ok === false || result.error) {
        plan = null
        phase = "error"
        errorMessage = result.message || (typeof result.error === "string" ? result.error : (result.error && result.error.message)) || "No pude preparar un plan seguro."
      } else {
        plan = result.plan || result
        phase = plan.executable ? "ready" : "error"
        errorMessage = plan.executable ? "" : (plan.message || "Necesito una orden más específica.")
        if (plan.executable && autoExecutePending) {
          autoExecutePending = false
          if (isSafeForAutoExecute(plan)) Qt.callLater(function() { root.executePlan() })
          else message = "Esta acción necesita Enter porque no tiene un undo completo."
        }
      }
    } catch (e) {
      plan = null
      phase = "error"
      errorMessage = "Director devolvió una respuesta inválida."
    }
  }

  function isSafeForAutoExecute(candidate) {
    return !!candidate && candidate.auto_executable === true
  }

  function executePlan() {
    if (!canExecute) {
      requestPlan(true)
      return
    }
    busy = true
    executing = true
    phase = "executing"
    errorMessage = ""
    executeProc.command = [commandPath, "execute", "--token", String(plan.token)]
    executeProc.running = true
  }

  function consumeExecution(raw) {
    busy = false
    executing = false
    try {
      var result = JSON.parse(raw)
      if (result.ok === false || result.error) {
        phase = "error"
        errorMessage = result.message || (typeof result.error === "string" ? result.error : (result.error && result.error.message)) || "No pude aplicar el plan."
      } else {
        phase = "done"
        message = result.message || "Listo. Ctrl+Z deshace la última acción."
        plan = null
        loadHistory()
        loadScenes()
        doneCloseTimer.restart()
      }
    } catch (e) {
      phase = "error"
      errorMessage = "La acción terminó sin una confirmación válida."
    }
  }

  function undo() {
    if (busy) return
    doneCloseTimer.stop()
    busy = true
    executing = true
    phase = "executing"
    errorMessage = ""
    undoProc.command = [commandPath, "undo"]
    undoProc.running = true
  }

  function consumeUndo(raw) {
    busy = false
    executing = false
    try {
      var result = JSON.parse(raw)
      if (result.ok === false || result.error) {
        phase = "error"
        errorMessage = result.message || (typeof result.error === "string" ? result.error : (result.error && result.error.message)) || "No hay una acción reversible."
      } else {
        phase = "done"
        message = result.message || "Restauré el estado anterior."
        loadHistory()
      }
    } catch (e) {
      phase = "error"
      errorMessage = "Undo terminó sin una confirmación válida."
    }
  }

  function loadHistory() {
    if (historyProc.running) return
    historyProc.command = [commandPath, "history", "--limit", "6"]
    historyProc.running = true
  }

  function consumeHistory(raw) {
    try {
      var result = JSON.parse(raw)
      historyItems = result.items || result.history || []
    } catch (e) {
      historyItems = []
    }
  }

  function loadScenes() {
    if (scenesProc.running) return
    scenesProc.command = [commandPath, "scenes", "list"]
    scenesProc.running = true
  }

  function consumeScenes(raw) {
    try {
      var result = JSON.parse(raw)
      var rows = result.items || []
      sceneItems = rows.map(function(scene) {
        return { query: "activate " + scene.name, summary: "◈ " + scene.name }
      })
    } catch (e) {
      sceneItems = []
    }
  }

  function stepText(step) {
    if (typeof step === "string") return step
    if (!step) return ""
    return String(step.summary || step.label || step.description || step.action || "")
  }

  function historyText(item) {
    if (typeof item === "string") return item
    if (!item) return ""
    return String(item.summary || item.query || item.message || "")
  }

  function historyQuery(item) {
    if (typeof item === "string") return item
    if (!item) return ""
    return String(item.query || item.summary || item.message || "")
  }

  Timer {
    id: previewTimer
    interval: 320
    repeat: false
    onTriggered: root.requestPlan(false)
  }

  Timer {
    id: doneCloseTimer
    interval: 1150
    repeat: false
    onTriggered: root.close()
  }

  Process {
    id: planProc
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.consumePlan(String(text || ""))
    }
    onExited: function(exitCode) {
      root.busy = false
      if (root.queuedQuery && root.queuedQuery !== root.plannedQuery) root.requestPlan(true)
    }
  }

  Process {
    id: executeProc
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.consumeExecution(String(text || ""))
    }
    onExited: root.busy = false
  }

  Process {
    id: undoProc
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.consumeUndo(String(text || ""))
    }
    onExited: root.busy = false
  }

  Process {
    id: historyProc
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.consumeHistory(String(text || ""))
    }
  }

  Process {
    id: scenesProc
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.consumeScenes(String(text || ""))
    }
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "ieltxu-director"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore

    Rectangle {
      anchors.fill: parent
      color: root.scrim

      Behavior on opacity { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
    }

    MouseArea {
      anchors.fill: parent
      onClicked: root.close()
    }

    Ui.BorderSurface {
      id: card
      anchors.centerIn: parent
      width: root.cardWidth
      height: root.cardHeight
      radius: root.cornerRadius
      color: root.background
      borderSpec: root.borderSpec
      padding: Style.spacing.panelPadding

      MouseArea { anchors.fill: parent; onClicked: {} }

      Column {
        anchors.fill: parent
        anchors.topMargin: card.contentTopInset
        anchors.rightMargin: card.contentRightInset
        anchors.bottomMargin: card.contentBottomInset
        anchors.leftMargin: card.contentLeftInset
        spacing: Style.spacing.md

        Row {
          width: parent.width
          height: Style.space(36)
          spacing: Style.space(10)

          Text {
            width: Style.space(30)
            anchors.verticalCenter: parent.verticalCenter
            text: "󰆍"
            color: Color.accent
            font.family: root.fontFamily
            font.pixelSize: Style.font.heading
            horizontalAlignment: Text.AlignHCenter
          }

          Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "Director"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.heading
            font.bold: true
          }

          Item { width: parent.width - Style.space(220); height: 1 }

          Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: statusText.implicitWidth + Style.space(18)
            height: Style.space(25)
            radius: height / 2
            color: root.phase === "error" ? Util.alpha(Color.urgent, 0.18) : Util.alpha(Color.accent, 0.14)

            Text {
              id: statusText
              anchors.centerIn: parent
              text: root.statusLabel
              color: root.phase === "error" ? Color.urgent : Color.accent
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
            }
          }
        }

        Ui.TextField {
          id: commandField
          width: parent.width
          height: Style.space(56)
          placeholderText: "Decile a Omarchy qué querés ver…"
          foreground: root.foreground
          accent: Color.accent
          horizontalPadding: Style.space(16)
          verticalPadding: Style.space(13)

          onTextChanged: {
            if (root.syncingQuery) return
            root.query = text
            root.plan = null
            root.phase = text.trim() ? "typing" : "idle"
            root.errorMessage = ""
            root.message = ""
            previewTimer.restart()
          }

          Keys.onPressed: function(event) {
            if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_Z) {
              root.undo()
              event.accepted = true
            } else if (event.key === Qt.Key_Escape) {
              root.close()
              event.accepted = true
            } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
              if (root.canExecute) root.executePlan()
              else root.requestPlan(true)
              event.accepted = true
            }
          }
        }

        Item {
          width: parent.width
          height: parent.height - Style.space(36) - Style.space(56) - Style.spacing.md * 3 - footer.height

          Column {
            anchors.fill: parent
            spacing: Style.spacing.md

            Text {
              visible: !root.query.trim() && root.historyItems.length === 0
              width: parent.width
              text: "Construí un escritorio, guardalo y volvé a invocarlo. Director compone ventanas, escenas y capacidades nativas de Omarchy."
              color: root.foreground
              opacity: 0.72
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              wrapMode: Text.WordWrap
            }

            Column {
              visible: !root.query.trim()
              width: parent.width
              spacing: Style.space(5)

              Repeater {
                model: root.sceneItems.concat(root.historyItems.length > 0 ? root.historyItems : root.examples)

                Rectangle {
                  required property var modelData
                  width: parent.width
                  height: Style.space(43)
                  radius: root.cornerRadius
                  color: exampleMouse.containsMouse ? root.selectedBackground : "transparent"

                  Text {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: Style.space(12)
                    anchors.rightMargin: Style.space(12)
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.historyText(parent.modelData)
                    color: exampleMouse.containsMouse ? root.selectedText : root.foreground
                    opacity: exampleMouse.containsMouse ? 1 : 0.82
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    elide: Text.ElideRight
                  }

                  MouseArea {
                    id: exampleMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.setQuery(root.historyQuery(parent.modelData), true)
                  }
                }
              }
            }

            Column {
              visible: !!root.query.trim()
              width: parent.width
              spacing: Style.space(8)

              Text {
                width: parent.width
              text: root.phase === "listening" ? "Estoy escuchando…" : (root.busy ? "Leyendo tu escritorio…" : (root.plan ? (root.plan.summary || "Plan") : "Esperando una intención clara…"))
                color: root.foreground
                opacity: root.busy ? 0.62 : 1
                font.family: root.fontFamily
                font.pixelSize: Style.font.title
                font.bold: !!root.plan
                wrapMode: Text.WordWrap
              }

              Repeater {
                model: root.planSteps

                Row {
                  required property var modelData
                  width: parent.width
                  height: Style.space(34)
                  spacing: Style.space(10)

                  Rectangle {
                    width: Style.space(22)
                    height: width
                    anchors.verticalCenter: parent.verticalCenter
                    radius: width / 2
                    color: Util.alpha(Color.accent, 0.16)

                    Text {
                      anchors.centerIn: parent
                      text: "✓"
                      color: Color.accent
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      font.bold: true
                    }
                  }

                  Text {
                    width: parent.width - Style.space(32)
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.stepText(parent.modelData)
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    elide: Text.ElideRight
                  }
                }
              }

              Text {
                visible: !!root.errorMessage
                width: parent.width
                text: root.errorMessage
                color: Color.urgent
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                wrapMode: Text.WordWrap
              }

              Repeater {
                model: root.plan && root.plan.warnings ? root.plan.warnings : []

                Text {
                  required property var modelData
                  width: parent.width
                  text: String(modelData)
                  color: Color.urgent
                  opacity: 0.9
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  wrapMode: Text.WordWrap
                }
              }

              Text {
                visible: !!root.message
                width: parent.width
                text: root.message
                color: Color.accent
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                wrapMode: Text.WordWrap
              }
            }
          }
        }

        Row {
          id: footer
          width: parent.width
          height: Style.space(28)
          spacing: Style.space(18)

          Text {
            text: root.canExecute ? "↵ aplicar" : "↵ preparar"
            color: root.canExecute ? Color.accent : root.foreground
            opacity: root.canExecute ? 1 : 0.58
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          Text {
            text: "Ctrl+Z deshacer"
            color: root.foreground
            opacity: 0.58
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          Item { width: parent.width - Style.space(250); height: 1 }

          Text {
            text: "Esc cerrar"
            color: root.foreground
            opacity: 0.58
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }
    }
  }
}
