import QtQuick
import QtQuick.Effects
import QtQuick.Shapes
import "util.js" as U

// Editorial: a cover. The story's photo fills most of the screen and drifts slowly, its headline
// set large on it; a quiet panel on the left holds the clock, the front door (the one bright
// element, with the camera's latest picture) and three plain tiles. "paper" is the light version.
Item {
    id: ed
    readonly property bool paper: home.look === "paper"
    readonly property real u: Math.min(width / 1768, height / 828)
    property color bg: paper ? "#f4f3ef" : "#0a0a0b"
    property color panel: paper ? "#ffffff" : "#161618"
    property color stroke: paper ? Qt.rgba(0, 0, 0, 0.08) : Qt.rgba(1, 1, 1, 0.08)
    property color ink: paper ? "#111111" : "#f5f5f7"
    property color muted: paper ? "#6e6e73" : "#8e8e93"
    property color hero: paper ? "#111111" : "#ffffff"        // the front door's button
    property color heroInk: paper ? "#ffffff" : "#0a0a0b"
    Behavior on bg { ColorAnimation { duration: 500 } }
    Behavior on panel { ColorAnimation { duration: 500 } }
    Behavior on ink { ColorAnimation { duration: 500 } }
    Behavior on hero { ColorAnimation { duration: 500 } }
    readonly property string sans: "Inter Variable"
    readonly property real m: 48 * u
    readonly property real leftW: 560 * u
    readonly property real bandY: height - 72 * u
    readonly property bool news: home.view !== "photos"

    Clock { id: clk }
    Rotator { id: rot; count: home.news.length; running: ed.news && ed.visible }
    property var story: home.news.length ? home.news[Math.min(rot.index, home.news.length - 1)] : null
    property var cur: null
    onStoryChanged: swap.restart()
    SequentialAnimation {
        id: swap
        NumberAnimation { target: headline; property: "opacity"; to: 0; duration: 220 }
        ScriptAction { script: { ed.cur = ed.story; cover.show(ed.cur ? ed.cur.image : "") } }
        ParallelAnimation {
            NumberAnimation { target: headline; property: "opacity"; to: 1; duration: 700; easing.type: Easing.OutCubic }
            NumberAnimation { target: headline; property: "lift"; from: 30 * ed.u; to: 0; duration: 800; easing.type: Easing.OutCubic }
        }
    }

    Rectangle { anchors.fill: parent; color: ed.bg }

    // ---------- the cover: the story's photo, or the slideshow ----------
    Item {
        id: stage
        x: ed.leftW; width: parent.width - x; height: ed.bandY; clip: true

        // a story without a photo: a soft glow in its channel's colour
        Rectangle { anchors.fill: parent; color: ed.paper ? "#1c1c1e" : ed.bg }  // dark: no seam with the panel
        Shape {
            anchors.fill: parent; opacity: ed.news ? 1 : 0
            ShapePath {
                strokeWidth: 0; strokeColor: "transparent"
                fillGradient: RadialGradient {
                    centerX: stage.width * 0.72; centerY: stage.height * 0.3; centerRadius: stage.width * 0.7
                    focalX: centerX; focalY: centerY
                    GradientStop { position: 0; color: ed.cur ? Qt.rgba(Qt.color(ed.cur.color).r, Qt.color(ed.cur.color).g, Qt.color(ed.cur.color).b, 0.55) : "transparent" }
                    GradientStop { position: 1; color: "transparent" }
                }
                PathRectangle { width: stage.width; height: stage.height }
            }
        }
        Text {
            anchors.right: parent.right; anchors.rightMargin: 60 * ed.u; y: 80 * ed.u; visible: ed.news
            text: ed.cur && !ed.cur.image ? ed.cur.source : ""; color: "white"; opacity: 0.09
            font.family: ed.sans; font.pixelSize: 190 * ed.u; font.weight: Font.Black; font.letterSpacing: -6 * ed.u
        }
        Item {
            id: cover; anchors.fill: parent; visible: ed.news
            property bool flip: false
            function show(url) {
                var next = flip ? a : b
                next.source = url; flip = !flip
                if (!url) { a.shown = false; b.shown = false }
            }
            component Layer: Image {
                id: img
                property bool shown: false
                anchors.fill: parent; fillMode: Image.PreserveAspectCrop; asynchronous: true; cache: false
                sourceSize.width: 1600
                opacity: shown ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 1100; easing.type: Easing.InOutQuad } }
                onStatusChanged: if (status === Image.Ready && source != "") {
                    shown = true; (img === a ? b : a).shown = false
                    drift.restart()
                }
                NumberAnimation { id: drift; target: img; property: "scale"; from: 1.0; to: 1.08; duration: rot.interval + 3000 }
            }
            Layer { id: a }
            Layer { id: b }
        }
        PhotoShow { id: show; anchors.fill: parent; visible: !ed.news; photos: home.photos }

        // shades: into the panel on the left, and under the headline
        Rectangle {
            width: 300 * ed.u; height: parent.height
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0; color: ed.bg } GradientStop { position: 1; color: "transparent" } }
        }
        Rectangle {
            anchors.bottom: parent.bottom; width: parent.width; height: parent.height * 0.62
            gradient: Gradient {
                GradientStop { position: 0; color: "transparent" }
                GradientStop { position: 0.55; color: Qt.rgba(0, 0, 0, 0.45) }
                GradientStop { position: 1; color: Qt.rgba(0, 0, 0, 0.82) }
            }
        }
        Rectangle {
            width: parent.width; height: 120 * ed.u
            gradient: Gradient { GradientStop { position: 0; color: Qt.rgba(0, 0, 0, 0.45) } GradientStop { position: 1; color: "transparent" } }
        }

        // like a story: a line that fills until the next one, and where we are
        Row {
            x: 80 * ed.u; y: 30 * ed.u; spacing: 16 * ed.u; visible: ed.news && home.news.length > 1
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: stage.width - 80 * ed.u - 48 * ed.u - count.width - 16 * ed.u; height: 3 * ed.u; radius: height / 2
                color: Qt.rgba(1, 1, 1, 0.25)
                Rectangle { width: parent.width * rot.progress; height: parent.height; radius: parent.radius; color: "white" }
            }
            Text {
                id: count; anchors.verticalCenter: parent.verticalCenter
                text: (rot.index + 1) + " / " + home.news.length; color: Qt.rgba(1, 1, 1, 0.85)
                font.family: ed.sans; font.pixelSize: 15 * ed.u; font.weight: Font.DemiBold; font.features: { "tnum": 1 }
            }
        }

        // the headline, set on the photo
        Column {
            id: headline
            property real lift: 0
            x: 80 * ed.u; width: stage.width - x - 200 * ed.u
            anchors.bottom: parent.bottom; anchors.bottomMargin: 50 * ed.u - lift
            spacing: 16 * ed.u; visible: ed.news && ed.cur !== null
            Row {
                spacing: 12 * ed.u
                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    height: 30 * ed.u; width: src.width + 34 * ed.u; radius: height / 2; color: Qt.rgba(1, 1, 1, 0.16)
                    border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.22)
                    Rectangle { x: 12 * ed.u; anchors.verticalCenter: parent.verticalCenter; width: 8 * ed.u; height: width; radius: width / 2; color: ed.cur ? ed.cur.color : "white" }
                    Text {
                        id: src; x: 26 * ed.u; anchors.verticalCenter: parent.verticalCenter
                        text: ed.cur ? ed.cur.source : ""; color: "white"
                        font.family: ed.sans; font.pixelSize: 14 * ed.u; font.weight: Font.DemiBold
                    }
                }
                Rectangle {
                    visible: !!(ed.cur && ed.cur.breaking); anchors.verticalCenter: parent.verticalCenter
                    height: 30 * ed.u; width: brk.width + 26 * ed.u; radius: height / 2; color: "#ff3b30"
                    Text { id: brk; anchors.centerIn: parent; text: "Breaking"; color: "white"; font.family: ed.sans; font.pixelSize: 14 * ed.u; font.weight: Font.Bold }
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: ed.cur ? U.ago(ed.cur.time) : ""; color: Qt.rgba(1, 1, 1, 0.75)
                    font.family: ed.sans; font.pixelSize: 15 * ed.u; font.weight: Font.Medium
                }
            }
            Text {
                width: parent.width; text: ed.cur ? ed.cur.title : ""; color: "white"
                wrapMode: Text.WordWrap; maximumLineCount: 3; elide: Text.ElideRight; lineHeight: 1.04
                font.family: ed.sans; font.weight: Font.DemiBold; font.letterSpacing: -0.8 * ed.u
                font.pixelSize: (text.length < 60 ? 56 : text.length < 95 ? 48 : 42) * ed.u
            }
            Text {
                width: parent.width * 0.86; text: ed.cur && ed.cur.summary !== ed.cur.title ? ed.cur.summary : ""; color: Qt.rgba(1, 1, 1, 0.78)
                wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight; lineHeight: 1.3
                font.family: ed.sans; font.pixelSize: 19 * ed.u
                visible: text !== ""
            }
        }
        Row {
            anchors.right: parent.right; anchors.rightMargin: 48 * ed.u; anchors.bottom: parent.bottom; anchors.bottomMargin: 54 * ed.u
            spacing: 12 * ed.u; visible: ed.news && home.news.length > 1
            Repeater {
                model: [-1, 1]
                Rectangle {
                    width: 56 * ed.u; height: width; radius: width / 2
                    color: navMa.pressed ? Qt.rgba(1, 1, 1, 0.3) : Qt.rgba(1, 1, 1, 0.14); border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.25)
                    Icon { anchors.centerIn: parent; name: modelData < 0 ? "left" : "right"; color: "white"; size: 24 * ed.u; stroke: 2 }
                    MouseArea { id: navMa; anchors.fill: parent; onClicked: rot.go(modelData) }
                }
            }
        }
        Text {
            x: 80 * ed.u; anchors.bottom: parent.bottom; anchors.bottomMargin: 40 * ed.u; visible: !ed.news && show.credit !== ""
            text: "Photograph by " + show.credit; color: Qt.rgba(1, 1, 1, 0.85); font.family: ed.sans; font.pixelSize: 15 * ed.u; font.weight: Font.Medium
        }
        Text {
            x: 80 * ed.u; y: parent.height * 0.42; width: parent.width - 160 * ed.u; visible: ed.news && home.news.length === 0
            text: home.newsNote || "The news is on its way…"; color: Qt.rgba(1, 1, 1, 0.7); wrapMode: Text.WordWrap
            font.family: ed.sans; font.pixelSize: 30 * ed.u; font.weight: Font.Light
        }
        MouseArea {
            anchors.fill: parent; z: -1; property real px: 0
            onPressed: (e) => px = e.x
            onReleased: (e) => {
                if (Math.abs(e.x - px) < 80 * ed.u) return
                if (ed.news) rot.go(e.x < px ? 1 : -1)
                else show.go(e.x < px ? 1 : -1)
            }
        }
    }

    // ---------- the panel ----------
    Text {
        x: ed.m; y: 46 * ed.u; text: U.longDate(clk.now).toUpperCase(); color: ed.muted
        font.family: ed.sans; font.pixelSize: 13 * ed.u; font.weight: Font.DemiBold; font.letterSpacing: 2.4 * ed.u
    }
    Row {
        x: ed.m - 8 * ed.u; y: 58 * ed.u; spacing: 10 * ed.u
        Text {
            id: bigTime; text: U.clock(clk.now); color: ed.ink
            font.family: ed.sans; font.pixelSize: 158 * ed.u; font.weight: 200; font.letterSpacing: -6 * ed.u; font.features: { "tnum": 1 }
        }
        Text {
            text: U.ampm(clk.now).toUpperCase(); color: ed.muted; anchors.baseline: bigTime.baseline
            font.family: ed.sans; font.pixelSize: 22 * ed.u; font.weight: Font.DemiBold; font.letterSpacing: 1 * ed.u
        }
    }

    // the front door: the camera's latest picture and the one bright button
    Rectangle {
        id: door
        x: ed.m; y: 272 * ed.u; width: ed.leftW - 2 * ed.m; height: 132 * ed.u; radius: 32 * ed.u
        color: ed.panel; border.width: 1; border.color: ed.stroke
        scale: doorMa.pressed ? 0.98 : 1
        Behavior on scale { NumberAnimation { duration: 130 } }
        layer.enabled: true
        layer.effect: MultiEffect { shadowEnabled: true; shadowBlur: 1.0; shadowOpacity: ed.paper ? 0.10 : 0.45; shadowVerticalOffset: 12 * ed.u; shadowColor: "black" }
        Item {
            id: thumb; x: 20 * ed.u; anchors.verticalCenter: parent.verticalCenter; width: 92 * ed.u; height: width
            Rectangle { anchors.fill: parent; radius: width / 2; color: ed.paper ? "#ececec" : "#232326"
                Icon { anchors.centerIn: parent; name: "door"; color: ed.muted; size: 36 * ed.u } }
            Rounded { anchors.fill: parent; radius: width / 2; source: home.doorStill; sourceWidth: 300 }
            Rectangle {  // online ring
                anchors.fill: parent; anchors.margins: -5 * ed.u; radius: width / 2; color: "transparent"; border.width: 3 * ed.u
                border.color: home.doorOnline === 1 ? "#30d158" : home.doorOnline === 0 ? "#ff453a" : ed.stroke
            }
        }
        Column {
            anchors.left: thumb.right; anchors.leftMargin: 22 * ed.u; anchors.verticalCenter: parent.verticalCenter; spacing: 4 * ed.u
            Text { text: "Front door"; color: ed.ink; font.family: ed.sans; font.pixelSize: 28 * ed.u; font.weight: Font.DemiBold; font.letterSpacing: -0.4 * ed.u }
            Text {
                text: (home.doorOnline === 1 ? "Online" : home.doorOnline === 0 ? "Offline" : "Waiting")
                      + (home.doorStillTime ? "  ·  " + U.ago(home.doorStillTime) : "")
                color: home.doorOnline === 0 ? "#ff453a" : ed.muted; font.family: ed.sans; font.pixelSize: 16 * ed.u; font.weight: Font.Medium
            }
        }
        Rectangle {
            anchors.right: parent.right; anchors.rightMargin: 20 * ed.u; anchors.verticalCenter: parent.verticalCenter
            width: 72 * ed.u; height: width; radius: width / 2; color: ed.hero
            Icon { anchors.centerIn: parent; name: "camera"; color: ed.heroInk; size: 32 * ed.u; stroke: 1.9 }
        }
        MouseArea { id: doorMa; anchors.fill: parent; onClicked: home.openDoor() }
    }

    // three plain tiles
    Row {
        x: ed.m; y: door.y + door.height + 16 * ed.u; spacing: 14 * ed.u
        Repeater {
            model: [
                { key: "events", icon: "bell", label: "Events", hint: home.visits.today ? home.visits.today + " today" : "" },
                { key: "view", icon: ed.news ? "photo" : "news", label: ed.news ? "Photos" : "News", hint: "" },
                { key: "settings", icon: "settings", label: "Settings", hint: "" }
            ]
            Rectangle {
                width: (ed.leftW - 2 * ed.m - 28 * ed.u) / 3; height: 124 * ed.u; radius: 28 * ed.u
                color: tMa.pressed ? Qt.darker(ed.panel, ed.paper ? 1.05 : 0.8) : ed.panel; border.width: 1; border.color: ed.stroke
                scale: tMa.pressed ? 0.96 : 1
                Behavior on scale { NumberAnimation { duration: 130 } }
                Icon { x: 20 * ed.u; y: 20 * ed.u; name: modelData.icon; color: ed.ink; size: 30 * ed.u; stroke: 1.7 }
                Text {
                    anchors.right: parent.right; anchors.rightMargin: 18 * ed.u; y: 22 * ed.u; text: modelData.hint; color: ed.muted
                    font.family: ed.sans; font.pixelSize: 14 * ed.u; font.weight: Font.DemiBold
                }
                Text {
                    x: 20 * ed.u; anchors.bottom: parent.bottom; anchors.bottomMargin: 18 * ed.u; text: modelData.label; color: ed.ink
                    font.family: ed.sans; font.pixelSize: 19 * ed.u; font.weight: Font.DemiBold
                }
                MouseArea {
                    id: tMa; anchors.fill: parent
                    onClicked: modelData.key === "events" ? home.openEvents() : modelData.key === "settings" ? home.openSettings()
                               : home.setView(ed.news ? "photos" : "news")
                }
            }
        }
    }

    // the latest at the door, and the voice orb
    Text {
        x: ed.m + 6 * ed.u; y: door.y + door.height + 16 * ed.u + 124 * ed.u + 26 * ed.u; width: ed.leftW - 2 * ed.m
        text: home.events.length ? home.events[0].replace(/^•\s*/, "") : (home.visits.last ? "Last visitor " + U.timeOf(home.visits.last) + ", " + U.dayOf(home.visits.last) : "All quiet at the door")
        color: ed.muted; elide: Text.ElideRight; font.family: ed.sans; font.pixelSize: 16 * ed.u; font.features: { "tnum": 1 }
    }
    Rectangle {
        x: ed.m; y: ed.bandY - 96 * ed.u; height: 68 * ed.u; width: askRow.width + 36 * ed.u; radius: height / 2
        color: askMa.pressed ? ed.panel : "transparent"; border.width: 1; border.color: ed.stroke
        Row {
            id: askRow; x: 10 * ed.u; anchors.verticalCenter: parent.verticalCenter; spacing: 14 * ed.u
            Orb { size: 48 * ed.u; mode: home.micState; anchors.verticalCenter: parent.verticalCenter }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: home.micState === "listening" ? "Listening…" : home.micState === "thinking" ? "One moment…" : "Ask the doorbell"
                color: ed.ink; font.family: ed.sans; font.pixelSize: 18 * ed.u; font.weight: Font.Medium
            }
        }
        MouseArea { id: askMa; anchors.fill: parent; onClicked: home.listen() }
    }

    // ---------- the foot: market and headlines ----------
    Rectangle { y: ed.bandY; width: parent.width; height: parent.height - y; color: ed.bg }
    MarketLine {
        x: ed.m; y: ed.bandY + 4 * ed.u; height: 30 * ed.u
        market: home.market; note: home.marketNote; pixelSize: 14 * ed.u
        color: ed.ink; muted: ed.muted; up: ed.paper ? "#1f8a4c" : "#30d158"; down: ed.paper ? "#c4271c" : "#ff6961"
    }
    Item {
        y: ed.bandY + 34 * ed.u; width: parent.width; height: parent.height - y
        readonly property bool hot: home.breaking.some(function (i) { return i.breaking })
        Rectangle {
            id: label; x: ed.m; anchors.verticalCenter: parent.verticalCenter
            width: lt.width + 22 * ed.u; height: 24 * ed.u; radius: height / 2
            color: parent.hot ? "#ff3b30" : "transparent"; border.width: parent.hot ? 0 : 1; border.color: ed.stroke
            Text {
                id: lt; anchors.centerIn: parent; text: parent.parent.hot ? "Breaking" : "Latest"
                color: parent.parent.hot ? "white" : ed.muted
                font.family: ed.sans; font.pixelSize: 12 * ed.u; font.weight: Font.Bold
            }
        }
        Ticker {
            x: label.x + label.width + 18 * ed.u; width: parent.width - x; height: parent.height
            items: home.breaking; color: ed.ink; sourceColor: ed.muted; markColor: ed.muted
            pixelSize: 18 * ed.u; weight: Font.Medium; speed: 70 * ed.u
        }
        Rectangle {
            x: label.x + label.width + 18 * ed.u; width: 40 * ed.u; height: parent.height
            gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: ed.bg } GradientStop { position: 1; color: "transparent" } }
        }
    }
}
