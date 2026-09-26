"""Local web dashboard and persistent OKX market collector (no trading)."""
import json
import logging
import re
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode

import pymysql
from flask import Flask, jsonify, send_from_directory, request
from main import parse_candle, utc_text
from macd_features import compute_features

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / '.local.json').read_text(encoding='utf-8'))
SYMBOLS = CONFIG['symbols']
STOP = threading.Event()
STATE = {'running': False, 'last_success_ms': None, 'error': None, 'cycles': 0}
LOCK = threading.Lock()
app = Flask(__name__)


def connect(database=True):
    return pymysql.connect(host=CONFIG['mysql_host'], port=CONFIG['mysql_port'],
                           user=CONFIG['mysql_user'], password=CONFIG['mysql_password'],
                           database=CONFIG['mysql_database'] if database else None,
                           charset='utf8mb4', autocommit=True, connect_timeout=5,
                           read_timeout=10, write_timeout=10,
                           cursorclass=pymysql.cursors.DictCursor)


def initialize():
    name = CONFIG['mysql_database']
    if not re.fullmatch(r'[a-zA-Z0-9_]+', name):
        raise ValueError('Invalid database name')
    with connect(False) as db, db.cursor() as cur:
        cur.execute(f'CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4')
    with connect() as db, db.cursor() as cur:
        cur.execute('''CREATE TABLE IF NOT EXISTS candles (
            symbol VARCHAR(32) NOT NULL, timestamp_ms BIGINT NOT NULL,
            open DECIMAL(30,12) NOT NULL, high DECIMAL(30,12) NOT NULL,
            low DECIMAL(30,12) NOT NULL, close DECIMAL(30,12) NOT NULL,
            volume DECIMAL(38,16) NOT NULL, volume_quote DECIMAL(38,16) NOT NULL,
            confirm TINYINT NOT NULL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY(symbol,timestamp_ms))''')
        cur.execute('''CREATE TABLE IF NOT EXISTS tickers (
            symbol VARCHAR(32) PRIMARY KEY, timestamp_ms BIGINT NOT NULL,
            last_price DECIMAL(30,12) NOT NULL, open_24h DECIMAL(30,12) NOT NULL,
            high_24h DECIMAL(30,12) NOT NULL, low_24h DECIMAL(30,12) NOT NULL,
            volume_quote_24h DECIMAL(38,16) NOT NULL)''')


def market(endpoint, **params):
    url = 'https://app.okx.com/api/v5/market/' + endpoint + '?' + urlencode(params)
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={'User-Agent': 'OKX-local-dashboard/1.0'}), timeout=12) as response:
                result = json.load(response)
            if result.get('code') != '0':
                raise RuntimeError(f"OKX: {result.get('code')} {result.get('msg')}")
            return result['data']
        except Exception:
            if attempt == 2:
                raise
            if STOP.wait(1 + attempt):
                return []


def store_candles(db, symbol, rows):
    values = []
    for raw in rows:
        c = parse_candle(raw)
        values.append((symbol, c['timestamp_ms'], c['open'], c['high'], c['low'], c['close'],
                       c['volume'], c['volume_quote'], int(c['confirm'])))
    if not values:
        return
    with db.cursor() as cur:
        # A completed candle can never be replaced by an older uncompleted cache entry.
        cur.executemany('''INSERT INTO candles
            (symbol,timestamp_ms,open,high,low,close,volume,volume_quote,confirm)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
            open=IF(confirm=0 OR VALUES(confirm)=1,VALUES(open),open),
            high=IF(confirm=0 OR VALUES(confirm)=1,VALUES(high),high),
            low=IF(confirm=0 OR VALUES(confirm)=1,VALUES(low),low),
            close=IF(confirm=0 OR VALUES(confirm)=1,VALUES(close),close),
            volume=IF(confirm=0 OR VALUES(confirm)=1,VALUES(volume),volume),
            volume_quote=IF(confirm=0 OR VALUES(confirm)=1,VALUES(volume_quote),volume_quote),
            confirm=GREATEST(confirm,VALUES(confirm))''', values)


def sync_symbol(db, symbol):
    with db.cursor() as cur:
        cur.execute('SELECT MAX(timestamp_ms) AS ts FROM candles WHERE symbol=%s AND confirm=1', (symbol,))
        last = cur.fetchone()['ts']
    cutoff = int(last) if last is not None else (int(time.time()) // 60 - 1440) * 60000
    recent = market('candles', instId=symbol, bar='1m', limit=300)
    store_candles(db, symbol, recent)
    if recent and min(int(r[0]) for r in recent) > cutoff:
        cursor = min(int(r[0]) for r in recent)
        while not STOP.is_set() and cursor > cutoff:
            page = market('history-candles', instId=symbol, bar='1m', limit=300, after=cursor)
            if not page:
                raise RuntimeError(f'Historical backfill stopped for {symbol}')
            oldest = min(int(r[0]) for r in page)
            if oldest >= cursor:
                raise RuntimeError('Pagination did not advance')
            store_candles(db, symbol, [r for r in page if int(r[0]) >= cutoff])
            cursor = oldest
            STOP.wait(0.15)
    ticker = market('ticker', instId=symbol)
    if not ticker:
        raise RuntimeError(f'No ticker for {symbol}')
    t = ticker[0]
    with db.cursor() as cur:
        cur.execute('''INSERT INTO tickers VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE timestamp_ms=VALUES(timestamp_ms),last_price=VALUES(last_price),
            open_24h=VALUES(open_24h),high_24h=VALUES(high_24h),low_24h=VALUES(low_24h),
            volume_quote_24h=VALUES(volume_quote_24h)''',
            (symbol,t['ts'],t['last'],t['open24h'],t['high24h'],t['low24h'],t['volCcy24h']))


def collect():
    while not STOP.is_set():
        started = time.monotonic()
        try:
            with connect() as db:
                for symbol in SYMBOLS:
                    sync_symbol(db, symbol)
            with LOCK:
                STATE.update(running=True, last_success_ms=int(time.time()*1000), error=None,
                             cycles=STATE['cycles']+1)
        except Exception as exc:
            logging.exception('Collector cycle failed')
            with LOCK:
                STATE.update(running=False, error=f'{type(exc).__name__}: {exc}')
        STOP.wait(max(0.2, CONFIG['poll_seconds'] - (time.monotonic()-started)))


@app.get('/')
def index():
    return send_from_directory(ROOT / 'web', 'index.html')


@app.get('/api/dashboard')
def snapshot():
    symbol = request.args.get('symbol', SYMBOLS[0])
    if symbol not in SYMBOLS:
        return jsonify(error='Unknown symbol'), 400
    try:
        with connect() as db, db.cursor() as cur:
            cur.execute('SELECT * FROM tickers WHERE symbol=%s', (symbol,))
            ticker = cur.fetchone()
            cur.execute('SELECT * FROM candles WHERE symbol=%s ORDER BY timestamp_ms DESC LIMIT 600', (symbol,))
            candles = list(reversed(cur.fetchall()))
            cur.execute('SELECT COUNT(*) AS count FROM candles WHERE symbol=%s', (symbol,))
            count = cur.fetchone()['count']
        completed = []
        gaps = 0
        for row in candles:
            if not row['confirm']:
                continue
            if completed and row['timestamp_ms'] - completed[-1]['timestamp_ms'] != 60000:
                completed = []  # Only a contiguous final segment is eligible for indicators.
                gaps += 1
            completed.append({**row, 'datetime_utc': utc_text(row['timestamp_ms']), 'confirm': '1'})
        features = compute_features(completed) if completed else []
        by_time = {int(row['timestamp_ms']): row for row in features}
        visible = []
        for row in candles[-240:]:
            f = by_time.get(row['timestamp_ms'], {})
            visible.append({**{k: float(row[k]) for k in ('open','high','low','close','volume')},
                            'time': row['timestamp_ms'], 'confirmed': bool(row['confirm']),
                            **{k: f.get(k) for k in ('dif','dea','hist','zl_hist','hist_z','hist_slope_pct','hist_accel_pct')}})
        with LOCK:
            state = dict(STATE)
        return jsonify(symbol=symbol, symbols=SYMBOLS, candles=visible,
                       ticker={k: float(v) if k not in ('symbol','timestamp_ms') else v for k,v in ticker.items()} if ticker else None,
                       count=count, state=state, gaps=gaps, server_time_ms=int(time.time()*1000))
    except Exception:
        logging.exception('Dashboard query failed')
        return jsonify(error='Database query failed; see logs/dashboard.log'), 503


if __name__ == '__main__':
    (ROOT / 'logs').mkdir(exist_ok=True)
    logging.basicConfig(filename=ROOT / 'logs/dashboard.log', level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    initialize()
    threading.Thread(target=collect, daemon=True, name='market-collector').start()
    app.run(host='127.0.0.1', port=CONFIG['web_port'], threaded=True, use_reloader=False)
