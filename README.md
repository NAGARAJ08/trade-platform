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

### 1. ✅ Success (Normal Order)

```bash
curl -X POST "http://localhost:8000/orders" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "AAPL",
    "quantity": 100,
    "order_type": "BUY"
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

---

### 2. 🐛 Validation Bug (Negative Quantity)

```bash
curl -X POST "http://localhost:8000/orders" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "AAPL",
    "quantity": -50,
    "order_type": "BUY"
  }'
```

**Bug:** Validation missing negative check - allows negative quantities  
**Error Location:** `validate_quantity()` in trade_service  
**Logs Show:** "ANOMALY DETECTED - Negative quantity received"

---

### 3. 🧮 Calculation Error (Bulk Order Bug)

```bash
curl -X POST "http://localhost:8000/orders" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "NVDA",
    "quantity": 600,
    "order_type": "BUY"
  }'
```

**Bug:** Wrong discount multiplier (0.98) for orders > 500  
**Response:**
```json
{
  "detail": "Pricing calculation error: Expected $297360.00 but calculated $291412.80. Discrepancy of $5947.20 in bulk order pricing. System bug detected."
}
```
**Error Location:** Bulk pricing logic in pricing_service

---

### 4. 💥 Division By Zero (Unknown Symbol)

```bash
curl -X POST "http://localhost:8000/orders" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "XYZ",
    "quantity": 100,
    "order_type": "SELL"
  }'
```

**Bug:** `get_cost_basis()` returns 0 for unknown symbols → division by zero  
**Error Location:** `calculate_pnl()` in pricing_service line ~145  
**Stack Trace:** "ZeroDivisionError: division by zero"

---

### 5. 🔴 Null Pointer Exception (Large Order)

```bash
curl -X POST "http://localhost:8000/orders" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "TSLA",
    "quantity": 1500,
    "order_type": "BUY"
  }'
```

**Bug:** Missing null check when fetching historical data for quantity > 1000  
**Response:**
```json
{
  "detail": "Risk assessment failed: NullPointerException at line 156 while calculating volatility for TSLA with quantity 1500. Historical market data unavailable for large orders."
}
```
**Error Location:** `calculate_risk_score()` line 156 in risk_service

---

### 6. ⏰ Market Closed (Time-Based)

```bash
curl -X POST "http://localhost:8000/orders" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "GOOGL",
    "quantity": 50,
    "order_type": "BUY"
  }'
```

**Triggers:** Only outside 9:30 AM - 4:00 PM  
**Response:** "Market is currently closed. Trading hours: 9:30 AM - 4:00 PM"

---

## Bug Summary

| Input Condition | Bug Triggered | Service | Root Cause |
|----------------|---------------|---------|------------|
| `quantity < 0` | Validation bypass | Trade | Missing negative check |
| `quantity > 500` | Calculation error | Pricing | Wrong bulk discount multiplier |
| Unknown `symbol` | Division by zero | Pricing | Returns 0 cost basis |
| `quantity > 1000` | Null pointer | Risk | Missing null check for volatility data |
| Outside 9:30-4pm | Market closed | Trade | Time-based validation |

**All bugs are reproducible with the same input data.**

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

## Function Call Hierarchy

The codebase implements **realistic nested function calls** with up to **4 levels of depth** within services and **5 levels cross-service**.

### Call Statistics

| Service | Entry Functions | Internal Functions | Max Nesting Depth |
|---------|----------------|-------------------|------------------|
| **Trade Service** | 2 | 9 | 4 levels |
| **Pricing Service** | 1 | 6 | 3 levels |
| **Risk Service** | 1 | 7 | 3 levels |
| **Orchestrator** | 1 | 2 | 5 levels (cross-service) |

### Trade Service Call Tree

**Entry:** `validate_trade()` → Calls 7 functions, max depth 4 levels

```
validate_trade()
├── check_symbol_tradeable() → get_symbol_metadata()
├── is_market_open()
├── validate_order_requirements() → validate_account_balance()
├── normalize_quantity_to_lot_size() → get_symbol_metadata()
└── check_order_limits() → get_symbol_metadata()
```

### Pricing Service Call Tree

**Entry:** `calculate_pricing()` → Calls 5 functions, max depth 3 levels

```
calculate_pricing()
├── get_market_price()
├── calculate_total_cost()
└── calculate_estimated_pnl() → get_cost_basis()
```

### Risk Service Call Tree

**Entry:** `assess_risk()` → Calls 8 functions, max depth 3 levels

```
assess_risk()
├── validate_compliance_rules()
├── check_sector_limits()
├── assess_order_risk()
├── calculate_risk_score()
├── determine_risk_level()
└── get_recommendation()
```

### Orchestrator Cross-Service Cascade

**Entry:** `place_order()` → Triggers **5-level cascade** across services

```
place_order()
├── call_service() → Trade.validate_trade() [4 levels deep]
├── call_service() → Pricing.calculate_pricing() [3 levels deep]
├── call_service() → Risk.assess_risk() [3 levels deep]
└── call_service() → Trade.execute_trade()
```

### Reusable Functions

- `get_symbol_metadata()` - Called **3 times** (trade service)
- `get_trace_logger()` - Called by all entry points
- `call_service()` - Called **4 times** (orchestrator)

**Total Internal Functions:** 24 across all services

---
