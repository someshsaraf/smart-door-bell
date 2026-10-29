import QtQuick

// Headlines gliding past: channel name, headline, a small mark between them.
Item {
    id: tk
    property var items: []
    property color color: "white"
    property color sourceColor: color
    property color markColor: color
    property string family: "Inter Variable"
    property real pixelSize: 22
    property int weight: Font.DemiBold
    property bool italic: false
    property real speed: 80   // pixels a second
    clip: true

    component Strip: Row {
        Repeater {
            model: tk.items
            Row {
                spacing: tk.pixelSize * 0.6
                height: tk.height
                Text {
                    text: (modelData.source || "").toUpperCase(); color: tk.sourceColor
                    font.family: "Inter Variable"; font.pixelSize: tk.pixelSize * 0.62; font.weight: Font.Bold
                    font.letterSpacing: tk.pixelSize * 0.08
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    text: modelData.title; color: tk.color
                    font.family: tk.family; font.pixelSize: tk.pixelSize; font.weight: tk.weight; font.italic: tk.italic
                    anchors.verticalCenter: parent.verticalCenter
                }
                Rectangle {
                    width: tk.pixelSize * 0.3; height: width; rotation: 45; color: tk.markColor; opacity: 0.8
                    anchors.verticalCenter: parent.verticalCenter
                }
                Item { width: tk.pixelSize * 0.6; height: 1 }
            }
        }
    }
    Row {
        id: belt
        height: tk.height
        Strip { id: one }
        Strip { }
        NumberAnimation on x {
            id: run; from: 0; to: -one.width; loops: Animation.Infinite
            duration: Math.max(1000, one.width / tk.speed * 1000)
            running: tk.visible && one.width > 0
        }
    }
    onItemsChanged: run.restart()
}
