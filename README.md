# Trade Platform - Simple Demo

A simple trading platform with 4 microservices that demonstrates order processing scenarios.

## 🏗️ Services

1. **Orchestrator** (Port 8000) - Main entry point, coordinates all services
2. **Trade Service** (Port 8001) - Validates and executes trades
3. **Pricing & PnL Service** (Port 8002) - Calculates prices and profit/loss
4. **Risk Service** (Port 8003) - Assesses trading risk

## 🚀 How to Run

### Step 1: Install Dependencies

```powershell
# In each service folder, install requirements
cd orchestrator
pip install -r requirements.txt

cd ..\trade_service
pip install -r requirements.txt

cd ..\pricing_pnl_service
pip install -r requirements.txt

cd ..\risk_service
pip install -r requirements.txt
```

### Step 2: Start Services (Open 4 terminals)

**Terminal 1 - Trade Service:**
```powershell
cd trade_service\src
python app.py
```

**Terminal 2 - Pricing & PnL Service:**
```powershell
cd pricing_pnl_service\src
python app.py
```

**Terminal 3 - Risk Service:**
```powershell
cd risk_service\src
python app.py
```

**Terminal 4 - Orchestrator:**
```powershell
cd orchestrator\src
python app.py
```

### Step 3: Access Swagger UI

Open your browser: **http://localhost:8000/docs**

## 📊 Test Scenarios

All scenarios use the same endpoint: `POST /orders` with query parameters

### 1. ✅ Successful Order

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/orders?success=true" -Method POST -Body '{"symbol":"AAPL","quantity":50,"order_type":"BUY"}' -ContentType "application/json"
```

**Or in Swagger:** Try `/orders` with `success=true`

### 2. ⏰ Market Closed

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/orders?market_closed=true" -Method POST -Body '{"symbol":"AAPL","quantity":50,"order_type":"BUY"}' -ContentType "application/json"
```

**Or in Swagger:** Try `/orders` with `market_closed=true`

### 3. 🔴 Service Error

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/orders?service_error=true" -Method POST -Body '{"symbol":"AAPL","quantity":100,"order_type":"BUY"}' -ContentType "application/json"
```

**Or in Swagger:** Try `/orders` with `service_error=true`

### 4. 🧮 Calculation Error

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/orders?calculation_error=true" -Method POST -Body '{"symbol":"INVALID","quantity":75,"order_type":"BUY"}' -ContentType "application/json"
```

**Or in Swagger:** Try `/orders` with `calculation_error=true`

## 📝 Query Parameters

Use these on the `/orders` endpoint:

- `?success=true` - Normal successful order (default)
- `?market_closed=true` - Simulates market closed
- `?service_error=true` - Simulates service failure
- `?calculation_error=true` - Simulates pricing error

**Example:** `/orders?market_closed=true&symbol=AAPL`

## 🔍 Viewing Logs

Logs are generated in each service's `logs/` folder:

```
orchestrator/logs/orchestrator.log
trade_service/logs/trade_service.log
pricing_pnl_service/logs/pricing_pnl_service.log
risk_service/logs/risk_service.log
```

Each log entry includes a `trace_id` to track requests across services.

## 📋 What Each Service Does

### Orchestrator (Port 8000)
- Receives order from client
- Calls other services in sequence:
  1. Trade Service → validate
  2. Pricing Service → get price
  3. Risk Service → assess risk
  4. Trade Service → execute
- Returns final result

### Trade Service (Port 8001)
- Validates: market hours, symbol, quantity
- Executes trade if approved
- Stores trade records

### Pricing & PnL Service (Port 8002)
- Gets current market price
- Calculates estimated profit/loss
- Supports symbols: AAPL, GOOGL, MSFT, AMZN, TSLA, META, NVDA

### Risk Service (Port 8003)
- Calculates risk score (0-100)
- Considers: position size, PnL, quantity, volatility
- Approves LOW/MEDIUM risk, rejects HIGH risk

## 🎯 Quick Demo in Swagger

1. Open http://localhost:8000/docs
2. Click on `POST /orders`
3. Click "Try it out"
4. Keep the default body
5. Change query parameters:
   - Set `market_closed` to `true`
   - Click "Execute"
6. See the rejection response
7. Try with different combinations!

## 🛠️ Technology

- **Python 3.11+**
- **FastAPI** - Modern web framework
- **Uvicorn** - ASGI server
- **No Docker** - Just simple Python apps

## 📱 All Services Have Swagger

- Orchestrator: http://localhost:8000/docs
- Trade: http://localhost:8001/docs
- Pricing: http://localhost:8002/docs
- Risk: http://localhost:8003/docs

---

**That's it! Simple and straightforward. 🚀**
