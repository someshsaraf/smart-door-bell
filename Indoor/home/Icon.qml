import QtQuick
import "util.js" as U

// A line icon from util.js in one colour (use opacity for transparency).
Image {
    property string name
    property color color: "white"
    property real size: 24
    property real stroke: 1.6
    width: size; height: size
    sourceSize: Qt.size(Math.ceil(size * 2), Math.ceil(size * 2))
    source: name ? U.icon(name, "#" + color.toString().slice(-6), stroke) : ""
    smooth: true; mipmap: true
}
