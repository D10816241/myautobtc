const API_BASE_URL = window.location.origin;
let username, password;

function setCredentials() {
    username = prompt("請輸入用戶名:");
    password = prompt("請輸入密碼:");
}

async function fetchWithAuth(url, options = {}) {
    if (!username || !password) {
        setCredentials();
    }
    const headers = new Headers(options.headers || {});
    headers.set('Authorization', 'Basic ' + btoa(username + ":" + password));
    const response = await fetch(url, { ...options, headers });
    if (response.status === 401) {
        alert("認證失敗，請重新輸入憑證");
        setCredentials();
        return fetchWithAuth(url, options);
    }
    return response;
}

async function fetchDashboardData() {
    try {
        const response = await fetchWithAuth(`${API_BASE_URL}/api/dashboard`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        updateDashboard(data);
        updateParamsForm(data.trading_params);
    } catch (error) {
        console.error('Error fetching data:', error);
        setErrorMessage(`獲取數據失敗: ${error.message}`);
    }
}

function updateDashboard(data) {
    updateElement('current-price', data.current_price, (value) => `$${value.toFixed(2)}`);
    updateElement('total-balance', data.total_balance, (value) => value.toFixed(2));
    updateElement('free-balance', data.free_balance, (value) => value.toFixed(2));
    updateElement('pnl', data.pnl, (value) => value.toFixed(2));
    updateElement('sma', data.sma, (value) => value.toFixed(2));
    updateElement('rsi', data.rsi, (value) => value.toFixed(2));
    updateElement('bb-upper', data.bb_upper, (value) => value.toFixed(2));
    updateElement('bb-middle', data.bb_middle, (value) => value.toFixed(2));
    updateElement('bb-lower', data.bb_lower, (value) => value.toFixed(2));
    updateElement('grid-step', data.grid_step, (value) => value.toFixed(4));
    updateElement('open-orders', data.open_orders);
    updateElement('trading-status', data.trading_active, (value) => value ? '活躍' : '已停止');
    updateElement('auto-trading-status', data.auto_trading_active, (value) => value ? '開啟' : '關閉');
    updateElement('volatility', data.volatility, (value) => `${(value * 100).toFixed(2)}%`);
}

function updateParamsForm(params) {
    for (const [key, value] of Object.entries(params)) {
        const input = document.getElementById(key);
        if (input) {
            input.value = value;
        }
    }
}

function updateElement(id, value, formatter = (v) => v) {
    const element = document.getElementById(id);
    if (element) {
        element.textContent = value != null ? formatter(value) : 'N/A';
    } else {
        console.warn(`Element with id '${id}' not found`);
    }
}

function setErrorMessage(message) {
    const errorElement = document.getElementById('error-message');
    if (errorElement) {
        errorElement.textContent = message;
    } else {
        console.error('Error message element not found:', message);
    }
}

async function toggleTrading() {
    try {
        const response = await fetchWithAuth(`${API_BASE_URL}/api/toggle_trading`, { method: 'POST' });
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        updateElement('trading-status', data.trading_active, (value) => value ? '活躍' : '已停止');
        alert(data.trading_active ? '交易已啟動' : '交易已停止');
    } catch (error) {
        console.error('Error toggling trading:', error);
        setErrorMessage(`切換交易狀態失敗: ${error.message}`);
    }
}

async function toggleAutoTrading() {
    try {
        const response = await fetchWithAuth(`${API_BASE_URL}/api/toggle_auto_trading`, { method: 'POST' });
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        updateElement('auto-trading-status', data.auto_trading_active, (value) => value ? '開啟' : '關閉');
        alert(data.auto_trading_active ? '自動交易已啟動' : '自動交易已停止');
    } catch (error) {
        console.error('Error toggling auto trading:', error);
        setErrorMessage(`切換自動交易狀態失敗: ${error.message}`);
    }
}

async function executeTrade() {
    try {
        const response = await fetchWithAuth(`${API_BASE_URL}/api/execute_trade`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        alert(data.message);
        fetchDashboardData();  // 重新加載數據以顯示最新狀態
    } catch (error) {
        console.error('Error executing trade:', error);
        setErrorMessage(`執行交易失敗: ${error.message}`);
    }
}

async function updateParams(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    const params = Object.fromEntries(formData.entries());
    
    try {
        const response = await fetchWithAuth(`${API_BASE_URL}/api/update_params`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(params),
        });
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        alert('參數更新成功');
        updateParamsForm(data.new_params);
    } catch (error) {
        console.error('Error updating parameters:', error);
        setErrorMessage(`更新參數失敗: ${error.message}`);
    }
}

// 初始化頁面
document.addEventListener('DOMContentLoaded', function() {
    fetchDashboardData();
    setInterval(fetchDashboardData, 60000);  // 每分鐘更新一次數據

    document.getElementById('toggle-trading').addEventListener('click', toggleTrading);
    document.getElementById('toggle-auto-trading').addEventListener('click', toggleAutoTrading);
    document.getElementById('execute-trade').addEventListener('click', executeTrade);
    document.getElementById('paramsForm').addEventListener('submit', updateParams);
});