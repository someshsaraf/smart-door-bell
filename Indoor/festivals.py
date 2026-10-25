"""Festival calendar for the smart themes.

Diwali follows the lunar calendar, so its date (the day of Lakshmi Puja) comes
from a table; add later years in config.json:
    "festivals": {"diwali": {"2031": "2031-11-14"}}
Christmas and New Year are fixed. Each festival has a window of whole days.
"""
import datetime as dt

FESTIVALS = {  # key: (display name, greeting)
    "diwali": ("Diwali", "Happy Diwali"),
    "christmas": ("Christmas", "Merry Christmas"),
    "new_year": ("New Year", "Happy New Year"),
}
DIWALI = {2025: "2025-10-20", 2026: "2026-11-08", 2027: "2027-10-29", 2028: "2028-10-17", 2029: "2029-11-05",
          2030: "2030-10-26"}

def windows(year, extra=None):
    """[(key, first day, last day)] for festivals that touch `year`."""
    out = []
    diwali = dict(DIWALI); diwali.update({int(y): d for y, d in ((extra or {}).get("diwali") or {}).items()})
    if year in diwali:
        d = dt.date.fromisoformat(diwali[year]); out.append(("diwali", d - dt.timedelta(days=2), d + dt.timedelta(days=2)))
    out.append(("christmas", dt.date(year, 12, 23), dt.date(year, 12, 27)))
    out.append(("new_year", dt.date(year, 1, 1), dt.date(year, 1, 2)))
    return out

def current(today, extra=None):
    """(key, last day) of the festival running on `today`, or (None, None)."""
    for key, first, last in windows(today.year, extra):
        if first <= today <= last:
            return key, last
    return None, None

def upcoming(today, extra=None, count=3):
    """Next windows that have not ended yet: [(key, first, last)]."""
    found = [w for y in (today.year, today.year + 1) for w in windows(y, extra) if w[2] >= today]
    return sorted(found, key=lambda w: w[1])[:count]

def greeting(key, today):
    name, text = FESTIVALS[key]
    if key == "new_year":  # the coming year when tried out before it starts
        return f"{text} {today.year + (today.month > 1)}"
    return text
