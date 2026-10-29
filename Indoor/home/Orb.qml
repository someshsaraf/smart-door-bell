import QtQuick
import QtQuick.Shapes
import QtQuick.Effects

// The voice button's orb: soft colours swirling inside a glassy sphere. Slow when idle,
// lively while listening, spinning while thinking.
Item {
    id: orb
    property string mode: ""   // "", "listening", "thinking"
    property real size: 64
    property var colors: ["#7aa2ff", "#36d6c3", "#b47cff", "#ff9ad5"]
    width: size; height: size
    property real spin: 0
    property real drift: 0
    NumberAnimation on spin {
        from: 0; to: 360; loops: Animation.Infinite
        duration: orb.mode === "thinking" ? 1600 : orb.mode === "listening" ? 4000 : 14000
    }
    NumberAnimation on drift {
        from: 0; to: Math.PI * 2; loops: Animation.Infinite
        duration: orb.mode === "listening" ? 2600 : 9000
    }
    scale: orb.mode === "listening" ? 1.0 + 0.06 * Math.sin(drift * 3) : 1.0

    Item {
        id: paint; anchors.fill: parent; visible: false
        Shape {
            anchors.fill: parent; preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeWidth: 0; strokeColor: "transparent"
                fillGradient: ConicalGradient {
                    centerX: orb.size / 2; centerY: orb.size / 2; angle: orb.spin
                    GradientStop { position: 0.0; color: orb.colors[0] }
                    GradientStop { position: 0.3; color: orb.colors[1] }
                    GradientStop { position: 0.6; color: orb.colors[2] }
                    GradientStop { position: 0.85; color: orb.colors[3] }
                    GradientStop { position: 1.0; color: orb.colors[0] }
                }
                PathAngleArc {
                    centerX: orb.size / 2; centerY: orb.size / 2; radiusX: orb.size / 2; radiusY: orb.size / 2
                    startAngle: 0; sweepAngle: 360
                }
            }
        }
        Repeater {
            model: 3
            Rectangle {
                width: orb.size * 0.55; height: width; radius: width / 2
                color: orb.colors[(index + 1) % 4]; opacity: 0.85
                x: orb.size / 2 - width / 2 + Math.cos(orb.drift + index * 2.1) * orb.size * 0.22
                y: orb.size / 2 - height / 2 + Math.sin(orb.drift * 1.3 + index * 2.1) * orb.size * 0.22
            }
        }
    }
    MultiEffect {
        anchors.fill: parent; source: paint
        blurEnabled: true; blur: 0.55; blurMax: 32; saturation: 0.15
        autoPaddingEnabled: false  // the blur stays inside, so the round mask fits the orb exactly
        maskEnabled: true; maskSource: circle; maskThresholdMin: 0.5; maskSpreadAtMin: 1.0
    }
    Item {
        id: circle; anchors.fill: parent; visible: false; layer.enabled: true; layer.smooth: true
        Rectangle { anchors.fill: parent; radius: width / 2; color: "black"; antialiasing: true }
    }
    // the glassy highlight and rim
    Rectangle {
        anchors.fill: parent; radius: width / 2; antialiasing: true
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.45) }
            GradientStop { position: 0.45; color: Qt.rgba(1, 1, 1, 0.0) }
            GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.12) }
        }
        border.width: Math.max(1, orb.size / 64); border.color: Qt.rgba(1, 1, 1, 0.35)
    }
}
