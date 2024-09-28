from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import ccxt
import os
from dotenv import load_dotenv
import logging
from functools import wraps
import pandas as pd
import numpy as np
from ta.trend import SMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands
import time
import threading

# 加載 .env 文件中的環境變量
load_dotenv()

app = Flask(__name__)
CORS(app)

# 配置日誌，只記錄錯誤訊息
logging.basicConfig(level=logging.ERROR)

# 從環境變量中獲取配置
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY')
BINANCE_SECRET_KEY = os.getenv('BINANCE_SECRET_KEY')
SYMBOL = os.getenv('SYMBOL', 'BTC/USDT')
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'password')

# 交易參數
trading_params = {
    'INITIAL_CAPITAL': 500,
    'GRID_NUMBER': 4,
    'VOLATILITY_PERIOD': 10,
    'MAX_POSITION_SIZE': 275,
    'STOP_LOSS_THRESHOLD': 0.85,
    'MAX_OPEN_ORDERS': 10,
    'AUTO_TRADE_INTERVAL': 60  # 自動交易間隔（秒）
}

# 初始化幣安交易所
exchange = ccxt.binance({
    'apiKey': BINANCE_API_KEY,
    'secret': BINANCE_SECRET_KEY,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future'
    }
})

# 全局變量
trading_active = True
auto_trading_active = False
last_grid_step = 0

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return decorated

def check_auth(username, password):
    return username == ADMIN_USERNAME and password == ADMIN_PASSWORD

def get_historical_data():
    try:
        ohlcv = exchange.fetch_ohlcv(SYMBOL, '1h', limit=100, params={'market': 'future'})
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df['close']
    except Exception as e:
        app.logger.error(f"Error fetching historical data: {str(e)}")
        return None

def calculate_indicators(close):
    sma_indicator = SMAIndicator(close=close, window=20)
    rsi_indicator = RSIIndicator(close=close, window=14)
    bb_indicator = BollingerBands(close=close, window=20, window_dev=2)

    sma = sma_indicator.sma_indicator().iloc[-1]
    rsi = rsi_indicator.rsi().iloc[-1]
    bb_upper = bb_indicator.bollinger_hband().iloc[-1]
    bb_middle = bb_indicator.bollinger_mavg().iloc[-1]
    bb_lower = bb_indicator.bollinger_lband().iloc[-1]

    return sma, rsi, bb_upper, bb_middle, bb_lower

def calculate_position_size(current_price):
    balance = exchange.fetch_balance()
    available_balance = balance['free']['USDT']
    position_size = min(available_balance * 0.15, trading_params['MAX_POSITION_SIZE'] / current_price)
    return position_size

def get_open_orders():
    return exchange.fetch_open_orders(SYMBOL)

def cancel_old_orders(open_orders):
    current_time = time.time() * 1000
    for order in open_orders:
        if current_time - order['timestamp'] > 24 * 60 * 60 * 1000:
            exchange.cancel_order(order['id'], SYMBOL)

def place_grid_orders(base_price, grid_step):
    global last_grid_step
    open_orders = get_open_orders()
    
    if len(open_orders) >= trading_params['MAX_OPEN_ORDERS']:
        cancel_old_orders(open_orders)
        open_orders = get_open_orders()
    
    available_order_slots = trading_params['MAX_OPEN_ORDERS'] - len(open_orders)
    
    position_size = calculate_position_size(base_price)
    for i in range(-trading_params['GRID_NUMBER'] // 2, trading_params['GRID_NUMBER'] // 2 + 1):
        if available_order_slots <= 0:
            break
        price = base_price * (1 + i * grid_step)
        try:
            if i < 0:
                exchange.create_limit_buy_order(SYMBOL, position_size, price)
            elif i > 0:
                exchange.create_limit_sell_order(SYMBOL, position_size, price)
            available_order_slots -= 1
        except ccxt.ExchangeError as e:
            app.logger.error(f"Order placement error: {str(e)}")
            if "Reach max open order limit" in str(e):
                break
    
    last_grid_step = grid_step

def adjust_grid_step(current_price, volatility):
    return 0.006 * (1 + volatility)

def calculate_pnl():
    balance = exchange.fetch_balance()
    total_balance = balance['total']['USDT']
    pnl = total_balance - trading_params['INITIAL_CAPITAL']
    return pnl, total_balance

def check_stop_loss(total_balance):
    return total_balance < trading_params['INITIAL_CAPITAL'] * trading_params['STOP_LOSS_THRESHOLD']

def auto_trade():
    global auto_trading_active
    while auto_trading_active:
        try:
            execute_trade_logic()
        except Exception as e:
            app.logger.error(f"Error in auto trade: {str(e)}")
        time.sleep(trading_params['AUTO_TRADE_INTERVAL'])

def execute_trade_logic():
    global trading_active
    if not trading_active:
        return

    closes = get_historical_data()
    if closes is None or len(closes) == 0:
        raise Exception("Unable to fetch historical data")
    
    current_price = closes.iloc[-1]
    volatility = closes.pct_change().rolling(trading_params['VOLATILITY_PERIOD']).std().iloc[-1]
    
    sma, rsi, bb_upper, bb_middle, bb_lower = calculate_indicators(closes)
    
    pnl, total_balance = calculate_pnl()
    
    if check_stop_loss(total_balance):
        trading_active = False
        auto_trading_active = False
        return
    
    grid_step = adjust_grid_step(current_price, volatility)
    
    if current_price < bb_lower and rsi < 30:
        place_grid_orders(current_price, grid_step * 0.8)
    elif current_price > bb_upper and rsi > 70:
        place_grid_orders(current_price, grid_step * 1.2)
    else:
        place_grid_orders(current_price, grid_step)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/dashboard')
@requires_auth
def dashboard():
    try:
        closes = get_historical_data()
        if closes is None or len(closes) == 0:
            raise Exception("Unable to fetch historical data")
        
        current_price = closes.iloc[-1]
        volatility = closes.pct_change().rolling(trading_params['VOLATILITY_PERIOD']).std().iloc[-1]
        
        sma, rsi, bb_upper, bb_middle, bb_lower = calculate_indicators(closes)
        
        pnl, total_balance = calculate_pnl()
        
        open_orders = get_open_orders()
        
        balance = exchange.fetch_balance()
        free_balance = balance['free']['USDT']
        
        data = {
            "current_price": current_price,
            "total_balance": total_balance,
            "free_balance": free_balance,
            "pnl": pnl,
            "sma": sma,
            "rsi": rsi,
            "bb_upper": bb_upper,
            "bb_middle": bb_middle,
            "bb_lower": bb_lower,
            "grid_step": last_grid_step,
            "open_orders": len(open_orders),
            "trading_active": trading_active,
            "auto_trading_active": auto_trading_active,
            "volatility": volatility,
            "trading_params": trading_params
        }
        return jsonify(data)
    except Exception as e:
        app.logger.error(f"Error in dashboard route: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/toggle_trading', methods=['POST'])
@requires_auth
def toggle_trading():
    global trading_active
    trading_active = not trading_active
    return jsonify({"trading_active": trading_active})

@app.route('/api/toggle_auto_trading', methods=['POST'])
@requires_auth
def toggle_auto_trading():
    global auto_trading_active
    auto_trading_active = not auto_trading_active
    if auto_trading_active:
        threading.Thread(target=auto_trade, daemon=True).start()
    return jsonify({"auto_trading_active": auto_trading_active})

@app.route('/api/execute_trade')
@requires_auth
def execute_trade():
    try:
        execute_trade_logic()
        return jsonify({"message": "Trade executed successfully"}), 200
    except Exception as e:
        app.logger.error(f"Error executing trade: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/update_params', methods=['POST'])
@requires_auth
def update_params():
    global trading_params
    try:
        new_params = request.json
        for key, value in new_params.items():
            if key in trading_params:
                trading_params[key] = float(value)
        return jsonify({"message": "Parameters updated successfully", "new_params": trading_params}), 200
    except Exception as e:
        app.logger.error(f"Error updating parameters: {str(e)}")
        return jsonify({"error": str(e)}), 400

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=8080)