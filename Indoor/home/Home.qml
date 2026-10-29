import QtQuick

// The home screen. `home` (home_qml.HomeModel) brings the news, the market, the door's state
// and the events, and takes the taps. The look (Settings > Look) decides the layout; the
// breaking-news banner and festival decorations float over every look.
Item {
    id: root
    width: 1768; height: 828
    readonly property real u: Math.min(width / 1768, height / 828)
    readonly property var files: ({ editorial: "LookEditorial.qml", paper: "LookEditorial.qml", glass: "LookGlass.qml", fluent: "LookFluent.qml" })

    Rectangle { anchors.fill: parent; color: "black" }
    Loader {
        id: look; anchors.fill: parent
        source: root.files[home.look] || root.files.editorial
    }
    Festive { anchors.fill: parent; u: root.u; key: home.festival; greeting: home.greeting }
    Flash { anchors.horizontalCenter: parent.horizontalCenter; u: root.u; story: home.flash }
}
