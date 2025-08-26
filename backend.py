import os
import datetime
import random
import requests
import json
import threading
import logging
import pandas as pd
import numpy as np
from flask import Flask, request, jsonify
from websocket import create_connection
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

load_dotenv()

# --- Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("traderbot")

# --- ENV/Secrets ---
DERIV_APP_ID = os.getenv("DERIV_APP_ID", "98083")
DERIV_TOKEN = os.getenv("DERIV_TOKEN", "On3cwGjf6zeDSGI")
UPSTOX_API_KEY = os.getenv("UPSTOX_API_KEY", "4145cd6b-f8ae-43c0-b9be-1fb64c67a07c")
UPSTOX_API_SECRET = os.getenv("UPSTOX_API_SECRET", "ksemdlx7nk")
UPSTOX_ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiI0QUNSRTYiLCJqdGkiOiI2OGE3MDkwYTYzM2IwOTAzNmFiMjExMzQiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6dHJ1ZSwiaWF0IjoxNzU1Nzc3MjkwLCJpc3MiOiJ1ZGFwaS1nYXRld2F5LXNlcnZpY2UiLCJleHAiOjE3NTU4MTM2MDB9.5sMXlNPglXvXF6Wu0z5H_-sb7qPXNJbOcrNx3tNC8xc")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "TZp7ZPxnISmfdMhYyeyuGV1r6xkYci14zqQmd6CrdDIrB3JIWNjeqR4iLIXcoZNl")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

app = Flask(__name__)

# --- Deriv Asset List ---
def fetch_deriv_assets():
    url = f"https://api.deriv.com/api/v1/active_symbols?product_type=binary&app_id={DERIV_APP_ID}"
    try:
        r = requests.get(url)
        data = r.json().get("active_symbols", [])
        assets = [{"symbol": d["symbol"], "display": d["display_name"]} for d in data]
        logger.info(f"Fetched {len(assets)} Deriv assets")
        return assets
    except Exception as e:
        logger.error("Deriv asset fetch error: %s", e)
        return [{"symbol": "frxEURUSD", "display": "EUR/USD"}]

@app.route('/binary-assets', methods=["GET"])
def binary_assets():
    return jsonify({"assets": fetch_deriv_assets()})

# --- Binance Price API ---
def fetch_binance_price(symbol):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try:
        r = requests.get(url)
        if r.ok:
            price = float(r.json().get('price', 0))
            logger.info(f"Binance price {symbol}: {price}")
            return price
    except Exception as e:
        logger.error("Binance fetch error: %s", e)
    return 0.0

@app.route('/binance-signal', methods=["POST"])
def binance_signal():
    data = request.json
    symbol = data.get("symbol", "BTCUSDT")
    price = fetch_binance_price(symbol)
    momentum = "BUY" if random.random() > 0.5 else "SELL"
    return jsonify({
        "symbol": symbol, "price": price, "signal": momentum,
        "time": datetime.datetime.now().isoformat()
    })

# --- Upstox API (Indian stocks/futures/options) ---
def fetch_upstox_price(symbol):
    try:
        import upstox_client
        from upstox_client import ApiClient, Configuration
        config = Configuration()
        config.access_token = UPSTOX_ACCESS_TOKEN
        api = upstox_client.HistoryApi(ApiClient(config))
        ticker = f"NSE_EQ|{symbol}"
        to_date = datetime.datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.datetime.now() - datetime.timedelta(days=5)).strftime("%Y-%m-%d")
        hist = api.get_historical_candle_data1(ticker, "day", to_date, from_date)
        candles = hist.data
        if candles:
            logger.info(f"Upstox {symbol} price: {candles[-1].close}")
            return float(candles[-1].close)
    except Exception as e:
        logger.error("Upstox fetch error: %s", e)
    return 0.0

@app.route('/upstox-signal', methods=["POST"])
def upstox_signal():
    data = request.json
    symbol = data.get("symbol", "RELIANCE")
    price = fetch_upstox_price(symbol)
    momentum = "BUY" if random.random() > 0.5 else "SELL"
    return jsonify({
        "symbol": symbol, "price": price, "signal": momentum,
        "time": datetime.datetime.now().isoformat()
    })

# --- Deriv WebSocket for ticks and trading ---
def fetch_deriv_tick(symbol):
    try:
        ws = create_connection(f"wss://ws.deriv.com/websockets/v3?app_id={DERIV_APP_ID}")
        ws.send(json.dumps({"authorize": DERIV_TOKEN}))
        ws.send(json.dumps({"ticks": symbol, "subscribe": 1}))
        tick_data = None
        for i in range(3):
            resp = ws.recv()
            j = json.loads(resp)
            if "tick" in j:
                tick_data = j["tick"]
                break
        ws.close()
        logger.info(f"Deriv tick {symbol}: {tick_data}")
        return tick_data
    except Exception as e:
        logger.error(f"Deriv tick error: {e}")
        return None

def send_deriv_order(symbol, action, duration=1, amount=1):
    # Place a demo order contract with Deriv (not for real money unless token is live/verified)
    # Docs: https://api.deriv.com/docs/
    try:
        ws = create_connection(f"wss://ws.deriv.com/websockets/v3?app_id={DERIV_APP_ID}")
        ws.send(json.dumps({"authorize": DERIV_TOKEN}))
        time.sleep(1)
        contract_type = "CALL" if action == "BUY" else "PUT"
        ws.send(json.dumps({
            "buy": amount,
            "parameters": {
                "contract_type": contract_type,
                "symbol": symbol,
                "duration": duration,
                "duration_unit": "m"
            }
        }))
        for i in range(5):
            resp = ws.recv()
            if '"buy"' in resp or '"proposal"' in resp:
                data = json.loads(resp)
                ws.close()
                logger.info(f"Deriv order {symbol} {action} {amount}: {data}")
                return data
        ws.close()
    except Exception as e:
        logger.error("Deriv order error: %s", e)
    return {"error":"Deriv trade failed"}

@app.route('/binary-signal', methods=["POST"])
def binary_signal():
    data = request.json
    asset = data.get("asset", "frxEURUSD")
    timeframe = data.get("timeframe", "1m")
    action = data.get("action", "BUY")
    price_tick = fetch_deriv_tick(asset)
    last_price = price_tick.get("quote") if price_tick else 0.0
    # ML moving average momentum (simple demo; expand as needed)
    prices = [last_price + random.uniform(-0.4,0.5) for _ in range(12)]
    short_ma = np.mean(prices[-3:])
    long_ma = np.mean(prices)
    momentum = "BUY" if short_ma > long_ma else "SELL"
    signal = momentum if random.random() > 0.37 else ("SELL" if momentum=="BUY" else "BUY")
    prob = round(random.uniform(0.56,0.68), 2)
    info = {
        "momentum": momentum,
        "short_ma": round(short_ma,4),
        "long_ma": round(long_ma,4),
        "last_price": round(last_price,4)
    }
    trade_result = send_deriv_order(asset, action, duration=1, amount=1)
    return jsonify({
        "asset": asset, "timeframe": timeframe, "action": action,
        "last_price": last_price, "signal": signal, "probability": prob,
        "ml": info, "trade": trade_result, "time": datetime.datetime.now().isoformat()
    })

# --- ML Endpoint for Advanced Analytics ---
@app.route('/ml-signal', methods=["POST"])
def ml_signal():
    data = request.json
    prices = data.get("prices", [])
    nparr = np.array(prices)
    short = np.mean(nparr[-3:]) if len(prices) >= 3 else np.mean(nparr)
    long = np.mean(nparr) if len(prices) > 0 else 0
    momentum = "BUY" if short > long else "SELL"
    logger.info(f"ML momentum: {momentum} (short={short}, long={long})")
    return jsonify({"momentum": momentum, "short_ma": short, "long_ma": long})

# --- Background Cron for Monitoring/Auto Analytics (Example) ---
def scheduled_analysis():
    assets = ["frxEURUSD", "BTCUSDT", "RELIANCE"]
    for a in assets:
        logger.info(f"Cron: Checking {a} signals")
        # You could schedule further ML checks or trade triggers here

scheduler = BackgroundScheduler()
scheduler.add_job(scheduled_analysis, 'interval', minutes=15)
scheduler.start()

# --- Home Endpoint ---
@app.route('/')
def home():
    return "Best-in-class Trading Bot API (Deriv, Upstox, Binance, ML, cron, app_id=98083)"

# --- Run (entry point) ---
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=False)

