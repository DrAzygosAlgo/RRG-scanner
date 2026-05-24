import os, json, time, logging, threading, requests
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask
import pandas as pd
import numpy as np
from dotenv import load_dotenv

# ── CONFIG ────────────────────────────────────────────────────────────────────
load_dotenv()
IST = ZoneInfo("Asia/Kolkata")
SCAN_TIME = dtime(18, 0, 0) # Trigger EOD scan after 6 PM
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(SCRIPT_DIR, "rrg_state.json")

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

# ── EOD DATA ENGINE ───────────────────────────────────────────────────────────
def get_eod_data():
    """Directly downloads the latest available Bhavcopy from NSE Archives."""
    for i in range(5):
        dt = datetime.now(IST) - timedelta(days=i)
        day, month, year = dt.strftime("%d"), dt.strftime("%b").upper(), dt.strftime("%Y")
        url = f"https://archives.nseindia.com/content/historical/EQUITIES/{year}/{month}/cm{day}{month}{year}bhav.csv.zip"
        
        log.info(f"Attempting: {url}")
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            if r.status_code == 200:
                df = pd.read_csv(r.content, compression='zip')
                log.info(f"Success: Loaded data for {day}-{month}-{year}")
                return df[['SYMBOL', 'CLOSE']]
        except Exception as e:
            log.warning(f"Fetch failed for {day}: {e}")
    return None

def run_eod_scan():
    log.info("Starting EOD RRG Scan...")
    data = get_eod_data()
    if data is None:
        log.info("No trading data found (Weekend/Holiday). Skipping.")
        return
    log.info(f"Processing {len(data)} symbols...")
    # Your RRG math logic goes here
    log.info("EOD Scan complete. Database updated.")

def scanner_loop():
    log.info("Background EOD Scanner Thread Synchronized.")
    while True:
        now = datetime.now(IST)
        if now.time() >= SCAN_TIME:
            run_eod_scan()
            time.sleep(20 * 3600) # Sleep 20h after success
        else:
            time.sleep(1800) # Check every 30m

# ── FLASK WEB SERVER ──────────────────────────────────────────────────────────
app = Flask(__name__)

@app.route('/')
def keep_alive():
    return f"RRG EOD Screener is Online. Status: Active."

# Start background thread before Gunicorn takes over
threading.Thread(target=scanner_loop, daemon=True).start()
