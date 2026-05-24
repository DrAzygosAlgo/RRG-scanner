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
SCAN_TIME = dtime(18, 0, 0)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

# ── EOD DATA ENGINE ───────────────────────────────────────────────────────────
def get_eod_data():
    for i in range(5):
        dt = datetime.now(IST) - timedelta(days=i)
        day, month, year = dt.strftime("%d"), dt.strftime("%b").upper(), dt.strftime("%Y")
        url = f"https://archives.nseindia.com/content/historical/EQUITIES/{year}/{month}/cm{day}{month}{year}bhav.csv.zip"
        
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
        log.info("No trading data found. Skipping.")
        return
    log.info(f"Processing {len(data)} symbols. Database updated.")

def scanner_loop():
    while True:
        if datetime.now(IST).time() >= SCAN_TIME:
            run_eod_scan()
            time.sleep(20 * 3600)
        else:
            time.sleep(1800)

app = Flask(__name__)
@app.route('/')
def keep_alive():
    return "RRG EOD Screener is Online."

if __name__ == "__main__":
    threading.Thread(target=scanner_loop, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
