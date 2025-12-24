# Workflow Testing Guide

Complete payloads and function flows for all three trading workflows.

## Overview

Three distinct workflows for semantic search-based RCA:
1. **Retail Workflow** - Individual investors
2. **Institutional Workflow** - Portfolio managers, compliance checks
3. **Algorithmic Workflow** - High-frequency trading, speed optimized

---

## 1. RETAIL WORKFLOW (Original)

### Endpoint
```
POST http://localhost:8000/orders
```

### Payload
```json
{
  "symbol": "AAPL",
  "quantity": 100,
  "order_type": "BUY",
  "user_id": "user_12345"
}
```

### Complete Function Call Flow

```
Orchestrator (port 8000):
  place_order()
    ├─> generate_order_id()
    ├─> validate_input()
    │
    └─> TRADE SERVICE (port 8001) - POST /trades/validate
          validate_order()
            ├─> check_symbol_tradeable()
            ├─> validate_trade()
            ├─> check_trading_hours()
            └─> normalize_order()
    │
    └─> PRICING SERVICE (port 8002) - POST /pricing/calculate
          calculate_pricing()
            ├─> get_market_price()
            ├─> apply_commission()
            ├─> calculate_estimated_pnl()
            └─> calculate_fees()
    │
    └─> RISK SERVICE (port 8003) - POST /risk/assess
          assess_risk()
            ├─> calculate_risk_score()
            ├─> check_position_limits()
            └─> validate_account_balance()
    │
    └─> TRADE SERVICE (port 8001) - POST /trades/execute
          execute_trade()
            ├─> submit_to_exchange()
            ├─> record_trade()
            └─> update_portfolio()
```

### Unique Function Signatures (for semantic search)
- `validate_trade()`
- `check_trading_hours()`
- `apply_commission()`
- `calculate_fees()`
- `check_position_limits()`
- `validate_account_balance()`

---

## 2. INSTITUTIONAL WORKFLOW (NEW)

### Endpoint
```
POST http://localhost:8000/orders/institutional
```

### Payload
```json
{
  "symbol": "AAPL",
  "quantity": 5000,
  "order_type": "BUY",
  "portfolio_manager_id": "PM_789",
  "custodian_account": "CUST_12345"
}
```

### Complete Function Call Flow

```
Orchestrator (port 8000):
  place_institutional_order()  ⭐ UNIQUE
    ├─> generate_order_id()
    ├─> validate_input()
    │
    └─> TRADE SERVICE (port 8001) - POST /trades/validate-institutional  ⭐ UNIQUE
          validate_institutional_order()  ⭐ UNIQUE
            ├─> check_symbol_tradeable()
            ├─> institutional_compliance_check()  ⭐ UNIQUE (SEC Form 13F)
            ├─> check_portfolio_manager_approval()  ⭐ UNIQUE (PM approval)
            └─> verify_custodian_account()  ⭐ UNIQUE (Custodian verification)
    │
    └─> PRICING SERVICE (port 8002) - POST /pricing/calculate-institutional  ⭐ UNIQUE
          calculate_institutional_pricing()  ⭐ UNIQUE
            ├─> get_market_price()
            ├─> apply_volume_discount()  ⭐ UNIQUE (0.1-0.5% discount)
            ├─> calculate_estimated_pnl()
            └─> apply_institutional_commission()  (0.1% vs 0.5% retail)
    │
    └─> RISK SERVICE (port 8003) - POST /risk/assess-institutional  ⭐ UNIQUE
          assess_institutional_risk()  ⭐ UNIQUE
            ├─> calculate_risk_score()
            ├─> check_aggregate_exposure()  ⭐ UNIQUE (Cross-portfolio limits)
            └─> assess_regulatory_risk()  ⭐ UNIQUE (Form 13F/13D)
    │
    └─> TRADE SERVICE (port 8001) - POST /trades/execute
          execute_trade()
            ├─> submit_to_exchange()
            ├─> record_trade()
            └─> update_portfolio()
```

### Unique Function Signatures (for semantic search)
- `place_institutional_order()` ⭐
- `validate_institutional_order()` ⭐
- `institutional_compliance_check()` ⭐
- `check_portfolio_manager_approval()` ⭐
- `verify_custodian_account()` ⭐
- `apply_volume_discount()` ⭐
- `calculate_institutional_pricing()` ⭐
- `check_aggregate_exposure()` ⭐
- `assess_regulatory_risk()` ⭐
- `assess_institutional_risk()` ⭐

### Key Differences from Retail
- Higher quantity limits: 1M shares (vs 10K retail)
- Volume discounts: 0.1-0.5% based on quantity
- Lower commission: 0.1% (vs 0.5% retail)
- PM approval required for orders > 100K shares
- SEC Form 13F compliance validation
- Custodian account verification
- Aggregate exposure across portfolios (max 100K per symbol)

---

## 3. ALGORITHMIC WORKFLOW (NEW)

### Endpoint
```
POST http://localhost:8000/orders/algo
```

### Payload
```json
{
  "symbol": "AAPL",
  "quantity": 1000,
  "order_type": "BUY",
  "strategy_id": "MOMENTUM_v2"
}
```

### Complete Function Call Flow

```
Orchestrator (port 8000):
  place_algo_order()  ⭐ UNIQUE
    ├─> generate_order_id()
    ├─> validate_input()
    │
    └─> TRADE SERVICE (port 8001) - POST /trades/validate-algo  ⭐ UNIQUE
          validate_algo_order()  ⭐ UNIQUE
            ├─> validate_algo_credentials()  ⭐ UNIQUE (Strategy whitelist)
            ├─> check_circuit_breaker_limits()  ⭐ UNIQUE (Per-strategy limits)
            ├─> verify_strategy_limits()  ⭐ UNIQUE (Daily execution count)
            └─> check_symbol_tradeable()
    │
    └─> PRICING SERVICE (port 8002) - POST /pricing/algo-fast  ⭐ UNIQUE
          calculate_algo_pricing()  ⭐ UNIQUE
            ├─> fast_price_lookup()  (Cached prices, skip validation)
            └─> minimal_cost_calculation()  (0.01% commission)
    │
    └─> RISK SERVICE (port 8003) - POST /risk/pre-trade-check  ⭐ UNIQUE
          pre_trade_check()  ⭐ UNIQUE
            ├─> verify_pre_trade_risk()  ⭐ UNIQUE (10ms fast check)
            └─> check_strategy_correlation()  ⭐ UNIQUE (Multi-strategy risk)
    │
    └─> TRADE SERVICE (port 8001) - POST /trades/execute
          execute_trade()
            ├─> submit_to_exchange()
            ├─> record_trade()
            └─> update_portfolio()
```

### Unique Function Signatures (for semantic search)
- `place_algo_order()` ⭐
- `validate_algo_order()` ⭐
- `validate_algo_credentials()` ⭐
- `check_circuit_breaker_limits()` ⭐
- `verify_strategy_limits()` ⭐
- `calculate_algo_pricing()` ⭐
- `fast_price_lookup()` ⭐
- `pre_trade_check()` ⭐
- `verify_pre_trade_risk()` ⭐
- `check_strategy_correlation()` ⭐

### Key Differences from Retail
- Ultra-low latency: 50-100ms target (vs 1500ms retail)
- Strategy-based validation: MOMENTUM_v2, MEAN_REVERSION, ARBITRAGE_v3
- Circuit breaker limits: 3K-10K shares per strategy
- Daily execution limits: 150/500 orders per strategy
- Minimal commission: 0.01% (vs 0.5% retail)
- Skip P&L calculation for speed
- Fast cached pricing
- Lightweight risk checks (10ms)

---

## Testing Commands

### 1. Start All Services
```powershell
.\start-all-services.ps1
```

### 2. Test Retail Workflow
```powershell
$retailPayload = @{
    symbol = "AAPL"
    quantity = 100
    order_type = "BUY"
    user_id = "user_12345"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/orders" -Method Post -Body $retailPayload -ContentType "application/json"
```

### 3. Test Institutional Workflow
```powershell
$institutionalPayload = @{
    symbol = "AAPL"
    quantity = 5000
    order_type = "BUY"
    portfolio_manager_id = "PM_789"
    custodian_account = "CUST_12345"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/orders/institutional" -Method Post -Body $institutionalPayload -ContentType "application/json"
```

### 4. Test Algorithmic Workflow
```powershell
$algoPayload = @{
    symbol = "AAPL"
    quantity = 1000
    order_type = "BUY"
    strategy_id = "MOMENTUM_v2"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/orders/algo" -Method Post -Body $algoPayload -ContentType "application/json"
```

---

## Semantic Search Identification

When performing RCA, error logs will contain function names that uniquely identify the workflow:

### Example Log Entries

**Retail Workflow:**
```
[validate_trade] Params - symbol: AAPL, quantity: 100
[check_trading_hours] Trading hours validation
[apply_commission] Commission calculated: $87.50
```
→ Semantic search detects: `validate_trade`, `check_trading_hours` → **RETAIL WORKFLOW**

**Institutional Workflow:**
```
[institutional_compliance_check] Params - symbol: AAPL, quantity: 5000
[check_portfolio_manager_approval] Params - order_id: abc123, symbol: AAPL, quantity: 5000
[verify_custodian_account] Params - order_id: abc123
[apply_volume_discount] Volume discount applied: 0.30%
```
→ Semantic search detects: `institutional_compliance_check`, `check_portfolio_manager_approval` → **INSTITUTIONAL WORKFLOW**

**Algorithmic Workflow:**
```
[validate_algo_credentials] Params - strategy_id: MOMENTUM_v2, order_id: xyz789
[check_circuit_breaker_limits] Params - symbol: AAPL, quantity: 1000, strategy_id: MOMENTUM_v2
[verify_strategy_limits] Params - strategy_id: MOMENTUM_v2
[fast_price_lookup] Fast pricing lookup
```
→ Semantic search detects: `validate_algo_credentials`, `check_circuit_breaker_limits` → **ALGORITHMIC WORKFLOW**

---

## Function Count Summary

| Service | Retail Functions | Institutional Functions | Algo Functions | Total New |
|---------|-----------------|------------------------|----------------|-----------|
| **Orchestrator** | 1 (place_order) | 1 (place_institutional_order) | 1 (place_algo_order) | +2 |
| **Trade Service** | 6 validation | 4 institutional validation | 3 algo validation | +7 |
| **Pricing Service** | 5 pricing | 2 institutional pricing | 1 algo pricing | +3 |
| **Risk Service** | 5 risk assessment | 3 institutional risk | 2 algo risk | +5 |
| **TOTAL** | ~17 | ~10 | ~7 | **+17 new functions** |

---

## Log File Locations

After testing, check logs for each workflow:
```
orchestrator/logs/{trace_id}.log
trade_service/logs/{trace_id}.log
pricing_pnl_service/logs/{trace_id}.log
risk_service/logs/{trace_id}.log
```

Each log will contain the complete function call chain with parameters for RCA analysis.
