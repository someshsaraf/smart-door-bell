"""Turns a spoken sentence (already text) into one of the dashboard's commands.

A fixed set of commands with forgiving wording, so the result is predictable
and instant; no cloud. parse() returns (action, args, reply) or None:

  stop       "stop the bell", "stop ringing", "silence"
  mute       "mute the bell for an hour", "mute for 30 minutes"   args: minutes
  unmute     "unmute the bell", "turn the bell back on"
  events     "show (me) all events", "show events from yesterday / last Monday /
             20 October / this week / last week"                    args: (start, end, label)
  play_last  "play the last recording", "show the last visitor"
  door       "show the front door", "who is at the door"
  home       "go home", "close", "go back"
  settings   "open settings"
"""
import datetime as dt
import re

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10, "fifteen": 15,
           "twenty": 20, "thirty": 30, "forty five": 45, "half an": 0.5, "half": 0.5}


def clean(text):
    t = text.lower().replace("’", "'")
    t = re.sub(r"[^a-z0-9' ]+", " ", t)
    t = re.sub(r"\b(\d+)(st|nd|rd|th)\b", r"\1", t)  # 20th -> 20
    return " ".join(t.split())


def day_range(text, today):
    """(start date, end date inclusive, label) named in the text, or None for no date."""
    if "today" in text: return today, today, "today"
    if "yesterday" in text: return today - dt.timedelta(1), today - dt.timedelta(1), "yesterday"
    if "this week" in text:
        start = today - dt.timedelta(today.weekday()); return start, today, "this week"
    if "last week" in text:
        start = today - dt.timedelta(today.weekday() + 7); return start, start + dt.timedelta(6), "last week"
    if "this month" in text: return today.replace(day=1), today, "this month"
    if "last month" in text:
        end = today.replace(day=1) - dt.timedelta(1); return end.replace(day=1), end, "last month"
    for i, name in enumerate(DAYS):  # "on monday", "last monday": the most recent one, today excluded
        if re.search(rf"\b{name}\b", text):
            back = (today.weekday() - i) % 7 or 7
            d = today - dt.timedelta(back); return d, d, d.strftime("%A %d %B").replace(" 0", " ")
    m = re.search(r"\b(\d{1,2}) (?:of )?(" + "|".join(MONTHS) + r")\b|\b(" + "|".join(MONTHS) + r") (\d{1,2})\b", text)
    if m:
        day = int(m.group(1) or m.group(4)); month = MONTHS.index(m.group(2) or m.group(3)) + 1
        try:
            d = dt.date(today.year, month, day)
            if d > today: d = d.replace(year=today.year - 1)  # "20 December" said in January
            return d, d, d.strftime("%d %B").lstrip("0")
        except ValueError:
            return None
    return None


def minutes(text):
    m = re.search(r"\b(\d+|" + "|".join(sorted(NUMBERS, key=len, reverse=True)) + r") (hour|hours|minute|minutes|min|mins)\b", text)
    if not m: return 60
    n = float(m.group(1)) if m.group(1).isdigit() else NUMBERS[m.group(1)]
    return int(n * 60) if m.group(2).startswith("hour") else int(n)


def parse(text, today=None):
    today = today or dt.date.today()
    t = clean(text)
    if not t: return None
    if re.search(r"\b(unmute|un mute)\b|turn the (bell|chime|sound) (back )?on|bell back on", t):
        return "unmute", None, "The bell is on again"
    if re.search(r"\b(mute|quiet|do not disturb)\b", t) and re.search(r"\b(for|bell|chime|doorbell)\b", t):
        mins = minutes(t)
        return "mute", mins, f"Bell muted for {mins // 60} hour{'s' if mins >= 120 else ''}" if mins % 60 == 0 else f"Bell muted for {mins} minutes"
    if re.search(r"\b(stop|silence|enough|shut up|quiet)\b", t) and not re.search(r"\b(event|recording)s?\b", t):
        return "stop", None, "Stopping the bell"
    if re.search(r"\b(play|show|open)\b.*\b(last|latest|recent)\b.*\b(recording|video|clip|visitor|event|one)\b", t):
        return "play_last", None, "Playing the last recording"
    if re.search(r"\b(event|events|visitors|rings|recordings|history|who came|who rang|what happened|(?:any|some)(?:one|body) (?:came|come|rang|ring|visit|visited))\b", t):
        r = None if re.search(r"\ball\b", t) and not re.search(r"\ball (events )?(from|on|of)\b", t) else day_range(t, today)
        if r: return "events", r, f"Events from {r[2]}"
        return "events", None, "All events"
    if re.search(r"\b(front door|camera|who is at the door|who's at the door|door)\b", t):
        return "door", None, "Front door"
    if re.search(r"\b(settings?|setup)\b", t):
        return "settings", None, "Settings"
    if re.search(r"\b(go home|home|close|go back|back|main screen)\b", t):
        return "home", None, "Home"
    return None
