# Trade Platform - FastAPI Microservices Demo

A simple trading platform with 4 microservices demonstrating order processing with detailed JSON logging.

## Services

- **Orchestrator** (8000) - Coordinates order flow
- **Trade Service** (8001) - Validates trades
- **Pricing & PnL** (8002) - Price calculations
- **Risk Service** (8003) - Risk assessment

## Quick Start

```powershell
# Start all services
.\start-all-services.ps1

# Or manually in separate terminals
uvicorn orchestrator.src.app:app --host 0.0.0.0 --port 8000
uvicorn trade_service.src.app:app --host 0.0.0.0 --port 8001
uvicorn pricing_pnl_service.src.app:app --host 0.0.0.0 --port 8002
uvicorn risk_service.src.app:app --host 0.0.0.0 --port 8003
```

**Swagger UI:** http://localhost:8000/docs

## API Examples

### 1. ✅ Success Scenario

```bash
curl -X POST "http://localhost:8000/orders" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "AAPL",
    "quantity": 100,
    "order_type": "BUY",
    "scenario": "success"
  }'
```

**Response:**
```json
{
  "order_id": "abc-123",
  "status": "EXECUTED",
  "message": "Order executed successfully",
  "trace_id": "xyz-789",
  "details": {
    "execution": { "status": "EXECUTED", "price": 175.50 },
    "pricing": { "total_cost": 17550.0, "estimated_pnl": -1050.0 },
    "risk": { "risk_level": "LOW", "approved": true }
  }
}
```

### 2. ⏰ Market Closed

```bash
curl -X POST "http://localhost:8000/orders" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "GOOGL",
    "quantity": 50,
    "order_type": "BUY",
    "scenario": "market_closed"
  }'
```

**Response:**
```json
{
  "order_id": "def-456",
  "status": "REJECTED",
  "message": "Market is currently closed. Trading hours: 9:00 AM - 4:00 PM",
  "trace_id": "xyz-790"
}
```

### 3. 🔴 Service Error (External API Failure)

```bash
curl -X POST "http://localhost:8000/orders" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "MSFT",
    "quantity": 200,
    "order_type": "SELL",
    "scenario": "service_error"
  }'
```

**Response:**
```json
{
  "detail": "Market data service unavailable. Unable to fetch current price for MSFT from NASDAQ Market Data API. The external data provider is experiencing connectivity issues. Please retry in a few moments."
}
```

### 4. 🧮 Calculation Error (Mismatch Detected)

```bash
curl -X POST "http://localhost:8000/orders" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "NVDA",
    "quantity": 100,
    "order_type": "BUY",
    "scenario": "calculation_error"
  }'
```

**Response:**
```json
{
  "detail": "Pricing calculation error detected: Expected $49560.00 but calculated $48588.80. Discrepancy of $971.20 exceeds acceptable tolerance. Please retry or contact support."
}
```

## Scenarios

| Scenario | Description | Demonstrates |
|----------|-------------|--------------|
| `success` | Normal order execution | Happy path flow |
| `market_closed` | Trading outside hours | Business rule validation |
| `service_error` | External API unavailable | External dependency failure |
| `calculation_error` | Price calculation mismatch | Data integrity checks |

**Note:** Omit `scenario` field for default success behavior.

## Logging

All services generate JSON logs in `logs/` directories with Splunk-style formatting:
- `orchestrator/logs/orchestrator.log`
- `trade_service/logs/trade_service.log`
- `pricing_pnl_service/logs/pricing_pnl_service.log`
- `risk_service/logs/risk_service.log`

Each log entry includes `trace_id` for distributed tracing across services.

## Tech Stack

- Python 3.9+
- FastAPI 0.109.0
- Uvicorn 0.27.0
- Pydantic 2.5.3

---
