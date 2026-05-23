"""
RRG SCREENER v6 - Render.com Edition
====================================
Data:     Live from NSE India via 'nsepython'
Strategy: Daily history cache + Live snapshot appending
Alerts:   Telegram + ntfy.sh + WhatsApp
Engine:   Flask Web Server + Background Threading
"""
import sys, os, json, time, logging, warnings, threading
from io import StringIO
import numpy as np
import pandas as pd
import requests
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from zoneinfo import ZoneInfo
from flask import Flask

# Use nsepythonserver to bypass cloud datacenter blocks
try:
    from nsepython import equity_history, index_history, nsefetch
except ImportError:
    from nsepythonserver import equity_history, index_history, nsefetch

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)
warnings.filterwarnings('ignore')

# ── CONFIG ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN        = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT         = os.getenv("TELEGRAM_CHAT",  "")
WHATSAPP_PHONE        = os.getenv("WHATSAPP_PHONE", "")
WHATSAPP_APIKEY       = os.getenv("WHATSAPP_APIKEY", "")
NTFY_TOPIC            = os.getenv("NTFY_TOPIC",     "rrg-alerts-drazygos")

SCAN_INTERVAL_MARKET  = int(os.getenv("SCAN_INTERVAL_MARKET",   "30"))
SCAN_INTERVAL_OFF     = int(os.getenv("SCAN_INTERVAL_OFFMARKET", "240"))
SCRIPT_DIR            = os.path.dirname(os.path.abspath(__file__))
STATE_FILE            = os.path.join(SCRIPT_DIR, "rrg_state_v6.json")
UNIVERSE_FILE         = os.path.join(SCRIPT_DIR, "rrg_universe.json")

UNIVERSE_REFRESH_DAYS = 7
IST                   = ZoneInfo("Asia/Kolkata")
MARKET_OPEN           = dtime(9, 15)
MARKET_CLOSE          = dtime(15, 30)
RRG_PERIOD            = 10

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

# ── OFFICIAL NSE INDEX MAP ────────────────────────────────────────────────────
NSE_INDICES = {
    "CNX50":             "NIFTY 50",
    "NIFTY METAL":       "NIFTY METAL",
    "NIFTY ENERGY":      "NIFTY ENERGY",
    "NIFTY PHARMA":      "NIFTY PHARMA",
    "NIFTY FMCG":        "NIFTY FMCG",
    "NIFTY AUTO":        "NIFTY AUTO",
    "NIFTY BANK":        "NIFTY BANK",
    "NIFTY PSU BANK":    "NIFTY PSU BANK",
    "NIFTY PVT BANK":    "NIFTY PRIVATE BANK",
    "NIFTY IT":          "NIFTY IT",
    "NIFTY INFRA":       "NIFTY INFRA",
    "NIFTY REALTY":      "NIFTY REALTY",
    "NIFTY MEDIA":       "NIFTY MEDIA",
    "NIFTY CPSE":        "NIFTY CPSE",
    "NIFTY COMMODITIES": "NIFTY COMMODITIES",
    "NIFTY FIN SERVICE": "NIFTY FIN SERVICE",
}
SECTORS = [k for k in NSE_INDICES if k != "CNX50"]

# ── UNIVERSE FETCHER ──────────────────────────────────────────────────────────
FALLBACK_CONSTITUENTS = {
    "NIFTY METAL": ["NATIONALUM","HINDCOPPER","HINDALCO","SAIL","WELCORP","VEDL","JSWSTEEL","TATASTEEL","JINDALSTEL","NMDC","COALINDIA"],
    "NIFTY ENERGY": ["ADANIPOWER","ADANIGREEN","GAIL","ONGC","NTPC","POWERGRID","RELIANCE","IOC","BPCL"],
    "NIFTY FMCG": ["NESTLEIND","RADICO","VBL","ITC","MARICO","BRITANNIA","TATACONSUM","HINDUNILVR","GODREJCP","DABUR"],
    "NIFTY PHARMA": ["SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","LUPIN","TORNTPHARM","AUROPHARMA","ALKEM"],
    "NIFTY AUTO": ["MARUTI","TATAMOTORS","M&M","BAJAJ-AUTO","HEROMOTOCO","EICHERMOT","TVSMOTOR","ASHOKLEY"],
    "NIFTY BANK": ["HDFCBANK","ICICIBANK","KOTAKBANK","AXISBANK","SBIN","INDUSINDBK","BANDHANBNK","FEDERALBNK"],
    "NIFTY IT": ["TCS","INFY","HCLTECH","WIPRO","TECHM","LTIM","MPHASIS","COFORGE"],
}

def get_universe():
    is_sunday = datetime.now(IST).weekday() == 6
    if Path(UNIVERSE_FILE).exists():
        try:
            with open(UNIVERSE_FILE) as f:
                data = json.load(f)
            stale = (datetime.now(IST) - datetime.fromisoformat(data.get("updated", "2000-01-01"))).days >= UNIVERSE_REFRESH_DAYS
            if not stale and not is_sunday:
                return data.get("constituents", {})
        except: pass
    
    log.info("Using Fallback Universe (File not found or stale)")
    with open(UNIVERSE_FILE, "w") as f:
        json.dump({"updated": datetime.now(IST).isoformat(), "constituents": FALLBACK_CONSTITUENTS}, f, indent=2)
    return FALLBACK_CONSTITUENTS

# ── LIVE NSE DATA ENGINE ──────────────────────────────────────────────────────
_history_cache = {}
_last_cache_date = None

def get_history(symbol, is_index=False):
    global _last_cache_date
    current_date = datetime.now(IST).date()
    
    if _last_cache_date != current_date:
        _history_cache.clear()
        _last_cache_date = current_date

    if symbol in _history_cache: return _history_cache[symbol]

    end_date = datetime.now(IST).strftime("%d-%m-%Y")
    start_date = (datetime.now(IST) - timedelta(days=360)).strftime("%d-%m-%Y")
    
    try:
        if is_index:
            df = index_history(symbol, start_date, end_date)
            date_col, close_col = 'HistoricalDate', 'CLOSE'
        else:
            df = equity_history(symbol, "EQ", start_date, end_date)
            date_col, close_col = ('CH_TIMESTAMP', 'CH_CLOSING_PRICE') if 'CH_TIMESTAMP' in df.columns else ('Date', 'Close')
            
        if df is not None and not df.empty:
            df[date_col] = pd.to_datetime(df[date_col])
            df = df.sort_values(date_col).set_index(date_col)
            series = df[close_col].astype(float)
            _history_cache[symbol] = series
            time.sleep(0.3) 
            return series
    except Exception as e: log.debug(f"History fetch failed for {symbol}: {e}")
    return None

def get_live_market_snapshot():
    live_prices = {}
    try:
        index_payload = nsefetch("https://www.nseindia.com/api/allIndices")
        for item in index_payload.get("data", []): live_prices[item["indexSymbol"]] = item["last"]
        stock_payload = nsefetch("https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20500")
        for item in stock_payload.get("data", []): live_prices[item["symbol"]] = item["lastPrice"]
    except Exception as e: log.error(f"Live fetch failed: {e}")
    return live_prices

# ── RRG CALCULATOR ────────────────────────────────────────────────────────────
def compute_rrg(stock_close, bench_close, period=RRG_PERIOD):
    common = stock_close.index.intersection(bench_close.index)
    if len(common) < period + 5: return None, None
    sc, bc = stock_close.loc[common].astype(float), bench_close.loc[common].astype(float)
    rs = (sc / bc) * 100
    rs_ratio = 100 + ((rs - rs.rolling(period).mean()) / rs.rolling(period).std().replace(0, np.nan))
    roc = rs_ratio.diff(1)
    rs_mom = 100 + ((roc - roc.rolling(period).mean()) / roc.rolling(period).std().replace(0, np.nan))
    return rs_ratio.round(3), rs_mom.round(3)

def get_quadrant(rsr, rsm):
    if rsr >= 100 and rsm >= 100: return "leading"
    if rsr >= 100 and rsm <  100: return "weakening"
    if rsr <  100 and rsm >= 100: return "improving"
    return "lagging"

def get_angle(trail_rsr, trail_rsm):
    if len(trail_rsr) < 2: return "unknown"
    ang = np.degrees(np.arctan2(trail_rsm[-1] - trail_rsm[-2], trail_rsr[-1] - trail_rsr[-2]))
    if 45 < ang <= 135: return "NE - Leading up"
    elif 0 < ang <= 45: return "E  - RS rising"
    elif ang > 135 or ang <= -135: return "SW - Weakening"
    elif -45 < ang <= 0: return "SE - Fading"
    elif -135 < ang <= -45: return "S  - Losing momentum"
    else: return "N  - Momentum surge"

def scan_pair(stock_ticker, bench_ticker, interval, live_prices, is_stock=True):
    stock_hist = get_history(stock_ticker, is_index=not is_stock)
    bench_hist = get_history(bench_ticker, is_index=True)
    if stock_hist is None or bench_hist is None: return None
        
    stock_live, bench_live = live_prices.get(stock_ticker), live_prices.get(bench_ticker)
    if not stock_live or not bench_live: return None

    freq = "W-FRI" if interval == "1wk" else "ME"
    sc, bc = stock_hist.resample(freq).last(), bench_hist.resample(freq).last()
    
    live_timestamp = pd.Timestamp.now(IST).normalize()
    sc.loc[live_timestamp], bc.loc[live_timestamp] = float(stock_live), float(bench_live)

    rsr, rsm = compute_rrg(sc, bc)
    if rsr is None: return None
    
    valid_rsr, valid_rsm = rsr.dropna().tail(5), rsm.dropna().tail(5)
    if len(valid_rsr) < 2: return None
    
    cur_rsr, cur_rsm = float(valid_rsr.iloc[-1]), float(valid_rsm.iloc[-1])
    return {
        "quadrant": get_quadrant(cur_rsr, cur_rsm),
        "rs_ratio": round(cur_rsr, 3), "rs_momentum": round(cur_rsm, 3),
        "angle": get_angle(list(valid_rsr), list(valid_rsm)),
        "trail_rsr": [round(v, 3) for v in valid_rsr.tolist()],
        "trail_rsm": [round(v, 3) for v in valid_rsm.tolist()],
        "updated": datetime.now(IST).isoformat()
    }

# ── ALERTS & STATE ────────────────────────────────────────────────────────────
def load_state():
    if Path(STATE_FILE).exists():
        try:
            with open(STATE_FILE) as f: return json.load(f)
        except: pass
    return {}

def save_state(state):
    with open(STATE_FILE, "w") as f: json.dump(state, f, indent=2)

def send_whatsapp(msg):
    if not WHATSAPP_PHONE or not WHATSAPP_APIKEY: return
    try:
        r = requests.get("https://api.callmebot.com/whatsapp.php", 
                         params={"phone": WHATSAPP_PHONE, "text": msg, "apikey": WHATSAPP_APIKEY}, timeout=10)
        log.info(f"WhatsApp: {'OK' if r.status_code==200 else 'FAIL '+str(r.status_code)}")
    except Exception as e: log.warning(f"WhatsApp Error: {e}")

def fire_alert(kind, name, benchmark, interval, old_q, new_q, data):
    msg = (f"*QUADRANT CHANGE*\n\n"
           f"{'Sector' if kind=='sector' else 'Stock'}: *{name}*\n"
           f"{old_q.upper()} -> *{new_q.upper()}*\n"
           f"Angle: {data['angle']}\n\n"
           f"RS-Ratio:    {data['rs_ratio']}\n"
           f"RS-Momentum: {data['rs_momentum']}\n"
           f"{datetime.now(IST).strftime('%d-%b-%Y %H:%M IST')}")

    log.info(f"  ALERT: [{kind}] {name} | {interval} | {old_q} -> {new_q}")
    send_whatsapp(msg)
    
    if TELEGRAM_TOKEN:
        try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        except: pass
    try: requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode("utf-8"), headers={"Title": f"Alert | {name}", "Priority": "high", "Tags": "chart_increasing"}, timeout=10)
    except: pass

# ── SCANNER ENGINE ────────────────────────────────────────────────────────────
def is_market_hours(): return MARKET_OPEN <= datetime.now(IST).time() <= MARKET_CLOSE

def run_scan():
    log.info("-" * 55)
    log.info(f"SCAN: {datetime.now(IST).strftime('%d-%b-%Y %H:%M IST')}")
    universe, state, changes = get_universe(), load_state(), 0
    live_prices = get_live_market_snapshot()
    if not live_prices: return

    for sector in SECTORS:
        bench_nse = NSE_INDICES.get(sector)
        if not bench_nse: continue
        for interval in ["1wk", "1mo"]:
            key = f"sector|{sector}|{interval}"
            data = scan_pair(bench_nse, NSE_INDICES["CNX50"], interval, live_prices, is_stock=False)
            if not data: continue
            old_q = state.get(key, {}).get("quadrant")
            if old_q and old_q != data["quadrant"]:
                fire_alert("sector", sector, "CNX 50", interval, old_q, data["quadrant"], data)
                changes += 1
            state[key] = data

    for index_name, symbols in universe.items():
        bench_nse = NSE_INDICES.get(index_name)
        if not bench_nse: continue
        for nse_symbol in symbols:
            for interval in ["1wk", "1mo"]:
                key = f"stock|{nse_symbol}|{index_name}|{interval}"
                data = scan_pair(nse_symbol, bench_nse, interval, live_prices, is_stock=True)
                if not data: continue
                old_q = state.get(key, {}).get("quadrant")
                if old_q and old_q != data["quadrant"]:
                    fire_alert("stock", nse_symbol, index_name, interval, old_q, data["quadrant"], data)
                    changes += 1
                state[key] = data

    save_state(state)
    log.info(f"DONE - {changes} alert(s) triggered")

# ── BACKGROUND THREAD ─────────────────────────────────────────────────────────
def scanner_loop():
    log.info("Background RRG Scanner Started...")
    run_scan()
    while True:
        interval = SCAN_INTERVAL_MARKET if is_market_hours() else SCAN_INTERVAL_OFF
        log.info(f"Next scan in {interval}m...")
        time.sleep(interval * 60)
        run_scan()

# ── FLASK WEB SERVER ──────────────────────────────────────────────────────────
app = Flask(__name__)

@app.route('/')
def keep_alive():
    return f"RRG Screener is Online. Last ping: {datetime.now(IST).strftime('%H:%M:%S IST')}"

if __name__ == "__main__":
    log.info("=" * 55)
    log.info("RRG SCREENER v6 - Web Service Edition")
    log.info("=" * 55)
    
    # 1. Start the infinite scanning loop in a background thread
    t = threading.Thread(target=scanner_loop, daemon=True)
    t.start()
    
    # 2. Start the Flask web server on the main thread (Required by Render)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
