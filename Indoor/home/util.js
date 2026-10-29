.pragma library
// Small helpers shared by the home screen's looks: icons, times and numbers.

// Line icons on a 24 x 24 grid, drawn for this dashboard (stroke = the icon's colour).
var ICONS = {
    door: '<path d="M6 21V4.5A1.5 1.5 0 0 1 7.5 3h9A1.5 1.5 0 0 1 18 4.5V21"/><path d="M3 21h18"/><circle cx="14.6" cy="12.4" r="0.6" fill="C"/>',
    camera: '<rect x="2.5" y="6" width="13.5" height="12" rx="2.5"/><path d="M16 10.2l5.5-3.1v9.8L16 13.8z"/>',
    bell: '<path d="M6 9.5a6 6 0 0 1 12 0c0 5.2 2 7 2 7H4s2-1.8 2-7"/><path d="M10.2 20a1.9 1.9 0 0 0 3.6 0"/>',
    events: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5V12l3 2"/>',
    news: '<path d="M4 5.5h12.5V19a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/><path d="M16.5 9H20v10a2 2 0 0 1-2 2"/><path d="M7.5 9h5.5M7.5 12.5h5.5M7.5 16h3.5"/>',
    photo: '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><circle cx="9" cy="10" r="1.8"/><path d="M21 15.5l-4.8-4.8L6 20"/>',
    settings: '<path d="M18.88 9.87 L21.46 10.38 L21.46 13.62 L18.88 14.13 L18.37 15.36 L19.84 17.54 L17.54 19.84 L15.36 18.37 L14.13 18.88 L13.62 21.46 L10.38 21.46 L9.87 18.88 L8.64 18.37 L6.46 19.84 L4.16 17.54 L5.63 15.36 L5.12 14.13 L2.54 13.62 L2.54 10.38 L5.12 9.87 L5.63 8.64 L4.16 6.46 L6.46 4.16 L8.64 5.63 L9.87 5.12 L10.38 2.54 L13.62 2.54 L14.13 5.12 L15.36 5.63 L17.54 4.16 L19.84 6.46 L18.37 8.64 Z"/><circle cx="12" cy="12" r="3.2"/>',
    mic: '<rect x="9" y="3" width="6" height="11.5" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3"/>',
    arrow: '<path d="M4.5 12h15M13.5 6l6 6-6 6"/>',
    left: '<path d="M14.5 6l-6 6 6 6"/>',
    right: '<path d="M9.5 6l6 6-6 6"/>',
    home: '<path d="M3.5 10.5L12 3.5l8.5 7V20a1 1 0 0 1-1 1h-5v-6h-5v6h-5a1 1 0 0 1-1-1z"/>',
    wifi: '<path d="M2.5 9a14 14 0 0 1 19 0M5.5 12.3a9.5 9.5 0 0 1 13 0M8.6 15.5a5 5 0 0 1 6.8 0"/><circle cx="12" cy="19" r="0.6" fill="C"/>',
    spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8"/>',
    up: '<path d="M6 15l6-6 6 6"/>',
    down: '<path d="M6 9l6 6 6-6"/>'
};

// the icon as an image source in the given colour
function icon(name, color, width) {
    var body = (ICONS[name] || "").replace(/="C"/g, '="' + color + '"');
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="' + color +
              '" stroke-width="' + (width || 1.6) + '" stroke-linecap="round" stroke-linejoin="round">' + body + '</svg>';
    return "data:image/svg+xml;base64," + Qt.btoa(svg);
}

function ago(t) {
    var s = Date.now() / 1000 - t;
    if (!t || s < 0) return "";
    if (s < 90) return "just now";
    if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 86400) return Math.round(s / 3600) + " h ago";
    return Math.round(s / 86400) + " d ago";
}
function clock(d) { var m = d.getMinutes(); return (d.getHours() % 12 || 12) + ":" + (m < 10 ? "0" : "") + m; }
function ampm(d) { return d.getHours() < 12 ? "am" : "pm"; }
function greeting(d) { var h = d.getHours(); return h < 5 ? "Good night" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening"; }
function longDate(d) { return Qt.formatDate(d, "dddd, d MMMM"); }
function timeOf(t) { return t ? clock(new Date(t * 1000)) + " " + ampm(new Date(t * 1000)) : ""; }
function dayOf(t) {
    if (!t) return "";
    var d = new Date(t * 1000), now = new Date();
    if (d.toDateString() === now.toDateString()) return "today";
    var y = new Date(now.getTime() - 86400000);
    return d.toDateString() === y.toDateString() ? "yesterday" : Qt.formatDate(d, "d MMM");
}
// 22,749.75 (Indian grouping)
function num(v) {
    var s = Math.abs(v).toFixed(2).split("."), i = s[0], last = i.slice(-3), rest = i.slice(0, -3);
    if (rest) last = rest.replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + last;
    return (v < 0 ? "-" : "") + last + "." + s[1];
}
function pct(p) { return (p >= 0 ? "+" : "") + p.toFixed(2) + "%"; }
function pad2(n) { return (n < 10 ? "0" : "") + n; }
