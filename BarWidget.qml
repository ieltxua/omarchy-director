import QtQuick
import qs.Ui

BarWidget {
  id: root
  moduleName: "ieltxu.director"
  readonly property string voicePath: decodeURIComponent(String(Qt.resolvedUrl("bin/omarchy-director-voice")).replace("file://", ""))
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰆍"
    tooltipText: "Director · click: escribir · click derecho: voz con vista previa"
    onPressed: function(button) {
      if (!root.bar) return
      if (button === Qt.RightButton)
        root.bar.run(root.voicePath + " toggle --preview")
      else if (button === Qt.LeftButton)
        root.bar.run("omarchy-shell shell call ieltxu.director toggle '{}'")
    }
  }
}
