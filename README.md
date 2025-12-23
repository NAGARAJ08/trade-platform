# Trade Platform 
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


```
1. POST /orders (orchestrator.py)
   └── place_order()
       │
       ├── STEP 1: Trade Validation
       │   └── POST /trades/validate (trade_service.py)
       │       └── validate_trade()
       │           ├── check_symbol_tradeable()
       │           │   └── get_symbol_metadata()
       │           ├── is_market_open()
       │           ├── validate_order_requirements()
       │           │   └── validate_account_balance()
       │           ├── normalize_quantity_to_lot_size()
       │           │   └── get_symbol_metadata()
       │           └── check_order_limits()
       │               └── get_symbol_metadata()
       │
       ├── STEP 1.5: Validation Price Snapshot (NEW)
       │   └── POST /pricing/calculate (pricing_pnl_service.py)
       │       └── calculate_pricing()
       │           ├── get_market_price()
       │           │   └── validate_price_components()
       │           │       └── check_price_range_validity() (Level 2)
       │           │           └── verify_market_conditions() (Level 3)
       │           ├── calculate_total_cost()
       │           │   └── validate_cost_breakdown() 
       │           │       ├── verify_fee_calculations() (Level 2)
       │           │       └── audit_commission_rate() (Level 3)
       │           └── calculate_estimated_pnl()
       │               └── get_cost_basis()
       │
       ├── STEP 2: Execution Pricing & PnL Calculation
       │   └── POST /pricing/calculate (pricing_pnl_service.py)
       │       └── calculate_pricing()
       │           ├── get_market_price() 
       │           │   └── validate_price_components() 
       │           │       └── check_price_range_validity() (Level 2)
       │           │           └── verify_market_conditions() (Level 3)
       │           ├── calculate_total_cost()
       │           │   └── validate_cost_breakdown() 
       │           │       ├── verify_fee_calculations() (Level 2)
       │           │       └── audit_commission_rate() (Level 3)
       │           └── calculate_estimated_pnl()
       │               └── get_cost_basis()
       │
       ├── STEP 3: Risk Assessment
       │   └── POST /risk/assess (risk_service.py)
       │       └── assess_risk()
       │           ├── validate_compliance_rules()
       │           ├── check_sector_limits() 
       │           ├── assess_order_risk()
       │           ├── [INLINE: Expected vs Actual PnL Check + Loss % Validation]
       │           ├── calculate_risk_score()
       │           │   ├── calculate_position_size_impact()
       │           │   ├── calculate_pnl_risk_factor()
       │           │   ├── assess_quantity_risk()
       │           │   ├── calculate_volatility_multiplier()
       │           │   ├── calculate_sector_risk_adjustment()
       │           │   └── normalize_risk_score()
       │           ├── determine_risk_level()
       │           └── get_recommendation()
       │
       └── STEP 4: Trade Execution
           └── POST /trades/execute (trade_service.py)
               └── execute_trade()

```

## Order Processing Flow - Business Logic Summary

Each function in the order flow performs a key business logic step:

- **place_order**: Orchestrates the entire order lifecycle, coordinating validation, pricing, risk, and execution.
- **validate_trade**: Checks if the order is allowed (symbol, market hours, requirements, limits).
- **check_symbol_tradeable**: Verifies the symbol is supported and tradeable on the exchange.
- **get_symbol_metadata**: Retrieves metadata (exchange, sector, lot size, max order) for the symbol.
- **is_market_open**: Ensures the order is placed during market hours.
- **validate_order_requirements**: Validates account balance (BUY) or holdings (SELL) and other business rules.
- **validate_account_balance**: Checks if the user has enough funds (BUY) or shares (SELL) to proceed.
- **normalize_quantity_to_lot_size**: Adjusts order quantity to match exchange lot size requirements.
- **check_order_limits**: Validates order quantity against symbol-specific and global limits.
- **calculate_pricing**: Computes market price, total cost, and estimated PnL for the order.
- **get_market_price**: Simulates real-time market price with ±2% variance.
- **validate_price_components**: Level 1 validation that ensures price data is complete and properly structured before processing.
- **check_price_range_validity**: Level 2 validation that verifies the current price falls within acceptable range of base price.
- **verify_market_conditions**: Level 3 validation that confirms market conditions are within acceptable parameters (price > 0, not suspiciously high).
- **calculate_total_cost**: Calculates all fees, commissions, and net cost/proceeds (includes fee for large SELL).
- **validate_cost_breakdown**: Level 1 validation that verifies cost components (commission, fees, base amount) are properly calculated.
- **verify_fee_calculations**: Level 2 validation that ensures fee amounts are accurate and within expected thresholds.
- **audit_commission_rate**: Level 3 validation that confirms commission rates match approved schedules and fee structures.
- **calculate_estimated_pnl**: Computes profit/loss based on cost basis and current price.
- **get_cost_basis**: Retrieves average purchase price for the symbol.
- **assess_risk**: Evaluates risk factors and compliance for the order.
- **validate_compliance_rules**: Checks regulatory rules (trade size, restricted stocks).
- **check_sector_limits**: Checks for sector exposure limits and triggers compliance delay for tech stocks.
- **assess_order_risk**: Scores order-specific risks (large position, selling at loss, etc.).
- **calculate_risk_score**: Aggregates all risk factors into a numeric risk score.
- **calculate_position_size_impact**: Calculates risk points (5-30) based on position value relative to account size.
- **calculate_pnl_risk_factor**: Calculates risk points (5-30) based on P&L characteristics (loss magnitude, profit potential).
- **assess_quantity_risk**: Calculates risk points (5-20) based on order size and execution complexity.
- **calculate_volatility_multiplier**: Applies volatility-based multiplier (1.0-2.5x) to risk score based on symbol's historical price swings.
- **calculate_sector_risk_adjustment**: Applies sector-specific risk multiplier (1.0-1.3x) for industry exposure (e.g., Technology 1.25x).
- **normalize_risk_score**: Caps risk score at 100 (maximum) and floors at 0 (minimum) to ensure consistent scale.
- **determine_risk_level**: Maps risk score to LOW, MEDIUM, or HIGH risk category.
- **get_recommendation**: Generates a human-readable risk recommendation for the order.
- **execute_trade**: Finalizes the order and records execution details.
---


## Test Scenarios (RCA Questions)
### 1. Why are my large SELL orders so expensive?
- **Inputs:**
```json
{
  "symbol": "NVDA",
  "quantity": 100,
  "order_type": "SELL"
}
```
```json
{
  "symbol": "NVDA",
  "quantity": 250,
  "order_type": "SELL"
}
```

### 2. Why did my order pass validation but fail at execution?
- **Input:**
```json
{
  "symbol": "AAPL",
  "quantity": 2850,
  "order_type": "BUY"
}
```

### 3. Why do tech stock orders take longer to process than non-tech stocks?
- **Inputs:**
```json
{
  "symbol": "TSLA",
  "quantity": 50,
  "order_type": "BUY"
}
```
```json
{
  "symbol": "NVDA",
  "quantity": 50,
  "order_type": "BUY"
}
```

### 4. Why did adding 1 share to my order change the risk score so much?
- **Inputs:**
```json
{
  "symbol": "AAPL",
  "quantity": 100,
  "order_type": "BUY"
}
```
```json
{
  "symbol": "AAPL",
  "quantity": 101,
  "order_type": "BUY"
}
```

### 5. Why did my order for 157 shares get normalized to 150?
- **Input:**
```json
{
  "symbol": "AAPL",
  "quantity": 157,
  "order_type": "BUY"
}
```

### 6. Why is my PnL negative for SELL orders when I should be making a profit?
- **Input:**
```json
{
  "symbol": "AAPL",
  "quantity": 100,
  "order_type": "SELL"
}
```

### 7. Why did my order get rejected for sector limits even though I haven't bought tech stocks before?
- **Input:**
```json
{
  "symbol": "NVDA",
  "quantity": 500,
  "order_type": "BUY"
}
```

### 8. Why does the price vary between validation and execution for the same order?
- **Input:**
```json
{
  "symbol": "AAPL",
  "quantity": 50,
  "order_type": "BUY"
}
```

### 9. Why is the SELL commission different for AAPL and TSLA for the same quantity?
- **Inputs:**
```json
{
  "symbol": "AAPL",
  "quantity": 250,
  "order_type": "SELL"
}
```
```json
{
  "symbol": "TSLA",
  "quantity": 250,
  "order_type": "SELL"
}
```

---

### 10. Why do both BUY and SELL orders fail for GME with market data error?
- **Inputs:**
```json
{
  "symbol": "GME",
  "quantity": 100,
  "order_type": "BUY"
}
```
```json
{
  "symbol": "GME",
  "quantity": 50,
  "order_type": "SELL"
}
```
- **Expected Output:** Both orders fail with 503 error "Market data feed unavailable"
- **Key Function:** `get_market_price()` in pricing_pnl_service (COMMON to both BUY and SELL)
- **RCA Goal:** Identify that both workflows fail at the same shared component
- **Trace Pattern:** Both traces show error in `get_market_price` with `error_type: market_data_unavailable`

---

### 11. Full Exception Stack Traces - Why does my large order fail with complete traceback?
- **Input:**
```json
{
  "symbol": "AAPL",
  "quantity": 5000,
  "order_type": "BUY"
}
```

- **Expected Behavior:**
  - Order requires $875,000 but account has only $500,000
  - Validation fails with insufficient balance error
  - **logger.exception()** captures COMPLETE Python stack trace

---

### 12. Deep Call Stack Validation - How do I trace nested function calls?
- **Input:**
```json
{
  "symbol": "AAPL",
  "quantity": 100,
  "order_type": "BUY"
}
```

- **Expected Behavior:**
  - Order succeeds, showing 3-level deep validation chains
  - Price validation: `validate_price_components` → `check_price_range_validity` → `verify_market_conditions`
  - Cost validation: `validate_cost_breakdown` → `verify_fee_calculations` → `audit_commission_rate`
---

### 13. Complex Multi-Step Risk Calculation - Why is my NVDA order scored as HIGH risk?
- **Input:**
```json
{
  "symbol": "NVDA",
  "quantity": 200,
  "order_type": "BUY"
}
```

- **Expected Behavior:**
  - Order triggers complex 5-step risk calculation
  - Base score: Position (20) + PnL (20) + Quantity (10) = 50
  - Volatility multiplier: 2.0x (NVDA high volatility) = 100
  - Sector adjustment: 1.25x (Technology/Semiconductors) = 125
  - Normalized to max 100
  - Final score: 100.0 = HIGH RISK

---

### 14. Expected vs Actual Validation - Why does MSFT show PnL mismatch?
- **Input:**
```json
{
  "symbol": "MSFT",
  "quantity": 100,
  "order_type": "SELL"
}
```

- **Expected Behavior:**
  - Current price: ~$378.90
  - Expected cost basis: $360.00
  - Expected PnL: (378.90 - 360.00) × 100 = $1,890.00
  - **BUG**: Pricing service uses $350.00 cost basis
  - Actual PnL calculated: (378.90 - 350.00) × 100 = $2,890.00
  - **Discrepancy detected: $1,000.00 difference!**
  - Risk service validates and REJECTS order
---

### 15. Common Function Error Analysis - Why do both BUY and SELL fail for GME?
- **Inputs:**
```json
// Test 1: BUY order
{
  "symbol": "GME",
  "quantity": 100,
  "order_type": "BUY"
}

// Test 2: SELL order
{
  "symbol": "GME",
  "quantity": 50,
  "order_type": "SELL"
}
```

- **Expected Behavior:**
  - **BOTH** orders fail at pricing stage
  - **SAME** error: "Market data feed unavailable"
  - **SAME** function: `get_market_price()`
  - **SAME** status code: 503
  - Proves common function affects both workflows