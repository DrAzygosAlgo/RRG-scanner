"""
RRG SCREENER v7 - EOD Bhavcopy Edition
======================================
Data:     Official NSE Bhavcopy via 'nselib'
Strategy: Once-daily EOD update
"""
import sys, os, json, time, logging, warnings, threading
from io import StringIO
import numpy as np
import pandas as pd
import requests
# Ensure BOTH datetime and timedelta are imported
from datetime import datetime, time as dtime, timedelta 
from zoneinfo import ZoneInfo
from flask import Flask
from nselib import capital_market

# ── CONFIG ────────────────────────────────────────────────────────────────────
IST = ZoneInfo("Asia/Kolkata")
SCAN_TIME = dtime(18, 0, 0) # Run scan at 6 PM daily

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

# ── EOD DATA ENGINE ───────────────────────────────────────────────────────────
def get_eod_data():
    """Tries to download the bhavcopy for today; if it fails, steps back 1 day."""
    for i in range(5):  # Try today, then yesterday, then the day before...
        date_to_try = (datetime.now(IST) - timedelta(days=i)).strftime("%d-%m-%Y")
        try:
            log.info(f"Attempting to download Bhavcopy for {date_to_try}...")
            df = capital_market.bhav_copy_equities(date_to_try)
            if df is not None and not df.empty:
                log.info(f"Successfully downloaded data for {date_to_try}")
                return df[['SYMBOL', 'CLOSE']]
        except:
            continue
    log.error("Could not find any recent Bhavcopy data.")
    return None

# ── RRG ENGINE ────────────────────────────────────────────────────────────────
# You can keep your compute_rrg, get_quadrant, and get_angle functions here.
# The only difference is that you pass the DataFrame loaded from the CSV.

# ── SCANNER ───────────────────────────────────────────────────────────────────
def run_eod_scan():
    log.info("Running EOD RRG Scan...")
    data = get_eod_data()
    if data is None: return
    
    # Logic to update your RRG state using the EOD close prices
    log.info("EOD Scan complete. Database updated.")

def scanner_loop():
    while True:
        now = datetime.now(IST).time()
        # If it's past 6 PM, run the scan
        if now >= SCAN_TIME:
            run_eod_scan()
            # Sleep for 23 hours to avoid duplicate runs
            time.sleep(23 * 3600)
        else:
            time.sleep(600) # Check every 10 mins

# ── FLASK WEB SERVER (To keep Render alive) ──────────────────────────────────
app = Flask(__name__)
@app.route('/')
def keep_alive():
    return "RRG EOD Screener is Online."

if __name__ == "__main__":
    t = threading.Thread(target=scanner_loop, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
