import QtQuick
import QtQuick.Particles

// Festival decoration over everything: Diwali sparks rising, Christmas snow, New Year
// confetti, and the greeting. Touches pass through.
Item {
    id: fe
    property string key: ""
    property string greeting: ""
    property real u: 1
    property color textColor: "#ffd27a"
    visible: key !== ""
    enabled: false

    ParticleSystem { id: ps; running: fe.visible }
    ImageParticle {
        system: ps; groups: ["spark"]; source: "image://home/dot"
        color: "#ffc062"; colorVariation: 0.25; alpha: 0.9; entryEffect: ImageParticle.Fade
    }
    ImageParticle {
        system: ps; groups: ["snow"]; source: "image://home/dot"
        color: "#ffffff"; alpha: 0.85; entryEffect: ImageParticle.Fade
    }
    ImageParticle {
        system: ps; groups: ["confetti"]; source: "image://home/confetti"
        color: "#ffd54a"; colorVariation: 1.0; rotationVariation: 180; rotationVelocityVariation: 220
    }
    Emitter {
        system: ps; group: "spark"; enabled: fe.key === "diwali"
        anchors.bottom: parent.bottom; width: parent.width; height: 10
        emitRate: 26; lifeSpan: 6500; lifeSpanVariation: 1500; size: 9 * fe.u; sizeVariation: 6 * fe.u; endSize: 2 * fe.u
        velocity: AngleDirection { angle: 270; angleVariation: 12; magnitude: 70 * fe.u; magnitudeVariation: 40 * fe.u }
    }
    Emitter {
        system: ps; group: "snow"; enabled: fe.key === "christmas"
        anchors.top: parent.top; width: parent.width; height: 10
        emitRate: 40; lifeSpan: 11000; size: 8 * fe.u; sizeVariation: 6 * fe.u
        velocity: AngleDirection { angle: 90; angleVariation: 10; magnitude: 60 * fe.u; magnitudeVariation: 30 * fe.u }
    }
    Emitter {
        system: ps; group: "confetti"; enabled: fe.key === "new_year"
        anchors.top: parent.top; width: parent.width; height: 10
        emitRate: 30; lifeSpan: 9000; size: 14 * fe.u; sizeVariation: 6 * fe.u
        velocity: AngleDirection { angle: 90; angleVariation: 20; magnitude: 110 * fe.u; magnitudeVariation: 40 * fe.u }
    }
    Wander { system: ps; groups: ["snow", "confetti"]; xVariance: 40 * fe.u; pace: 60 * fe.u }

    Rectangle {
        visible: fe.greeting !== ""
        anchors.horizontalCenter: parent.horizontalCenter; y: 18 * fe.u
        width: g.width + 56 * fe.u; height: 54 * fe.u; radius: height / 2
        color: Qt.rgba(0.04, 0.05, 0.08, 0.62); border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.14)
        Text {
            id: g; anchors.centerIn: parent; text: fe.greeting; color: fe.textColor
            font.family: "EB Garamond"; font.italic: true; font.pixelSize: 30 * fe.u
        }
    }
}
