import QtQuick
import "util.js" as U

// The market in one line: indices, top movers, open or closed.
Row {
    id: m
    property var market: ({})
    property string note: ""
    property color color: "white"
    property color muted: "#999999"
    property color up: "#2fbf71"
    property color down: "#ef5350"
    property real pixelSize: 16
    property bool movers: true
    spacing: pixelSize * 1.6
    readonly property var d: market && market.indices ? market : null

    Text {
        visible: !m.d; text: m.note || "Markets loading…"; color: m.muted
        font.family: "Inter Variable"; font.pixelSize: m.pixelSize; anchors.verticalCenter: parent.verticalCenter
    }
    Repeater {
        model: m.d ? m.d.indices : []
        Row {
            spacing: m.pixelSize * 0.5; anchors.verticalCenter: parent.verticalCenter
            Text {
                text: modelData.name.toUpperCase(); color: m.muted; anchors.verticalCenter: parent.verticalCenter
                font.family: "Inter Variable"; font.pixelSize: m.pixelSize * 0.78; font.weight: Font.DemiBold; font.letterSpacing: m.pixelSize * 0.06
            }
            Text {
                text: U.num(modelData.ltp); color: m.color; anchors.verticalCenter: parent.verticalCenter
                font.family: "Inter Variable"; font.pixelSize: m.pixelSize; font.weight: Font.DemiBold; font.features: { "tnum": 1 }
            }
            Text {
                text: (modelData.pct >= 0 ? "▲ " : "▼ ") + Math.abs(modelData.pct).toFixed(2) + "%"
                color: modelData.pct >= 0 ? m.up : m.down; anchors.verticalCenter: parent.verticalCenter
                font.family: "Inter Variable"; font.pixelSize: m.pixelSize * 0.88; font.weight: Font.DemiBold; font.features: { "tnum": 1 }
            }
        }
    }
    Repeater {
        model: m.d && m.movers ? [["UP", m.d.gainers.slice(0, 2), m.up], ["DOWN", m.d.losers.slice(0, 2), m.down]] : []
        Row {
            spacing: m.pixelSize * 0.5; anchors.verticalCenter: parent.verticalCenter
            visible: modelData[1].length > 0
            Text {
                text: modelData[0]; color: modelData[2]; anchors.verticalCenter: parent.verticalCenter
                font.family: "Inter Variable"; font.pixelSize: m.pixelSize * 0.78; font.weight: Font.Bold; font.letterSpacing: m.pixelSize * 0.06
            }
            Repeater {
                model: modelData[1]
                Text {
                    text: modelData.symbol + " " + U.pct(modelData.pct); color: m.color; opacity: 0.85
                    anchors.verticalCenter: parent.verticalCenter
                    font.family: "Inter Variable"; font.pixelSize: m.pixelSize * 0.88; font.features: { "tnum": 1 }
                }
            }
        }
    }
    Text {
        visible: !!m.d; text: m.d ? (m.d.open ? "LIVE" : "CLOSED · " + m.d.session.toUpperCase()) : ""
        color: m.d && m.d.open ? m.up : m.muted; anchors.verticalCenter: parent.verticalCenter
        font.family: "Inter Variable"; font.pixelSize: m.pixelSize * 0.74; font.weight: Font.Bold; font.letterSpacing: m.pixelSize * 0.08
    }
}
