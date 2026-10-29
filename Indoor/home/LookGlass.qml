import QtQuick
import QtQuick.Effects
import "util.js" as U

// Glass: like a phone's home screen. The story's photo (or the slideshow) fills the screen and
// everything else sits on frosted-glass widgets: a big live Front door widget, the rings today,
// settings, the news card, and a dock with the news/photos switch and the voice orb.
Item {
    id: gl
    readonly property real u: Math.min(width / 1768, height / 828)
    readonly property string sans: "Inter Variable"
    readonly property bool news: home.view !== "photos"
    readonly property real m: 56 * u
    readonly property real colX: width - m - 672 * u   // the widget column
    readonly property color dim: Qt.rgba(1, 1, 1, 0.62)

    Clock { id: clk }
    Rotator { id: rot; count: home.news.length; running: gl.news && gl.visible }
    property var story: home.news.length ? home.news[Math.min(rot.index, home.news.length - 1)] : null
    property var cur: null
    onStoryChanged: swap.restart()
    SequentialAnimation {
        id: swap
        NumberAnimation { target: card; property: "contentOpacity"; to: 0; duration: 160 }
        ScriptAction { script: gl.cur = gl.story }
        NumberAnimation { target: card; property: "contentOpacity"; to: 1; duration: 450; easing.type: Easing.OutCubic }
    }

    // ---------- the wallpaper, and a blurred copy for the glass ----------
    Item {
        id: backdrop; anchors.fill: parent
        NewsBackdrop {
            anchors.fill: parent; visible: gl.news
            source: gl.cur ? gl.cur.image : ""; blur: 0.7; brightness: -0.22; saturation: 0.35
            fallback: "#1b2433"
        }
        PhotoShow { id: show; anchors.fill: parent; visible: !gl.news; photos: home.photos }
        Rectangle {  // keeps the clock readable on bright pictures
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0.32) }
                GradientStop { position: 0.4; color: Qt.rgba(0, 0, 0, 0.0) }
                GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.25) }
            }
        }
    }
    MultiEffect {
        id: frosted; anchors.fill: parent; source: backdrop; visible: false
        blurEnabled: true; blur: 1.0; blurMax: 64; saturation: 0.25; brightness: 0.02
    }

    // ---------- the clock, like a lock screen ----------
    Column {
        x: gl.m + 6 * gl.u; y: 34 * gl.u; spacing: -18 * gl.u
        Text {
            text: Qt.formatDate(clk.now, "dddd d MMMM"); color: Qt.rgba(1, 1, 1, 0.88)
            font.family: gl.sans; font.pixelSize: 26 * gl.u; font.weight: Font.DemiBold
        }
        Text {
            text: U.clock(clk.now); color: "white"
            font.family: gl.sans; font.pixelSize: 178 * gl.u; font.weight: 250; font.features: { "tnum": 1 }
            layer.enabled: true
            layer.effect: MultiEffect { shadowEnabled: true; shadowBlur: 0.8; shadowOpacity: 0.35; shadowVerticalOffset: 4 * gl.u }
        }
    }

    // ---------- the news card ----------
    Frost {
        id: card
        backdrop: frosted; x: gl.m; y: 290 * gl.u; width: gl.colX - gl.m - 44 * gl.u; height: 438 * gl.u
        radius: 36 * gl.u; tint: Qt.rgba(0.08, 0.09, 0.12, 0.30); stroke: Qt.rgba(1, 1, 1, 0.18)
        property real contentOpacity: 1
        opacity: gl.news ? 1 : 0; visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 500 } }

        Item {
            anchors.fill: parent; opacity: card.contentOpacity
            Item {
                id: pic; x: 22 * gl.u; y: 22 * gl.u; width: 360 * gl.u; height: parent.height - 44 * gl.u
                Rectangle {
                    anchors.fill: parent; radius: 24 * gl.u
                    gradient: Gradient {
                        GradientStop { position: 0; color: gl.cur ? Qt.darker(gl.cur.color, 1.2) : "#333" }
                        GradientStop { position: 1; color: gl.cur ? Qt.darker(gl.cur.color, 2.6) : "#111" }
                    }
                    Text { anchors.centerIn: parent; text: gl.cur ? gl.cur.source : ""; color: Qt.rgba(1, 1, 1, 0.9); font.family: gl.sans; font.pixelSize: 44 * gl.u; font.weight: Font.Black }
                }
                Rounded { anchors.fill: parent; radius: 24 * gl.u; source: gl.cur ? gl.cur.image : "" }
            }
            Column {
                x: pic.x + pic.width + 32 * gl.u; y: 34 * gl.u; width: parent.width - x - 34 * gl.u; spacing: 14 * gl.u
                Row {
                    spacing: 10 * gl.u
                    Rectangle { width: 10 * gl.u; height: width; radius: width / 2; color: gl.cur ? gl.cur.color : "white"; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: gl.cur ? gl.cur.source : ""; color: "white"; font.family: gl.sans; font.pixelSize: 18 * gl.u; font.weight: Font.Bold; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: gl.cur ? "·  " + U.ago(gl.cur.time) : ""; color: gl.dim; font.family: gl.sans; font.pixelSize: 18 * gl.u; anchors.verticalCenter: parent.verticalCenter }
                    Rectangle {
                        visible: !!(gl.cur && gl.cur.breaking); anchors.verticalCenter: parent.verticalCenter
                        width: bt.width + 20 * gl.u; height: 28 * gl.u; radius: height / 2; color: "#ff453a"
                        Text { id: bt; anchors.centerIn: parent; text: "Breaking"; color: "white"; font.family: gl.sans; font.pixelSize: 14 * gl.u; font.weight: Font.Bold }
                    }
                }
                Text {
                    width: parent.width; text: gl.cur ? gl.cur.title : ""; color: "white"
                    wrapMode: Text.WordWrap; maximumLineCount: 4; elide: Text.ElideRight; lineHeight: 1.08
                    font.family: gl.sans; font.weight: Font.DemiBold; font.pixelSize: (text.length < 70 ? 38 : 33) * gl.u
                }
                Text {
                    width: parent.width; text: gl.cur && gl.cur.summary !== gl.cur.title ? gl.cur.summary : ""; color: gl.dim
                    wrapMode: Text.WordWrap; maximumLineCount: 3; elide: Text.ElideRight; lineHeight: 1.25
                    font.family: gl.sans; font.pixelSize: 19 * gl.u
                }
            }
            // page: a capsule that fills until the next story
            Row {
                x: pic.x + pic.width + 32 * gl.u; y: parent.height - 52 * gl.u; spacing: 14 * gl.u
                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter; width: 120 * gl.u; height: 6 * gl.u; radius: 3 * gl.u; color: Qt.rgba(1, 1, 1, 0.22)
                    Rectangle { width: parent.width * rot.progress; height: parent.height; radius: parent.radius; color: "white" }
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: home.news.length ? (rot.index + 1) + " of " + home.news.length : ""; color: gl.dim
                    font.family: gl.sans; font.pixelSize: 15 * gl.u; font.weight: Font.Medium; font.features: { "tnum": 1 }
                }
            }
        }
        MouseArea {
            anchors.fill: parent; property real px: 0
            onPressed: (e) => px = e.x
            onReleased: (e) => {
                if (Math.abs(e.x - px) > 80 * gl.u) rot.go(e.x < px ? 1 : -1)
                else rot.go(e.x > width / 2 ? 1 : -1)
            }
        }
        Text {
            anchors.centerIn: parent; visible: home.news.length === 0
            text: home.newsNote || "Loading the news…"; color: gl.dim; font.family: gl.sans; font.pixelSize: 22 * gl.u
        }
    }
    // photos: the credit, on a small glass chip
    Frost {
        visible: !gl.news && show.credit !== ""
        backdrop: frosted; x: gl.m; y: foot.y - 16 * gl.u - height; height: 44 * gl.u; width: cr.width + 36 * gl.u
        radius: height / 2; tint: Qt.rgba(0, 0, 0, 0.18)
        Text { id: cr; anchors.centerIn: parent; text: "Photo · " + show.credit; color: "white"; font.family: gl.sans; font.pixelSize: 15 * gl.u; font.weight: Font.Medium }
    }

    // ---------- the widgets ----------
    // the front door: the camera's latest picture, live on a tap
    Item {
        id: doorW
        x: gl.colX; y: gl.m; width: 672 * gl.u; height: 300 * gl.u
        scale: doorMa.pressed ? 0.98 : 1
        Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutQuad } }
        Frost { anchors.fill: parent; backdrop: frosted; radius: 38 * gl.u; tint: Qt.rgba(0.1, 0.12, 0.16, 0.3) }
        Rounded { id: still; anchors.fill: parent; radius: 38 * gl.u; source: home.doorStill; sourceWidth: 900 }
        Rectangle {
            anchors.fill: parent; radius: 38 * gl.u; visible: still.status === Image.Ready
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0.25) }
                GradientStop { position: 0.45; color: Qt.rgba(0, 0, 0, 0.0) }
                GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.62) }
            }
        }
        Icon { anchors.centerIn: parent; visible: still.status !== Image.Ready; name: "door"; color: "white"; size: 90 * gl.u; opacity: 0.35; stroke: 1.2 }
        Rectangle {  // online / offline
            x: 24 * gl.u; y: 22 * gl.u; height: 36 * gl.u; width: st.width + 42 * gl.u; radius: height / 2; color: Qt.rgba(0, 0, 0, 0.42)
            Rectangle {
                id: stDot; x: 15 * gl.u; anchors.verticalCenter: parent.verticalCenter; width: 10 * gl.u; height: width; radius: width / 2
                color: home.doorOnline === 1 ? "#30d158" : home.doorOnline === 0 ? "#ff453a" : "#8e8e93"
            }
            Text {
                id: st; anchors.left: stDot.right; anchors.leftMargin: 8 * gl.u; anchors.verticalCenter: parent.verticalCenter
                text: home.doorOnline === 1 ? "Online" : home.doorOnline === 0 ? "Offline" : "Waiting"
                color: "white"; font.family: gl.sans; font.pixelSize: 15 * gl.u; font.weight: Font.DemiBold
            }
        }
        Column {
            x: 30 * gl.u; anchors.bottom: parent.bottom; anchors.bottomMargin: 26 * gl.u; spacing: 2 * gl.u
            Text { text: "Front door"; color: "white"; font.family: gl.sans; font.pixelSize: 40 * gl.u; font.weight: Font.Bold }
            Text {
                text: home.doorStillTime ? "Picture from " + U.ago(home.doorStillTime) + " · tap for live" : "Tap to see who's there"
                color: Qt.rgba(1, 1, 1, 0.8); font.family: gl.sans; font.pixelSize: 17 * gl.u; font.weight: Font.Medium
            }
        }
        Rectangle {
            anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 24 * gl.u
            width: 76 * gl.u; height: width; radius: width / 2; color: "white"
            Icon { anchors.centerIn: parent; name: "camera"; color: "#111111"; size: 34 * gl.u; stroke: 1.9 }
        }
        MouseArea { id: doorMa; anchors.fill: parent; onClicked: home.openDoor() }
    }

    component Widget: Item {
        id: w
        property string icon
        property color iconBg
        property string title
        property string line
        property string big
        signal tapped
        width: 325 * gl.u; height: 210 * gl.u
        scale: wma.pressed ? 0.97 : 1
        Behavior on scale { NumberAnimation { duration: 140 } }
        Frost { anchors.fill: parent; backdrop: frosted; radius: 36 * gl.u; tint: Qt.rgba(0.08, 0.09, 0.12, 0.30) }
        Rectangle {
            x: 24 * gl.u; y: 24 * gl.u; width: 50 * gl.u; height: width; radius: 14 * gl.u; color: w.iconBg
            Icon { anchors.centerIn: parent; name: w.icon; color: "white"; size: 28 * gl.u; stroke: 1.9 }
        }
        Text {
            anchors.right: parent.right; anchors.rightMargin: 26 * gl.u; y: 14 * gl.u
            text: w.big; color: "white"; font.family: gl.sans; font.pixelSize: 64 * gl.u; font.weight: Font.DemiBold; font.features: { "tnum": 1 }
        }
        Column {
            x: 26 * gl.u; anchors.bottom: parent.bottom; anchors.bottomMargin: 22 * gl.u; spacing: 3 * gl.u
            Text { text: w.title; color: "white"; font.family: gl.sans; font.pixelSize: 26 * gl.u; font.weight: Font.Bold }
            Text { text: w.line; color: gl.dim; font.family: gl.sans; font.pixelSize: 16 * gl.u; font.weight: Font.Medium }
        }
        MouseArea { id: wma; anchors.fill: parent; onClicked: w.tapped() }
    }
    Widget {
        x: gl.colX; y: doorW.y + doorW.height + 22 * gl.u
        icon: "bell"; iconBg: "#ff453a"; title: "Events"; big: home.visits.today ? String(home.visits.today) : ""
        line: home.visits.last ? (home.visits.today ? "rings today · last " : "Last ring ") + U.timeOf(home.visits.last) : "No rings yet"
        onTapped: home.openEvents()
    }
    Widget {
        x: gl.colX + 347 * gl.u; y: doorW.y + doorW.height + 22 * gl.u
        icon: "settings"; iconBg: "#636366"; title: "Settings"; line: "Look, sound, camera"
        onTapped: home.openSettings()
    }

    // the dock: news or photos, and the voice orb
    Item {
        x: gl.colX; y: doorW.y + doorW.height + 22 * gl.u + 210 * gl.u + 22 * gl.u; width: 672 * gl.u; height: 128 * gl.u
        Frost { anchors.fill: parent; backdrop: frosted; radius: 36 * gl.u; tint: Qt.rgba(0.08, 0.09, 0.12, 0.30) }
        Rectangle {  // segmented control
            id: seg; x: 22 * gl.u; anchors.verticalCenter: parent.verticalCenter; width: 330 * gl.u; height: 60 * gl.u; radius: height / 2
            color: Qt.rgba(1, 1, 1, 0.14)
            Rectangle {
                x: (gl.news ? 0 : parent.width / 2) + 4 * gl.u; y: 4 * gl.u; width: parent.width / 2 - 8 * gl.u; height: parent.height - 8 * gl.u
                radius: height / 2; color: Qt.rgba(1, 1, 1, 0.92)
                Behavior on x { NumberAnimation { duration: 280; easing.type: Easing.OutCubic } }
            }
            Repeater {
                model: [["news", "News"], ["photos", "Photos"]]
                Item {
                    x: index * seg.width / 2; width: seg.width / 2; height: seg.height
                    Row {
                        anchors.centerIn: parent; spacing: 8 * gl.u
                        Icon { name: modelData[0] === "news" ? "news" : "photo"; size: 22 * gl.u; color: home.view === modelData[0] ? "#111111" : "#ffffff"; anchors.verticalCenter: parent.verticalCenter }
                        Text {
                            text: modelData[1]; anchors.verticalCenter: parent.verticalCenter
                            color: home.view === modelData[0] ? "#111111" : "white"
                            font.family: gl.sans; font.pixelSize: 18 * gl.u; font.weight: Font.DemiBold
                        }
                    }
                    MouseArea { anchors.fill: parent; onClicked: home.setView(modelData[0]) }
                }
            }
        }
        Row {
            anchors.right: parent.right; anchors.rightMargin: 24 * gl.u; anchors.verticalCenter: parent.verticalCenter; spacing: 16 * gl.u
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: home.micState === "listening" ? "Listening…" : home.micState === "thinking" ? "Thinking…" : "Ask the\ndoorbell"
                horizontalAlignment: Text.AlignRight; color: "white"; lineHeight: 0.95
                font.family: gl.sans; font.pixelSize: 17 * gl.u; font.weight: Font.DemiBold
            }
            Orb { size: 80 * gl.u; mode: home.micState; anchors.verticalCenter: parent.verticalCenter }
        }
        MouseArea { x: seg.x + seg.width; width: parent.width - x; height: parent.height; onClicked: home.listen() }
    }

    // ---------- the foot: market and headlines on one glass bar ----------
    Frost {
        id: foot
        backdrop: frosted; x: gl.m; y: parent.height - 22 * gl.u - height; width: parent.width - 2 * gl.m; height: 54 * gl.u
        radius: height / 2; tint: Qt.rgba(0.08, 0.09, 0.12, 0.34)
        MarketLine {
            id: mk; x: 26 * gl.u; height: parent.height; movers: false
            market: home.market; note: home.marketNote; pixelSize: 15 * gl.u
            color: "white"; muted: Qt.rgba(1, 1, 1, 0.6); up: "#30d158"; down: "#ff6961"
        }
        Rectangle { id: sep; x: mk.x + mk.width + 22 * gl.u; anchors.verticalCenter: parent.verticalCenter; width: 1; height: 26 * gl.u; color: Qt.rgba(1, 1, 1, 0.25) }
        Ticker {
            x: sep.x + 22 * gl.u; width: parent.width - x - 26 * gl.u; height: parent.height
            items: home.breaking; color: "white"; sourceColor: Qt.rgba(1, 1, 1, 0.6); markColor: Qt.rgba(1, 1, 1, 0.4)
            pixelSize: 18 * gl.u; weight: Font.Medium; speed: 70 * gl.u
        }
    }
}
