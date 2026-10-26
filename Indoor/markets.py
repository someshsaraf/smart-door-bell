"""NIFTY 50 and SENSEX, and the NIFTY 50's top gainers and losers, for the market
band of the news screen. From Yahoo Finance through the yfinance package (no
account; it talks to Yahoo like a browser, which plain requests are refused).

One download covers both indices and the 50 stocks: daily bars, today's (or the
last session's) close against the session before. The NIFTY 50 members come from
NSE's published list, refreshed weekly (markets_tokens.json), with a built-in copy
as fallback. Every 2 minutes during market hours (Mon-Fri 9:15-15:30 IST), every
30 minutes otherwise; on a failed poll the last values stay on screen.
Yahoo's Indian prices can lag the exchange by a few minutes."""
import csv, io, json, threading, time, urllib.request, warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from PySide6.QtCore import QThread, Signal

ROOT = Path(__file__).resolve().parent
MEMBERS = ROOT / "markets_tokens.json"
NIFTY_LIST = "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"
INDICES = (("^NSEI", "NIFTY 50"), ("^BSESN", "SENSEX"))
IST = timezone(timedelta(hours=5, minutes=30))
UA = "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
OPEN_POLL_S, CLOSED_POLL_S, RETRY_S = 120, 30 * 60, 300
FALLBACK = ("ADANIENT ADANIPORTS APOLLOHOSP ASIANPAINT AXISBANK BAJAJ-AUTO BAJFINANCE BAJAJFINSV BEL BHARTIARTL "
            "CIPLA COALINDIA DRREDDY EICHERMOT ETERNAL GRASIM HCLTECH HDFCBANK HDFCLIFE HINDALCO HINDUNILVR "
            "ICICIBANK INDIGO INFY ITC JIOFIN JSWSTEEL KOTAKBANK LT M&M MARUTI MAXHEALTH NESTLEIND NTPC ONGC "
            "POWERGRID RELIANCE SBILIFE SBIN SHRIRAMFIN SUNPHARMA TATACONSUM TATASTEEL TCS TECHM TITAN TRENT "
            "ULTRACEMCO WIPRO").split()


def market_open(now=None):
    n = now or datetime.now(IST)
    return n.weekday() < 5 and (9, 15) <= (n.hour, n.minute) < (15, 31)


def nifty_members():
    """NSE symbols of the NIFTY 50, from NSE's list (cached a week), else the built-in copy."""
    try:
        t = json.loads(MEMBERS.read_text(encoding="utf-8"))
        if time.time() - t["time"] < 7 * 86400 and len(t["symbols"]) >= 45: return t["symbols"]
    except (OSError, ValueError, KeyError): pass
    try:
        raw = urllib.request.urlopen(urllib.request.Request(NIFTY_LIST, headers={"User-Agent": UA}), timeout=20).read().decode()
        symbols = [r["Symbol"] for r in csv.DictReader(io.StringIO(raw))]
        if len(symbols) >= 45:
            MEMBERS.write_text(json.dumps({"time": time.time(), "symbols": symbols}), encoding="utf-8")
            return symbols
    except Exception: pass
    return FALLBACK


def snapshot():
    """One reading: both indices, and the NIFTY 50 ranked by the day's % change."""
    import yfinance as yf
    stocks = nifty_members()
    tickers = [t for t, _ in INDICES] + [s + ".NS" for s in stocks]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # pandas deprecation chatter from inside yfinance
        close = yf.download(tickers, period="5d", interval="1d", progress=False, auto_adjust=False, threads=True)["Close"]

    def day(ticker):
        """(last, previous close) from the last two daily bars, or None."""
        if ticker not in close: return None
        c = close[ticker].dropna()
        return (float(c.iloc[-1]), float(c.iloc[-2])) if len(c) >= 2 else None

    indices = []
    for ticker, name in INDICES:
        d = day(ticker)
        if d: indices.append({"name": name, "ltp": d[0], "change": d[0] - d[1], "pct": (d[0] / d[1] - 1) * 100})
    moves = []
    for s in stocks:
        d = day(s + ".NS")
        if d: moves.append({"symbol": s, "ltp": d[0], "pct": (d[0] / d[1] - 1) * 100})
    moves.sort(key=lambda m: -m["pct"])
    if not indices: raise RuntimeError("no index data from Yahoo")
    session = close[INDICES[0][0]].dropna().index[-1].strftime("%d %b").lstrip("0")  # the day the figures are from
    return {"indices": indices, "session": session, "gainers": [m for m in moves if m["pct"] > 0][:5],
            "losers": [m for m in reversed(moves) if m["pct"] < 0][:5], "time": time.time(), "open": market_open()}


class Markets(QThread):
    updated = Signal(dict)
    status = Signal(str)  # what is wrong ("" when fine), shown on the band while it has no data

    def __init__(self):
        super().__init__(); self.wake = threading.Event(); self.last = None

    def refresh(self): self.wake.set()

    def run(self):
        while not self.isInterruptionRequested():
            wait = OPEN_POLL_S if market_open() else CLOSED_POLL_S
            try:
                self.last = snapshot(); self.updated.emit(self.last); self.status.emit("")
            except ImportError:
                self.status.emit("market data needs the yfinance package (Indoor/setup_pi.sh installs it)"); wait = 3600
            except Exception as e:
                self.status.emit(f"market data unavailable ({str(e)[:80]}), retrying"); wait = min(wait, RETRY_S)
            self.wake.wait(wait); self.wake.clear()

    def stop(self):
        self.requestInterruption(); self.wake.set(); self.wait(3000)
