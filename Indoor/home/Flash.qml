import QtQuick
import QtQuick.Effects
import "util.js" as U

// A big banner for a breaking story that just came in; it slides down, stays a while, leaves.
Item {
    id: fl
    property var story: ({})
    property real u: 1
    property color accent: "#e5233a"
    readonly property bool on: !!(story && story.title)
    property var shown: ({})
    onStoryChanged: if (story && story.title) shown = story  // kept while the banner slides away
    width: 1180 * u; height: 168 * u
    y: on ? 22 * u : -height - 40 * u
    opacity: on ? 1 : 0
    Behavior on y { NumberAnimation { duration: 650; easing.type: Easing.OutCubic } }
    Behavior on opacity { NumberAnimation { duration: 400 } }

    Rectangle {
        anchors.fill: parent; radius: 26 * fl.u; color: "#17090c"
        border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.12)
        layer.enabled: true
        layer.effect: MultiEffect { shadowEnabled: true; shadowBlur: 1.0; shadowOpacity: 0.55; shadowVerticalOffset: 14 * fl.u; shadowColor: "black" }
    }
    Rectangle { x: 18 * fl.u; y: 22 * fl.u; width: 6 * fl.u; height: parent.height - 44 * fl.u; radius: 3 * fl.u; color: fl.accent }
    Row {
        x: 44 * fl.u; y: 24 * fl.u; spacing: 14 * fl.u
        Rectangle {
            width: tag.width + 28 * fl.u; height: 34 * fl.u; radius: 17 * fl.u; color: fl.accent
            Text {
                id: tag; anchors.centerIn: parent; text: "BREAKING"; color: "white"
                font.family: "Inter Variable"; font.pixelSize: 15 * fl.u; font.weight: Font.Black; font.letterSpacing: 2 * fl.u
            }
            SequentialAnimation on opacity {
                running: fl.on; loops: Animation.Infinite
                NumberAnimation { to: 0.55; duration: 700 }
                NumberAnimation { to: 1; duration: 700 }
            }
        }
        Text {
            text: (fl.shown.source || "") + "  ·  " + U.ago(fl.shown.time || 0); color: Qt.rgba(1, 1, 1, 0.7)
            font.family: "Inter Variable"; font.pixelSize: 17 * fl.u; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter
        }
    }
    Text {
        x: 44 * fl.u; y: 74 * fl.u; width: parent.width - 88 * fl.u
        text: fl.shown.title || ""; color: "white"; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight
        font.family: "Inter Variable"; font.pixelSize: 33 * fl.u; font.weight: Font.Bold; lineHeight: 1.05
    }
}
