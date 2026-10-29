"""The looks of the indoor screen (Settings > Look). Each one is a home screen
layout in Qt Quick (home/Look*.qml) plus the colours and typefaces of the
other pages (app.py STYLE) and of the web page.

A festival's colours (app.py PALETTES) replace the look's colours while it
lasts; the layout stays."""
from pathlib import Path

PREVIEWS = Path(__file__).resolve().parent / "assets" / "looks"  # <key>.png, shown in Settings > Look

LOOKS = {
    "editorial": dict(
        name="Editorial", about="A cover: the story's photo fills the screen with its headline set large; the clock, the front door and three tiles on a black panel.",
        colors=dict(bg="#0a0a0b", panel="#161618", button="#1f1f22", border="#38383c", line="#2a2a2d", accent="#f5f5f7",
                    on_accent="#0a0a0b", muted="#8e8e93", list="#121214", count="#ffffff", tag="#d1d1d6",
                    text="#f5f5f7", text2="#aeaeb2"),
        type=dict(sans="Inter Variable", display="Inter Variable", title_px="24px", page_px="36px", title_weight="600")),
    "paper": dict(
        name="Paper", about="The same cover with a light panel: black type and a black front door button, for a bright room.",
        colors=dict(bg="#f4f3ef", panel="#ffffff", button="#ffffff", border="#d2d2d7", line="#e5e5ea", accent="#111111",
                    on_accent="#ffffff", muted="#6e6e73", list="#f9f9f7", count="#111111", tag="#3a3a3c",
                    text="#111111", text2="#48484a"),
        type=dict(sans="Inter Variable", display="Inter Variable", title_px="24px", page_px="36px", title_weight="600")),
    "glass": dict(
        name="Glass", about="Like a phone's home screen: frosted-glass widgets over the story's photo, with a big live Front door widget.",
        colors=dict(bg="#0d1320", panel="#162033", button="#1e2a41", border="#33435f", line="#25324a", accent="#0a84ff",
                    on_accent="#ffffff", muted="#97a6bd", list="#111a2b", count="#64b5ff", tag="#64b5ff",
                    text="#f2f6fc", text2="#b8c4d6"),
        type=dict(sans="Inter Variable", display="Inter Variable", title_px="22px", page_px="34px", title_weight="700")),
    "fluent": dict(
        name="Fluent", about="Like a Windows app: a navigation pane with an accent Front door button, and cards on a soft Mica backdrop.",
        colors=dict(bg="#202020", panel="#2b2b2b", button="#373737", border="#454545", line="#3a3a3a", accent="#60cdff",
                    on_accent="#00141f", muted="#9d9d9d", list="#262626", count="#60cdff", tag="#60cdff",
                    text="#ffffff", text2="#c8c8c8"),
        type=dict(sans="Inter Variable", display="Inter Variable", title_px="22px", page_px="32px", title_weight="600")),
}
DEFAULT = "editorial"


def get(key):
    return LOOKS.get(key) or LOOKS[DEFAULT]


def preview(key):
    """The look's picture for Settings > Look, if there is one."""
    p = PREVIEWS / f"{key}.png"
    return p if p.exists() else None
