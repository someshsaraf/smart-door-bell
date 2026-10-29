import QtQuick
import QtQuick.Effects
import "util.js" as U

// Fluent: like a Windows 11 app. Mica (the picture blurred to a tinted haze) behind a
// navigation pane with an accent Front door button, and content laid out as cards:
// the story, the front door, recent activity and the market.
Item {
    id: fx
    readonly property real u: Math.min(width / 1768, height / 828)
    readonly property string sans: "Inter Variable"
    readonly property bool news: home.view !== "photos"
    readonly property color text1: "#ffffff"
    readonly property color text2: "#c8c8c8"
    readonly property color text3: "#9d9d9d"
    readonly property color accent: "#60cdff"
    readonly property color accentInk: "#00141f"
    readonly property color cardBg: Qt.rgba(1, 1, 1, 0.055)
    readonly property color cardStroke: Qt.rgba(1, 1, 1, 0.075)
    readonly property real paneW: 304 * u
    readonly property real cx: paneW + 40 * u               // content left
    readonly property real cw: width - cx - 40 * u          // content width
    readonly property real heroW: cw - 508 * u - 20 * u

    Clock { id: clk }
    Rotator { id: rot; count: home.news.length; running: fx.news && fx.visible }
    property var story: home.news.length ? home.news[Math.min(rot.index, home.news.length - 1)] : null
    property var cur: null
    onStoryChanged: swap.restart()
    SequentialAnimation {
        id: swap
        NumberAnimation { target: heroBody; property: "opacity"; to: 0; duration: 150 }
        ScriptAction { script: fx.cur = fx.story }
        ParallelAnimation {
            NumberAnimation { target: heroBody; property: "opacity"; to: 1; duration: 420; easing.type: Easing.OutCubic }
            NumberAnimation { target: heroBody; property: "y"; from: 14 * fx.u; to: 0; duration: 520; easing.type: Easing.OutCubic }
        }
    }

    // ---------- Mica ----------
    Item {
        id: wall; anchors.fill: parent; visible: false
        Image {
            anchors.fill: parent; fillMode: Image.PreserveAspectCrop; sourceSize.width: 480; asynchronous: true
            source: fx.news ? (fx.cur && fx.cur.image ? fx.cur.image : "") : (home.photos.length ? home.photos[show.index % home.photos.length].url : "")
        }
    }
    Rectangle { anchors.fill: parent; color: "#202020" }
    MultiEffect { anchors.fill: parent; source: wall; blurEnabled: true; blur: 1; blurMax: 64; saturation: 0.6; opacity: 0.55 }
    Rectangle { anchors.fill: parent; color: "#202020"; opacity: 0.72 }

    component Card: Rectangle {
        radius: 8 * fx.u; color: fx.cardBg; border.width: 1; border.color: fx.cardStroke; antialiasing: true
    }
    component SubtleButton: Rectangle {
        id: sb
        property string icon
        signal tapped
        width: 40 * fx.u; height: 36 * fx.u; radius: 5 * fx.u
        color: sbMa.pressed ? Qt.rgba(1, 1, 1, 0.04) : Qt.rgba(1, 1, 1, 0.06); border.width: 1; border.color: fx.cardStroke
        Icon { anchors.centerIn: parent; name: sb.icon; color: fx.text1; size: 18 * fx.u }
        MouseArea { id: sbMa; anchors.fill: parent; onClicked: sb.tapped() }
    }

    // ---------- navigation pane ----------
    Rectangle { width: fx.paneW; height: parent.height; color: Qt.rgba(0.17, 0.17, 0.17, 0.55) }
    Rectangle { x: fx.paneW; width: 1; height: parent.height; color: Qt.rgba(1, 1, 1, 0.06) }
    Row {
        x: 22 * fx.u; y: 24 * fx.u; spacing: 12 * fx.u
        Rectangle {
            width: 30 * fx.u; height: width; radius: 7 * fx.u; color: fx.accent
            Icon { anchors.centerIn: parent; name: "door"; color: fx.accentInk; size: 19 * fx.u; stroke: 2 }
        }
        Text { text: "Doorbell"; color: fx.text1; font.family: fx.sans; font.pixelSize: 15 * fx.u; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
    }
    // the accent button: the front door
    Rectangle {
        x: 16 * fx.u; y: 78 * fx.u; width: fx.paneW - 32 * fx.u; height: 72 * fx.u; radius: 7 * fx.u
        color: doorMa.pressed ? Qt.darker(fx.accent, 1.12) : fx.accent
        border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.2)
        Icon { id: dIcon; x: 18 * fx.u; anchors.verticalCenter: parent.verticalCenter; name: "camera"; color: fx.accentInk; size: 28 * fx.u; stroke: 1.9 }
        Column {
            anchors.left: dIcon.right; anchors.leftMargin: 14 * fx.u; anchors.verticalCenter: parent.verticalCenter; spacing: 1 * fx.u
            Text { text: "Front door"; color: fx.accentInk; font.family: fx.sans; font.pixelSize: 20 * fx.u; font.weight: Font.DemiBold }
            Text { text: "Open the live view"; color: fx.accentInk; opacity: 0.72; font.family: fx.sans; font.pixelSize: 13 * fx.u; font.weight: Font.Medium }
        }
        MouseArea { id: doorMa; anchors.fill: parent; onClicked: home.openDoor() }
    }
    component NavItem: Item {
        id: ni
        property string icon
        property string label
        property bool selected: false
        property string badge: ""
        signal tapped
        x: 8 * fx.u; width: fx.paneW - 16 * fx.u; height: 46 * fx.u
        Rectangle {
            anchors.fill: parent; radius: 5 * fx.u
            color: niMa.pressed ? Qt.rgba(1, 1, 1, 0.04) : ni.selected ? Qt.rgba(1, 1, 1, 0.07) : "transparent"
        }
        Rectangle {
            visible: ni.selected; x: 0; anchors.verticalCenter: parent.verticalCenter
            width: 3 * fx.u; height: 18 * fx.u; radius: 1.5 * fx.u; color: fx.accent
        }
        Icon { x: 16 * fx.u; anchors.verticalCenter: parent.verticalCenter; name: ni.icon; color: fx.text1; size: 22 * fx.u }
        Text {
            x: 54 * fx.u; anchors.verticalCenter: parent.verticalCenter; text: ni.label; color: fx.text1
            font.family: fx.sans; font.pixelSize: 16 * fx.u; font.weight: ni.selected ? Font.DemiBold : Font.Normal
        }
        Rectangle {
            visible: ni.badge !== ""; anchors.right: parent.right; anchors.rightMargin: 14 * fx.u; anchors.verticalCenter: parent.verticalCenter
            width: Math.max(height, bdg.width + 12 * fx.u); height: 20 * fx.u; radius: height / 2; color: fx.accent
            Text { id: bdg; anchors.centerIn: parent; text: ni.badge; color: fx.accentInk; font.family: fx.sans; font.pixelSize: 12 * fx.u; font.weight: Font.Bold }
        }
        MouseArea { id: niMa; anchors.fill: parent; onClicked: ni.tapped() }
    }
    Column {
        y: 172 * fx.u; spacing: 4 * fx.u
        NavItem { icon: "news"; label: "News"; selected: fx.news; onTapped: home.setView("news") }
        NavItem { icon: "photo"; label: "Photos"; selected: !fx.news; onTapped: home.setView("photos") }
        NavItem { icon: "bell"; label: "Events"; badge: home.visits.today ? String(home.visits.today) : ""; onTapped: home.openEvents() }
    }
    // voice, and settings at the foot of the pane
    Item {
        x: 8 * fx.u; y: parent.height - 150 * fx.u; width: fx.paneW - 16 * fx.u; height: 74 * fx.u
        Rectangle { anchors.fill: parent; radius: 6 * fx.u; color: askMa.pressed ? Qt.rgba(1, 1, 1, 0.08) : Qt.rgba(1, 1, 1, 0.04); border.width: 1; border.color: fx.cardStroke }
        Orb { id: orb; x: 12 * fx.u; anchors.verticalCenter: parent.verticalCenter; size: 50 * fx.u; mode: home.micState }
        Column {
            anchors.left: orb.right; anchors.leftMargin: 14 * fx.u; anchors.verticalCenter: parent.verticalCenter
            Text {
                text: home.micState === "listening" ? "Listening…" : home.micState === "thinking" ? "Thinking…" : "Ask the doorbell"
                color: fx.text1; font.family: fx.sans; font.pixelSize: 16 * fx.u; font.weight: Font.DemiBold
            }
            Text { text: "“Stop the bell”, “Show events”"; color: fx.text3; font.family: fx.sans; font.pixelSize: 12 * fx.u }
        }
        MouseArea { id: askMa; anchors.fill: parent; onClicked: home.listen() }
    }
    NavItem { y: parent.height - 64 * fx.u; icon: "settings"; label: "Settings"; onTapped: home.openSettings() }

    // ---------- header ----------
    Column {
        x: fx.cx; y: 30 * fx.u; spacing: 4 * fx.u
        Text { text: U.greeting(clk.now); color: fx.text1; font.family: fx.sans; font.pixelSize: 40 * fx.u; font.weight: Font.DemiBold }
        Text { text: U.longDate(clk.now); color: fx.text2; font.family: fx.sans; font.pixelSize: 17 * fx.u }
    }
    Row {
        anchors.right: parent.right; anchors.rightMargin: 40 * fx.u; y: 22 * fx.u; spacing: 8 * fx.u
        Text { id: tm; text: U.clock(clk.now); color: fx.text1; font.family: fx.sans; font.pixelSize: 72 * fx.u; font.weight: 300; font.features: { "tnum": 1 } }
        Text { text: U.ampm(clk.now).toUpperCase(); color: fx.text2; font.family: fx.sans; font.pixelSize: 20 * fx.u; font.weight: Font.DemiBold; anchors.baseline: tm.baseline }
    }

    // ---------- the info bar: breaking headlines, one at a time ----------
    Rectangle {
        id: info
        x: fx.cx; y: 132 * fx.u; width: fx.cw; height: 52 * fx.u; radius: 6 * fx.u
        readonly property bool hot: home.breaking.length > 0 && home.breaking[0].breaking
        color: hot ? Qt.rgba(0.27, 0.15, 0.15, 0.85) : fx.cardBg; border.width: 1; border.color: hot ? Qt.rgba(1, 0.6, 0.64, 0.25) : fx.cardStroke
        property int i: 0
        Timer { interval: 7000; running: home.breaking.length > 1 && fx.visible; repeat: true; onTriggered: { infoText.opacity = 0; flip.restart() } }
        Timer { id: flip; interval: 220; onTriggered: { info.i = (info.i + 1) % Math.max(1, Math.min(8, home.breaking.length)); infoText.opacity = 1 } }
        Rectangle {
            x: 16 * fx.u; anchors.verticalCenter: parent.verticalCenter; width: 22 * fx.u; height: width; radius: width / 2
            color: info.hot ? "#ff99a4" : fx.accent
            Text { anchors.centerIn: parent; text: info.hot ? "!" : "i"; color: "#1c1c1c"; font.family: fx.sans; font.pixelSize: 14 * fx.u; font.weight: Font.Black }
        }
        Text {
            id: infoLabel; x: 52 * fx.u; anchors.verticalCenter: parent.verticalCenter
            text: info.hot ? "Breaking" : "Latest"; color: fx.text1; font.family: fx.sans; font.pixelSize: 15 * fx.u; font.weight: Font.DemiBold
        }
        Text {
            id: infoText; anchors.left: infoLabel.right; anchors.leftMargin: 14 * fx.u; anchors.right: parent.right; anchors.rightMargin: 18 * fx.u
            anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight
            readonly property var it: home.breaking.length ? home.breaking[info.i % home.breaking.length] : null
            text: it ? it.source + "  ·  " + it.title : "No headlines yet"
            color: fx.text2; font.family: fx.sans; font.pixelSize: 15 * fx.u
            Behavior on opacity { NumberAnimation { duration: 200 } }
        }
    }

    // ---------- the story, or the photographs ----------
    Card {
        id: hero
        x: fx.cx; y: 204 * fx.u; width: fx.heroW; height: parent.height - y - 128 * fx.u; clip: true
        Item {
            id: heroBody; width: parent.width; height: parent.height; visible: fx.news
            Item {
                id: hp; x: 8 * fx.u; y: 8 * fx.u; width: 420 * fx.u; height: parent.height - 16 * fx.u
                Rectangle {
                    anchors.fill: parent; radius: 5 * fx.u
                    gradient: Gradient {
                        GradientStop { position: 0; color: fx.cur ? Qt.darker(fx.cur.color, 1.3) : "#333" }
                        GradientStop { position: 1; color: fx.cur ? Qt.darker(fx.cur.color, 2.8) : "#111" }
                    }
                    Text { anchors.centerIn: parent; text: fx.cur ? fx.cur.source : ""; color: Qt.rgba(1, 1, 1, 0.9); font.family: fx.sans; font.pixelSize: 40 * fx.u; font.weight: Font.Black }
                }
                Rounded { anchors.fill: parent; radius: 5 * fx.u; source: fx.cur ? fx.cur.image : "" }
            }
            Column {
                x: hp.x + hp.width + 28 * fx.u; y: 28 * fx.u; width: parent.width - x - 28 * fx.u; spacing: 12 * fx.u
                Text {
                    text: fx.cur ? [fx.cur.source, fx.cur.region, U.ago(fx.cur.time)].filter(function (t) { return t }).join("  ·  ") : ""
                    color: fx.text3; font.family: fx.sans; font.pixelSize: 14 * fx.u; font.weight: Font.Medium
                }
                Text {
                    width: parent.width; text: fx.cur ? fx.cur.title : ""; color: fx.text1
                    wrapMode: Text.WordWrap; maximumLineCount: 5; elide: Text.ElideRight; lineHeight: 1.12
                    font.family: fx.sans; font.pixelSize: (text.length < 80 ? 31 : 27) * fx.u; font.weight: Font.DemiBold
                }
                Text {
                    width: parent.width; text: fx.cur && fx.cur.summary !== fx.cur.title ? fx.cur.summary : ""; color: fx.text2
                    wrapMode: Text.WordWrap; maximumLineCount: 4; elide: Text.ElideRight; lineHeight: 1.3
                    font.family: fx.sans; font.pixelSize: 16 * fx.u
                }
            }
            Row {
                x: hp.x + hp.width + 28 * fx.u; y: parent.height - 60 * fx.u; spacing: 8 * fx.u
                SubtleButton { icon: "left"; onTapped: rot.go(-1) }
                SubtleButton { icon: "right"; onTapped: rot.go(1) }
                Text {
                    anchors.verticalCenter: parent.verticalCenter; leftPadding: 8 * fx.u
                    text: home.news.length ? (rot.index + 1) + " of " + home.news.length : ""; color: fx.text3
                    font.family: fx.sans; font.pixelSize: 14 * fx.u; font.features: { "tnum": 1 }
                }
            }
            Rectangle {  // progress to the next story, along the card's foot
                anchors.bottom: parent.bottom; x: hp.x + hp.width; height: 2 * fx.u; width: (parent.width - x) * rot.progress; color: fx.accent; opacity: 0.8
            }
            MouseArea {
                width: parent.width; height: parent.height - 76 * fx.u; property real px: 0
                onPressed: (e) => px = e.x
                onReleased: (e) => { if (Math.abs(e.x - px) > 80 * fx.u) rot.go(e.x < px ? 1 : -1) }
            }
        }
        Item {
            anchors.fill: parent; anchors.margins: 8 * fx.u; visible: !fx.news
            Item {
                anchors.fill: parent; layer.enabled: true
                layer.effect: MultiEffect { maskEnabled: true; maskSource: heroMask; maskThresholdMin: 0.5; maskSpreadAtMin: 1.0 }
                PhotoShow { id: show; anchors.fill: parent; photos: home.photos; visible: !fx.news }
            }
            Item { id: heroMask; anchors.fill: parent; visible: false; layer.enabled: true; Rectangle { anchors.fill: parent; radius: 5 * fx.u; color: "black" } }
            Rectangle {
                anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: 14 * fx.u
                width: credit.width + 24 * fx.u; height: 32 * fx.u; radius: 5 * fx.u; color: Qt.rgba(0.12, 0.12, 0.12, 0.75); visible: show.credit !== ""
                Text { id: credit; anchors.centerIn: parent; text: "Photo · " + show.credit; color: fx.text1; font.family: fx.sans; font.pixelSize: 13 * fx.u }
            }
        }
    }

    // ---------- market ----------
    Row {
        x: fx.cx; y: hero.y + hero.height + 20 * fx.u; spacing: 12 * fx.u
        Repeater {
            model: home.market && home.market.indices ? home.market.indices : []
            Card {
                width: 250 * fx.u; height: 68 * fx.u
                Column {
                    x: 18 * fx.u; anchors.verticalCenter: parent.verticalCenter; spacing: 2 * fx.u
                    Text { text: modelData.name; color: fx.text3; font.family: fx.sans; font.pixelSize: 13 * fx.u; font.weight: Font.Medium }
                    Row {
                        spacing: 10 * fx.u
                        Text { text: U.num(modelData.ltp); color: fx.text1; font.family: fx.sans; font.pixelSize: 20 * fx.u; font.weight: Font.DemiBold; font.features: { "tnum": 1 } }
                        Text {
                            anchors.baseline: parent.children[0].baseline
                            text: (modelData.pct >= 0 ? "▲ " : "▼ ") + Math.abs(modelData.pct).toFixed(2) + "%"
                            color: modelData.pct >= 0 ? "#6ccb5f" : "#ff99a4"; font.family: fx.sans; font.pixelSize: 14 * fx.u; font.weight: Font.DemiBold
                        }
                    }
                }
            }
        }
        Card {
            width: fx.heroW - (home.market && home.market.indices ? home.market.indices.length : 0) * 262 * fx.u; height: 68 * fx.u
            MarketLine {
                x: 18 * fx.u; height: parent.height; width: parent.width - 36 * fx.u; clip: true
                market: home.market && home.market.indices ? { indices: [], gainers: home.market.gainers, losers: home.market.losers, session: home.market.session, open: home.market.open } : ({})
                note: home.marketNote; pixelSize: 15 * fx.u
                color: fx.text1; muted: fx.text3; up: "#6ccb5f"; down: "#ff99a4"
            }
        }
    }

    // ---------- the front door and recent activity ----------
    Card {
        id: doorCard
        x: fx.cx + fx.heroW + 20 * fx.u; y: 204 * fx.u; width: 508 * fx.u; height: 300 * fx.u
        Item {
            x: 8 * fx.u; y: 8 * fx.u; width: parent.width - 16 * fx.u; height: 210 * fx.u
            Rectangle { anchors.fill: parent; radius: 5 * fx.u; color: Qt.rgba(0, 0, 0, 0.3)
                Icon { anchors.centerIn: parent; name: "door"; color: fx.text3; size: 64 * fx.u; stroke: 1.2 } }
            Rounded { anchors.fill: parent; radius: 5 * fx.u; source: home.doorStill; sourceWidth: 800 }
            Rectangle {
                x: 10 * fx.u; y: 10 * fx.u; height: 26 * fx.u; width: lv.width + 30 * fx.u; radius: 4 * fx.u; color: Qt.rgba(0.12, 0.12, 0.12, 0.8)
                Rectangle { id: lvDot; x: 10 * fx.u; anchors.verticalCenter: parent.verticalCenter; width: 8 * fx.u; height: width; radius: width / 2
                    color: home.doorOnline === 1 ? "#6ccb5f" : home.doorOnline === 0 ? "#ff99a4" : fx.text3 }
                Text { id: lv; anchors.left: lvDot.right; anchors.leftMargin: 6 * fx.u; anchors.verticalCenter: parent.verticalCenter
                    text: home.doorOnline === 1 ? "Online" : home.doorOnline === 0 ? "Offline" : "Waiting"; color: fx.text1; font.family: fx.sans; font.pixelSize: 12 * fx.u; font.weight: Font.DemiBold }
            }
        }
        Column {
            x: 20 * fx.u; y: 230 * fx.u; spacing: 2 * fx.u
            Text { text: "Front door"; color: fx.text1; font.family: fx.sans; font.pixelSize: 18 * fx.u; font.weight: Font.DemiBold }
            Text {
                text: home.doorStillTime ? "Picture from " + U.ago(home.doorStillTime) : "Camera picture"
                color: fx.text3; font.family: fx.sans; font.pixelSize: 13 * fx.u
            }
        }
        Rectangle {
            anchors.right: parent.right; anchors.rightMargin: 16 * fx.u; y: 236 * fx.u; width: 120 * fx.u; height: 40 * fx.u; radius: 5 * fx.u
            color: openMa.pressed ? Qt.darker(fx.accent, 1.12) : fx.accent
            Text { anchors.centerIn: parent; text: "Open"; color: fx.accentInk; font.family: fx.sans; font.pixelSize: 15 * fx.u; font.weight: Font.DemiBold }
            MouseArea { id: openMa; anchors.fill: parent; onClicked: home.openDoor() }
        }
        MouseArea { width: parent.width; height: 220 * fx.u; onClicked: home.openDoor() }
    }
    Card {
        x: doorCard.x; y: doorCard.y + doorCard.height + 20 * fx.u; width: 508 * fx.u; height: hero.y + hero.height + 88 * fx.u - y
        Text { x: 20 * fx.u; y: 18 * fx.u; text: "Recent activity"; color: fx.text1; font.family: fx.sans; font.pixelSize: 17 * fx.u; font.weight: Font.DemiBold }
        Text {
            anchors.right: parent.right; anchors.rightMargin: 20 * fx.u; y: 20 * fx.u
            text: home.visits.today ? home.visits.today + " rings today" : ""; color: fx.accent; font.family: fx.sans; font.pixelSize: 14 * fx.u; font.weight: Font.DemiBold
        }
        Column {
            x: 20 * fx.u; y: 56 * fx.u; width: parent.width - 40 * fx.u; spacing: 0
            Repeater {
                model: home.events.slice(0, 4)
                Item {
                    width: parent.width; height: 40 * fx.u
                    readonly property var parts: modelData.replace(/^•\s*/, "").match(/^(\d\d:\d\d)\s+(.*)$/) || ["", "", modelData]
                    Rectangle { width: parent.width; height: 1; color: fx.cardStroke; visible: index > 0 }
                    Icon {
                        anchors.verticalCenter: parent.verticalCenter; size: 18 * fx.u; color: fx.text2
                        name: /offline|online/i.test(parent.parts[2]) ? "wifi" : /talk|call/i.test(parent.parts[2]) ? "mic" : "bell"
                    }
                    Text {
                        x: 32 * fx.u; anchors.verticalCenter: parent.verticalCenter; width: parent.width - x - 60 * fx.u; elide: Text.ElideRight
                        text: parent.parts[2]; color: fx.text1; font.family: fx.sans; font.pixelSize: 15 * fx.u
                    }
                    Text {
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                        text: parent.parts[1]; color: fx.text3; font.family: fx.sans; font.pixelSize: 14 * fx.u; font.features: { "tnum": 1 }
                    }
                }
            }
            Text { visible: home.events.length === 0; text: "Nothing yet today"; color: fx.text3; font.family: fx.sans; font.pixelSize: 15 * fx.u; topPadding: 8 * fx.u }
        }
    }
}
