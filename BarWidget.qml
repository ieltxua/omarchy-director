import QtQuick
import qs.Ui

BarWidget {
  id: root
  moduleName: "io.github.ieltxua.director"
  readonly property string voicePath: decodeURIComponent(String(Qt.resolvedUrl("bin/omarchy-director-voice")).replace("file://", ""))
  readonly property string voiceMode: settings && settings.voiceMode === "yolo" ? "yolo" : "preview"
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰆍"
    tooltipText: "Director · click: escribir · click derecho: voz " + (root.voiceMode === "yolo" ? "YOLO" : "con vista previa")
    onPressed: function(button) {
      if (!root.bar) return
      if (button === Qt.RightButton)
        root.bar.run(root.voicePath + " toggle --" + root.voiceMode)
      else if (button === Qt.LeftButton)
        root.bar.run("omarchy-shell shell call io.github.ieltxua.director toggle '{}'")
    }
  }
}
