# Trading Platform - Multiple Workflow Scenarios

## 🎯 Overview
This platform now supports **5 DISTINCT WORKFLOWS** with different function call chains, enabling realistic RCA (Root Cause Analysis) scenarios. Each workflow is triggered by specific conditions and calls different sets of functions.

---

## 📊 Workflow Matrix

| Workflow | Entry Point | Trigger Condition | Functions Called | Use Case |
|----------|-------------|-------------------|------------------|----------|
| **1. Standard Order** | POST /orders | Normal orders | validate_trade → calculate_pricing → assess_risk → execute_trade | Regular BUY/SELL flow |
| **2. High-Risk Escalation** | POST /orders | risk_score > 75 | Standard flow + escalate_to_risk_manager → check_portfolio_impact → require_manual_approval | Large/risky orders |
| **3. SELL at Loss** | POST /orders | SELL + pnl < 0 | Standard flow + calculate_tax_implications → check_wash_sale_rule → verify_cost_basis_accuracy | Loss-selling with tax |
| **4. Express Order** | POST /orders | order_value < $10K | express_order_check → check_symbol_tradeable → validate_account_balance (SKIPS sector/concentration) | Fast-track small orders |
| **5. Market Data Query** | GET /pricing/symbol/{symbol} | Any time | get_market_price → validate_price_components → check_price_range_validity → verify_market_conditions | Price lookup only |

---

## 🔄 Detailed Workflow Descriptions

### WORKFLOW 1: Standard Order Flow (Baseline)
**Entry:** `POST /orders`  
**Trigger:** All orders (BUY or SELL)  
**Call Chain:**
```
place_order
├── validate_trade
│   ├── check_symbol_tradeable
│   ├── normalize_quantity_to_lot_size
│   ├── check_order_limits
│   └── validate_order_requirements
│       └── validate_account_balance
├── calculate_pricing
│   ├── get_market_price
│   │   └── validate_price_components
│   │       └── check_price_range_validity
│   │           └── verify_market_conditions
│   ├── calculate_total_cost
│   │   └── validate_cost_breakdown
│   │       ├── verify_fee_calculations
│   │       └── audit_commission_rate
│   └── calculate_estimated_pnl
├── assess_risk
│   ├── validate_compliance_rules
│   ├── check_sector_limits (3-sec delay for tech stocks)
│   ├── check_portfolio_concentration
│   ├── assess_order_risk
│   └── calculate_risk_score
│       ├── calculate_volatility_multiplier
│       ├── calculate_position_size_impact
│       ├── calculate_pnl_risk_factor
│       ├── assess_quantity_risk
│       ├── calculate_sector_risk_adjustment
│       └── normalize_risk_score
└── execute_trade
```

**Example:** `POST /orders {"symbol": "AAPL", "quantity": 100, "order_type": "BUY"}`

---

### WORKFLOW 2: High-Risk Escalation Flow ⚠️
**Entry:** `POST /orders`  
**Trigger:** `risk_score > 75` (automatically detected)  
**Call Chain:**
```
place_order
├── [All standard flow functions]
├── assess_risk (returns risk_score = 78)
├── ⚠️ HIGH RISK DETECTED - Triggers additional workflow:
│   ├── escalate_to_risk_manager (POST /risk/escalate)
│   ├── check_portfolio_impact (deep analysis)
│   └── require_manual_approval (if score > 85)
└── [Execution conditional on approval]
```

**Functions ONLY called in this workflow:**
- `escalate_to_risk_manager()`
- `check_portfolio_impact()`
- `require_manual_approval()`

**Example:** 
```json
POST /orders
{
  "symbol": "TSLA",
  "quantity": 500,
  "order_type": "BUY"
}
// Results in risk_score = 82 → triggers escalation
```

**RCA Scenario:** "Why did my order get flagged for manual approval?"
- Trace log shows risk_score = 82
- Follow flow: assess_risk → escalate_to_risk_manager → check_portfolio_impact → require_manual_approval
- Root cause: Position value ($121K) + high volatility (TSLA 2.5x multiplier) = excessive risk

---

### WORKFLOW 3: SELL at Loss Flow (Tax Analysis) 📉
**Entry:** `POST /orders`  
**Trigger:** `order_type = SELL` AND `estimated_pnl < 0` (automatically detected)  
**Call Chain:**
```
place_order
├── [All standard flow functions]
├── calculate_pricing (returns estimated_pnl = -$3,200)
├── 📉 SELL AT LOSS DETECTED - Triggers additional workflow:
│   ├── calculate_tax_implications (POST /pricing/tax-analysis)
│   ├── check_wash_sale_rule (verify no recent repurchases)
│   └── verify_cost_basis_accuracy (confirm loss amount)
└── execute_trade (with tax benefit logged)
```

**Functions ONLY called in this workflow:**
- `calculate_tax_implications()`
- `check_wash_sale_rule()`
- `verify_cost_basis_accuracy()`

**Example:**
```json
POST /orders
{
  "symbol": "NVDA",
  "quantity": 200,
  "order_type": "SELL"
}
// Market price $450, cost basis $466 → PnL = -$3,200
// Triggers tax analysis workflow
```

**RCA Scenario:** "Why was there a delay in my SELL order?"
- Trace log shows estimated_pnl = -$3,200
- Follow flow: calculate_pricing → calculate_tax_implications → check_wash_sale_rule → verify_cost_basis_accuracy
- Root cause: Additional 600ms for tax validation (required for loss-selling compliance)

---

### WORKFLOW 4: Express Order Fast-Track 🚀
**Entry:** `POST /orders`  
**Trigger:** `order_value < $10,000` (can be manually requested)  
**Call Chain:**
```
validate_express_order (POST /trades/validate-express)
├── express_order_check (determines eligibility)
├── check_symbol_tradeable (lightweight check only)
└── validate_account_balance (basic balance check)

❌ SKIPPED VALIDATIONS:
- check_sector_limits (SKIPPED)
- check_portfolio_concentration (SKIPPED)
- deep compliance checks (SKIPPED)
- full risk assessment (SKIPPED)
```

**Functions ONLY called in this workflow:**
- `express_order_check()`

**Example:**
```json
POST /orders
{
  "symbol": "AAPL",
  "quantity": 50,
  "order_type": "BUY"
}
// 50 shares × $175 = $8,750 → Express eligible
// Fast-track: 300ms vs 1,200ms for standard flow
```

**RCA Scenario:** "Why was my small order processed so quickly?"
- Trace log shows express_eligible = true, order_value = $8,750
- Follow flow: express_order_check → check_symbol_tradeable → validate_account_balance
- Root cause: Express workflow skipped 5 heavy validation steps (sector, concentration, deep compliance)

---

### WORKFLOW 5: Market Data Query (No Order Execution) 📈
**Entry:** `GET /pricing/symbol/{symbol}`  
**Trigger:** Direct API call (no order placement)  
**Call Chain:**
```
get_current_price (GET /pricing/symbol/AAPL)
├── get_market_price
│   └── validate_price_components
│       └── check_price_range_validity
│           └── verify_market_conditions
└── [Returns price only - NO order execution]

❌ SKIPPED:
- validate_trade (NO validation)
- assess_risk (NO risk assessment)
- execute_trade (NO execution)
```

**Example:**
```
GET /pricing/symbol/AAPL
// Returns: {"symbol": "AAPL", "price": 175.50, "timestamp": "..."}
```

**RCA Scenario:** "Why do I see pricing logs without any trade?"
- Trace log shows ONLY: get_market_price → validate_price_components
- Root cause: User called market data API (GET /pricing/symbol/AAPL) - not an actual order

---

## 🧪 Testing Each Workflow

### Test Scenario 1: Standard Order
```bash
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{"symbol": "AAPL", "quantity": 100, "order_type": "BUY"}'
```
**Expected Flow:** validate_trade → calculate_pricing → assess_risk → execute_trade  
**Functions Called:** 25-30 functions  
**Duration:** ~1,200ms

---

### Test Scenario 2: High-Risk Order (Triggers Escalation)
```bash
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{"symbol": "TSLA", "quantity": 500, "order_type": "BUY"}'
```
**Expected Flow:** Standard + escalate_to_risk_manager + check_portfolio_impact  
**Functions Called:** 33-35 functions  
**Duration:** ~1,800ms  
**Unique Functions:** escalate_to_risk_manager, check_portfolio_impact, require_manual_approval

---

### Test Scenario 3: SELL at Loss (Triggers Tax Analysis)
```bash
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{"symbol": "NVDA", "quantity": 200, "order_type": "SELL"}'
```
**Expected Flow:** Standard + calculate_tax_implications + check_wash_sale_rule  
**Functions Called:** 33-35 functions  
**Duration:** ~1,600ms  
**Unique Functions:** calculate_tax_implications, check_wash_sale_rule, verify_cost_basis_accuracy

---

### Test Scenario 4: Express Order (Fast-Track)
```bash
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{"symbol": "AAPL", "quantity": 50, "order_type": "BUY"}'
```
**Expected Flow:** express_order_check → check_symbol_tradeable → validate_account_balance  
**Functions Called:** 8-10 functions (MUCH lighter)  
**Duration:** ~300ms (4x faster!)  
**Skipped Functions:** check_sector_limits, check_portfolio_concentration, deep compliance

---

### Test Scenario 5: Market Data Query
```bash
curl -X GET http://localhost:8002/pricing/symbol/AAPL
```
**Expected Flow:** get_market_price → validate_price_components → verify_market_conditions  
**Functions Called:** 4-5 functions  
**Duration:** ~100ms  
**No Trade Execution:** Price lookup only

---

## 📊 Workflow Comparison Table

| Metric | Standard | High-Risk | SELL Loss | Express | Market Data |
|--------|----------|-----------|-----------|---------|-------------|
| **Functions Called** | 28 | 35 | 34 | 10 | 5 |
| **Duration** | 1,200ms | 1,800ms | 1,600ms | 300ms | 100ms |
| **Risk Assessment** | ✅ Full | ✅ Full + Escalation | ✅ Full | ❌ Skipped | ❌ N/A |
| **Trade Execution** | ✅ Yes | ✅ Conditional | ✅ Yes | ✅ Yes | ❌ No |
| **Tax Analysis** | ❌ No | ❌ No | ✅ Yes | ❌ No | ❌ N/A |
| **Sector Checks** | ✅ Yes | ✅ Yes | ✅ Yes | ❌ Skipped | ❌ N/A |

---

## 🔍 RCA Query Examples

### Find all orders that triggered high-risk escalation:
```sql
-- Query 2 modified: Find high-risk orders
SELECT c.function_name, c.parameters, r.call_order, r.line_number
FROM CodeNodes c
JOIN Relationships r ON c.node_id = r.to_node
WHERE c.function_name = 'escalate_to_risk_manager'
ORDER BY r.call_order;
```

### Find all SELL-at-loss orders with tax analysis:
```sql
-- Find tax analysis calls
SELECT c.function_name, c.parameters, r.call_order
FROM CodeNodes c
JOIN Relationships r ON c.node_id = r.to_node
WHERE c.function_name IN ('calculate_tax_implications', 'check_wash_sale_rule', 'verify_cost_basis_accuracy')
ORDER BY r.call_order;
```

### Find all express orders (fast-tracked):
```sql
-- Find express order validations
SELECT c.function_name, c.parameters, r.call_order
FROM CodeNodes c
JOIN Relationships r ON c.node_id = r.to_node
WHERE c.function_name = 'express_order_check'
ORDER BY r.call_order;
```

---

## 🎓 Key Takeaways

1. **Conditional Workflows:** Functions are called based on runtime conditions (risk_score, pnl, order_value)
2. **Function Uniqueness:** Each workflow has unique functions that are ONLY called in that scenario
3. **Performance Variance:** Different workflows have vastly different execution times (100ms - 1,800ms)
4. **RCA Capability:** You can now trace logs and see which workflow was executed based on function calls
5. **Realistic Scenarios:** Multiple workflows simulate real-world trading platform complexity

---

## 📝 Next Steps for Testing

1. **Run generic parser** to capture all new functions
2. **Execute test scenarios** for each workflow
3. **Query flow analysis** to see different call patterns
4. **Analyze logs** to understand which workflow was triggered
5. **Use Query 10** (Map log to flow) to trace specific events back to workflows

---

**Generated:** 2025-12-24  
**Platform Version:** 2.0 (Multi-Workflow)
