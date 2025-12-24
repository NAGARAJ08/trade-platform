import logging
import json
import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum
import random

from fastapi import FastAPI, HTTPException, Header, Request
from pydantic import BaseModel, Field
import uvicorn

# Custom JSON formatter for Splunk-style logs
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "service": "pricing_pnl_service",
            "message": record.getMessage(),
        }
        if hasattr(record, 'trace_id'):
            log_data["trace_id"] = record.trace_id
        if hasattr(record, 'order_id'):
            log_data["order_id"] = record.order_id
        if hasattr(record, 'extra_data'):
            log_data.update(record.extra_data)
        # Include stack trace if exception info is present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Console handler with readable format
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - pricing_pnl_service - %(message)s'))

logger.addHandler(console_handler)

# Store trace-specific handlers
trace_handlers = {}

class TraceFilter(logging.Filter):
    """Filter logs by trace_id"""
    def __init__(self, trace_id):
        super().__init__()
        self.trace_id = trace_id
    
    def filter(self, record):
        return hasattr(record, 'trace_id') and record.trace_id == self.trace_id

def get_trace_logger(trace_id: str):
    """Get or create a logger for specific trace_id"""
    if trace_id not in trace_handlers:
        trace_file_handler = logging.FileHandler(f'../logs/{trace_id}.log')
        trace_file_handler.setFormatter(JsonFormatter())
        trace_file_handler.addFilter(TraceFilter(trace_id))  # Only log for this trace_id
        trace_handlers[trace_id] = trace_file_handler
        logger.addHandler(trace_file_handler)
    return logger

# FastAPI app
app = FastAPI(
    title="Pricing & PnL Service",
    description="Combined service for pricing calculation and profit/loss analysis",
    version="1.0.0"
)

# In-memory storage
pricing_data: Dict[str, Dict[str, Any]] = {}
pnl_data: Dict[str, Dict[str, Any]] = {}


class OrderType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class PricingRequest(BaseModel):
    order_id: str
    symbol: str = Field(..., example="AAPL")
    quantity: int = Field(...)
    order_type: OrderType


class PricingResponse(BaseModel):
    order_id: str
    symbol: str
    price: float
    estimated_pnl: float
    total_cost: float
    commission: float
    fees: float
    base_amount: float
    timestamp: str


def get_trace_id(x_trace_id: Optional[str] = Header(None)) -> str:
    """Generate or use existing trace ID"""
    return x_trace_id or str(uuid.uuid4())


def verify_market_conditions(symbol: str, price: float, trace_id: Optional[str] = None, order_id: Optional[str] = None) -> bool:
    """
    Level 3: Verify market conditions are within acceptable parameters.
    
    Args:
        symbol: Stock ticker symbol
        price: Current price to verify
        trace_id: Trace ID for logging
        order_id: Order ID for logging
    
    Returns:
        bool: True if market conditions are acceptable
    
    Raises:
        ValueError: If price is outside acceptable range
    
    Note:
        This is called deep in the call stack to validate pricing data
    """
    if trace_id and order_id:
        logger.info(f"[verify_market_conditions] Verifying market conditions for {symbol} at ${price}",
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'verify_market_conditions'})
    
    # Check if price is within reasonable bounds (not 0 or negative)
    if price <= 0:
        if trace_id and order_id:
            logger.exception(f"[verify_market_conditions] Invalid price detected: ${price}",
                           extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'verify_market_conditions',
                                  'extra_data': {'symbol': symbol, 'invalid_price': price}})
        raise ValueError(f"Invalid market price for {symbol}: ${price}")
    
    # Check if price is suspiciously high (> $10,000 per share)
    if price > 10000:
        if trace_id and order_id:
            logger.warning(f"[verify_market_conditions] Unusually high price detected: ${price}",
                          extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'verify_market_conditions'})
    
    return True


def check_price_range_validity(symbol: str, price: float, base_price: float, trace_id: Optional[str] = None, order_id: Optional[str] = None) -> bool:
    """
    Level 2: Validate that current price is within acceptable range of base price.
    
    Args:
        symbol: Stock ticker symbol
        price: Current market price with variance
        base_price: Base reference price
        trace_id: Trace ID for logging
        order_id: Order ID for logging
    
    Returns:
        bool: True if price is valid
    
    Raises:
        ValueError: If price variance exceeds acceptable threshold
    
    Note:
        Calls verify_market_conditions for deeper validation
    """
    if trace_id and order_id:
        logger.info(f"[check_price_range_validity] Validating price range for {symbol}",
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'check_price_range_validity',
                          'extra_data': {'current_price': price, 'base_price': base_price}})
    
    # Calculate variance percentage
    variance_pct = abs(price - base_price) / base_price * 100
    
    # Price shouldn't vary more than 10% from base in normal conditions
    if variance_pct > 10:
        if trace_id and order_id:
            logger.exception(f"[check_price_range_validity] Price variance too high: {variance_pct:.2f}%",
                           extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'check_price_range_validity',
                                  'extra_data': {'symbol': symbol, 'variance_pct': variance_pct, 'threshold': 10}})
        raise ValueError(f"Price variance {variance_pct:.2f}% exceeds acceptable range for {symbol}")
    
    # Validate market conditions (Level 3)
    verify_market_conditions(symbol, price, trace_id, order_id)
    
    if trace_id and order_id:
        logger.info(f"[check_price_range_validity] Price range validation passed",
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'check_price_range_validity'})
    
    return True


def validate_price_components(symbol: str, base_price: float, variance: float, trace_id: Optional[str] = None, order_id: Optional[str] = None) -> float:
    """
    Level 1: Validate all components of price calculation.
    
    Args:
        symbol: Stock ticker symbol
        base_price: Base reference price
        variance: Random variance to apply (-0.02 to 0.02)
        trace_id: Trace ID for logging
        order_id: Order ID for logging
    
    Returns:
        float: Validated final price
    
    Note:
        Calls check_price_range_validity which calls verify_market_conditions
        Creates a 3-level deep call stack for complex validation
    """
    if trace_id and order_id:
        logger.info(f"[validate_price_components] Starting price component validation for {symbol}",
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'validate_price_components',
                          'extra_data': {'base_price': base_price, 'variance': variance}})
    
    # Calculate price with variance
    calculated_price = base_price * (1 + variance)
    final_price = round(calculated_price, 2)
    
    # Validate price range (Level 2, which calls Level 3)
    check_price_range_validity(symbol, final_price, base_price, trace_id, order_id)
    
    if trace_id and order_id:
        logger.info(f"[validate_price_components] Price validation complete: ${final_price}",
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'validate_price_components',
                          'extra_data': {'final_price': final_price}})
    
    return final_price


def get_market_price(symbol: str, order_type: Optional[OrderType] = None, trace_id: Optional[str] = None, order_id: Optional[str] = None) -> float:
    """
    Retrieve current market price for a trading symbol with simulated variance.
    COMMON FUNCTION used by both BUY and SELL workflows.
    
    Args:
        symbol: Stock ticker symbol (e.g., 'AAPL', 'NVDA')
        order_type: BUY or SELL (optional, for logging)
        trace_id: Trace ID for logging (optional)
        order_id: Order ID for logging (optional)
    
    Returns:
        float: Current market price rounded to 2 decimal places
    
    Raises:
        HTTPException: If market data feed is unavailable or symbol is restricted
        ValueError: If symbol is not found in supported symbols list
    
    Note:
        - This is a COMMON FUNCTION called by both BUY and SELL flows
        - Validates market data feed availability before price lookup
        - Applies ±2% random variance to base price for realistic market simulation
        - Simulates real-time price fluctuations between service calls
        - Errors here will appear in logs for both workflow types
    """
    # Market data feed validation for restricted symbols
    restricted_symbols = {"GME", "AMC"}  # Symbols with market data issues
    
    if symbol in restricted_symbols:
        if trace_id and order_id:
            logger.error(f"[get_market_price] MARKET DATA FEED UNAVAILABLE - Symbol {symbol} currently experiencing data feed issues",
                        extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'get_market_price',
                               'extra_data': {'symbol': symbol, 'order_type': order_type.value if order_type else None, 'error_type': 'market_data_unavailable'}})
        raise HTTPException(
            status_code=503,
            detail=f"Market data feed unavailable for symbol '{symbol}'. Unable to retrieve real-time pricing. Please try again later or contact support if issue persists."
        )
    
    base_prices = {
        "AAPL": 175.50,
        "GOOGL": 140.25,
        "MSFT": 378.90,
        "AMZN": 152.75,
        "TSLA": 242.80,
        "META": 356.20,
        "NVDA": 495.60
    }
    
    # Get base price - no default, should fail for unknown
    if symbol not in base_prices:
        raise ValueError(f"Symbol '{symbol}' not found in market data")
    
    base_price = base_prices[symbol]
    
    # Apply market variance for realistic price simulation
    # Mimics real-world price movements between service calls
    variance = random.uniform(-0.02, 0.02)
    
    # Validate all price components through nested validation chain
    # This creates a 3-level deep call stack:
    # validate_price_components -> check_price_range_validity -> verify_market_conditions
    price = validate_price_components(symbol, base_price, variance, trace_id, order_id)
    
    return price


def get_cost_basis(symbol: str) -> float:
    """
    Retrieve average cost basis for profit/loss calculations.
    
    Args:
        symbol: Stock ticker symbol
    
    Returns:
        float: Average purchase price for the symbol, defaults to $50.00 if unknown
    
    Note:
        Cost basis represents the average price paid per share and is used
        to calculate estimated P&L on SELL orders or unrealized gains on BUY orders

    """
    cost_basis = {
        "AAPL": 165.00,
        "GOOGL": 135.00,
        "MSFT": 360.00,  
        "AMZN": 145.00,
        "TSLA": 230.00,
        "META": 340.00,
        "NVDA": 475.00
    }
    # Use default cost basis for unknown symbols
    return cost_basis.get(symbol, 50.0)


def audit_commission_rate(commission: float, base_amount: float, trace_id: str, order_id: str) -> bool:
    """
    Level 3: Audit commission rate to ensure it matches expected percentage.
    
    Args:
        commission: Calculated commission amount
        base_amount: Base transaction amount
        trace_id: Trace ID for logging
        order_id: Order ID for logging
    
    Returns:
        bool: True if commission rate is valid
    
    Raises:
        ValueError: If commission rate is outside acceptable range
    """
    logger.info(f"[audit_commission_rate] Auditing commission: ${commission} on ${base_amount}",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'audit_commission_rate'})
    
    # Skip validation if base amount is too small (edge case)
    if base_amount < 0.01:
        logger.warning(f"[audit_commission_rate] Skipping validation - base amount too small: ${base_amount}",
                      extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'audit_commission_rate'})
        return True
    
    # Calculate actual rate
    actual_rate = commission / base_amount
    expected_rate = 0.005  # 0.5%
    
    # Allow 0.1% variance for rounding and additional fees
    if abs(actual_rate - expected_rate) > 0.001:
        logger.exception(f"[audit_commission_rate] Commission rate mismatch: expected {expected_rate*100}%, got {actual_rate*100}%",
                       extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'audit_commission_rate',
                              'extra_data': {'expected_rate': expected_rate, 'actual_rate': actual_rate}})
        raise ValueError(f"Commission rate validation failed: expected {expected_rate*100}%, calculated {actual_rate*100}%")
    
    logger.info(f"[audit_commission_rate] Commission rate validated: {actual_rate*100:.3f}%",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'audit_commission_rate'})
    return True


def verify_fee_calculations(fees: float, quantity: int, order_type: str, trace_id: str, order_id: str) -> bool:
    """
    Level 2: Verify fee calculations are accurate.
    
    Args:
        fees: Calculated fees
        quantity: Number of shares
        order_type: BUY or SELL
        trace_id: Trace ID for logging
        order_id: Order ID for logging
    
    Returns:
        bool: True if fees are valid
    
    Raises:
        ValueError: If fee calculation appears incorrect
    """
    logger.info(f"[verify_fee_calculations] Verifying fees: ${fees} for {quantity} shares",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'verify_fee_calculations'})
    
    if order_type == "BUY":
        # BUY fees should be $0.01 per share
        expected_fees = quantity * 0.01
        if abs(fees - expected_fees) > 0.01:
            logger.exception(f"[verify_fee_calculations] Fee mismatch for BUY: expected ${expected_fees}, got ${fees}",
                           extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'verify_fee_calculations'})
            raise ValueError(f"BUY fee validation failed: expected ${expected_fees}, calculated ${fees}")
    else:
        # SELL fees are SEC fees (0.0000207 * proceeds), harder to validate without proceeds
        # Just verify it's non-negative
        if fees < 0:
            logger.exception(f"[verify_fee_calculations] Negative fees detected: ${fees}",
                           extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'verify_fee_calculations'})
            raise ValueError(f"Invalid negative fees: ${fees}")
    
    logger.info(f"[verify_fee_calculations] Fee validation passed",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'verify_fee_calculations'})
    return True


def validate_cost_breakdown(base_amount: float, commission: float, fees: float, total: float, 
                            order_type: str, quantity: int, trace_id: str, order_id: str) -> bool:
    """
    Level 1: Validate complete cost breakdown for accuracy.
    
    Args:
        base_amount: Base transaction amount
        commission: Commission charged
        fees: Exchange/regulatory fees
        total: Total cost
        order_type: BUY or SELL
        quantity: Number of shares
        trace_id: Trace ID for logging
        order_id: Order ID for logging
    
    Returns:
        bool: True if cost breakdown is valid
    
    Raises:
        ValueError: If cost breakdown validation fails
    
    Note:
        Calls verify_fee_calculations which calls audit_commission_rate
        Creates a 3-level deep validation chain
    """
    logger.info(f"[validate_cost_breakdown] Validating cost breakdown for {order_type} order",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'validate_cost_breakdown',
                      'extra_data': {'base': base_amount, 'commission': commission, 'fees': fees, 'total': total}})
    
    # Verify fee calculations (Level 2, which calls Level 3)
    verify_fee_calculations(fees, quantity, order_type, trace_id, order_id)
    
    # Audit commission rate (Level 3)
    audit_commission_rate(commission, base_amount, trace_id, order_id)
    
    # Validate total calculation
    if order_type == "BUY":
        expected_total = base_amount + commission + fees
    else:  # SELL
        expected_total = base_amount - commission - fees
    
    if abs(total - expected_total) > 0.01:
        logger.exception(f"[validate_cost_breakdown] Total cost mismatch: expected ${expected_total}, got ${total}",
                       extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'validate_cost_breakdown',
                              'extra_data': {'expected': expected_total, 'actual': total, 'difference': total - expected_total}})
        raise ValueError(f"Cost breakdown validation failed: total ${total} doesn't match expected ${expected_total}")
    
    logger.info(f"[validate_cost_breakdown] Cost breakdown validated successfully",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'validate_cost_breakdown'})
    return True


def calculate_total_cost(quantity: int, price: float, symbol: str, order_type: OrderType, trace_id: str, order_id: str) -> Dict[str, float]:
    """
    Calculate comprehensive cost breakdown including all fees and commissions.
    
    Args:
        quantity: Number of shares to trade
        price: Price per share
        symbol: Stock ticker symbol
        order_type: BUY or SELL
        trace_id: Trace ID for logging
        order_id: Order ID for logging
    
    Returns:
        dict: Cost breakdown with keys:
            - 'base_amount': Base cost (BUY) or gross proceeds (SELL)
            - 'commission': Trading commission
            - 'fees': Exchange/regulatory fees
            - 'total_cost': Final amount (including all fees)
    
    Note:
        BUY orders: total_cost = base + commission + fees (amount to debit)
        SELL orders: total_cost = base - commission - fees (net proceeds)
    """
    logger.info(f"[calculate_total_cost] Calculating cost for {order_type} order", 
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'calculate_total_cost'})
    
    if order_type == OrderType.BUY:
        base_cost = quantity * price
        commission = base_cost * 0.005  # 0.5%
        exchange_fee = quantity * 0.01  # $0.01 per share
        total_cost = base_cost + commission + exchange_fee
        
        logger.info(f"[calculate_total_cost] BUY cost breakdown - Base: ${base_cost:.2f}, Commission: ${commission:.2f}, Fees: ${exchange_fee:.2f}, Total: ${total_cost:.2f}", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'calculate_total_cost',
                          'extra_data': {'base_cost': base_cost, 'commission': commission, 'exchange_fee': exchange_fee, 'total': total_cost}})
        
        # Validate cost breakdown through nested validation chain
        # Creates 3-level deep call stack: validate_cost_breakdown -> verify_fee_calculations -> audit_commission_rate
        validate_cost_breakdown(base_cost, commission, exchange_fee, total_cost, "BUY", quantity, trace_id, order_id)
        
        return {'base_amount': base_cost, 'commission': commission, 'fees': exchange_fee, 'total_cost': total_cost}
    else:  # SELL
        gross_proceeds = quantity * price
        commission = gross_proceeds * 0.005  # 0.5%
        sec_fee = gross_proceeds * 0.0000207  # SEC fee
        
        # For large SELL orders of certain stocks, extra fee applied
        if quantity > 200 and symbol in ["TSLA", "NVDA"]:
            logger.warning(f"[calculate_total_cost] Large SELL order of {symbol}, applying additional processing fee", 
                          extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'calculate_total_cost'})
            extra_fee = gross_proceeds * 0.02  # 2% extra
            commission += extra_fee
        
        net_proceeds = gross_proceeds - commission - sec_fee
        
        logger.info(f"[calculate_total_cost] SELL proceeds breakdown - Gross: ${gross_proceeds:.2f}, Commission: ${commission:.2f}, SEC Fee: ${sec_fee:.2f}, Net: ${net_proceeds:.2f}", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'calculate_total_cost',
                          'extra_data': {'gross_proceeds': gross_proceeds, 'commission': commission, 'sec_fee': sec_fee, 'net_proceeds': net_proceeds}})
        
        # Validate cost breakdown through nested validation chain
        validate_cost_breakdown(gross_proceeds, commission, sec_fee, net_proceeds, "SELL", quantity, trace_id, order_id)
        
        return {'base_amount': gross_proceeds, 'commission': commission, 'fees': sec_fee, 'total_cost': net_proceeds}


def calculate_tax_implications(symbol: str, pnl: float, quantity: int, trace_id: str, order_id: str) -> Dict[str, Any]:
    """
    Calculate tax implications for SELL orders with losses.
    Called ONLY when order_type = SELL AND pnl < 0.
    
    Args:
        symbol: Stock ticker
        pnl: Estimated profit/loss (negative for loss)
        quantity: Number of shares
        trace_id: Trace ID for logging
        order_id: Order ID for logging
    
    Returns:
        dict: Tax calculation details
    """
    logger.info(f"[calculate_tax_implications] Params - symbol: {symbol}, pnl: ${pnl:.2f}, quantity: {quantity}, capital_loss: ${abs(pnl):.2f}",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'calculate_tax_implications'})
    logger.info(f"[calculate_tax_implications] Calculating tax implications for loss sale",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'calculate_tax_implications'})
    
    # Calculate potential tax loss deduction
    capital_loss = abs(pnl)
    tax_bracket = 0.24  # Assume 24% tax bracket
    tax_benefit = capital_loss * tax_bracket
    
    tax_calc = {
        'capital_loss': capital_loss,
        'tax_bracket': tax_bracket,
        'estimated_tax_benefit': round(tax_benefit, 2),
        'loss_type': 'SHORT_TERM' if quantity > 100 else 'LONG_TERM',  # Simplified
        'deduction_limit': 3000  # IRS annual limit
    }
    
    logger.info(f"[calculate_tax_implications] Tax benefit: ${tax_benefit:.2f} from ${capital_loss:.2f} loss",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'calculate_tax_implications',
                      'extra_data': tax_calc})
    
    return tax_calc


def check_wash_sale_rule(symbol: str, quantity: int, trace_id: str, order_id: str) -> Dict[str, bool]:
    """
    Check for potential wash sale violations (selling at loss then rebuying within 30 days).
    Called ONLY for SELL orders with losses.
    
    Args:
        symbol: Stock ticker
        quantity: Number of shares
        trace_id: Trace ID for logging
        order_id: Order ID for logging
    
    Returns:
        dict: Wash sale check results
    """
    logger.info(f"[check_wash_sale_rule] Params - symbol: {symbol}, quantity: {quantity}, lookback_days: 30",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'check_wash_sale_rule'})
    logger.info(f"[check_wash_sale_rule] Checking wash sale rules for {symbol}",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'check_wash_sale_rule'})
    
    # Simulate recent transaction check (would query trade history in production)
    import time
    time.sleep(0.2)
    
    # Simulate: no recent buys of same symbol (safe)
    result = {
        'wash_sale_risk': False,
        'recent_buys_within_30_days': 0,
        'warning': None
    }
    
    logger.info(f"[check_wash_sale_rule] No wash sale violations detected",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'check_wash_sale_rule',
                      'extra_data': result})
    
    return result


def verify_cost_basis_accuracy(symbol: str, quantity: int, trace_id: str, order_id: str) -> Dict[str, Any]:
    """
    Verify cost basis accuracy for accurate loss calculation.
    Called ONLY for SELL orders with losses to ensure tax reporting accuracy.
    
    Args:
        symbol: Stock ticker
        quantity: Number of shares
        trace_id: Trace ID for logging
        order_id: Order ID for logging
    
    Returns:
        dict: Cost basis verification details
    """
    logger.info(f"[verify_cost_basis_accuracy] Params - symbol: {symbol}, quantity: {quantity}",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'verify_cost_basis_accuracy'})
    logger.info(f"[verify_cost_basis_accuracy] Verifying cost basis for {symbol}",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'verify_cost_basis_accuracy'})
    
    cost_basis = get_cost_basis(symbol)
    
    # Simulate cost basis verification against purchase records
    import time
    time.sleep(0.2)
    
    verification = {
        'verified_cost_basis': cost_basis,
        'purchase_lot_method': 'FIFO',  # First In, First Out
        'lots_affected': 2,
        'accuracy_confirmed': True
    }
    
    logger.info(f"[verify_cost_basis_accuracy] Cost basis verified: ${cost_basis}/share using FIFO",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'verify_cost_basis_accuracy',
                      'extra_data': verification})
    
    return verification


def calculate_estimated_pnl(symbol: str, quantity: int, price: float, order_type: OrderType, trace_id: str, order_id: str) -> float:
    """
    Calculate estimated profit/loss for the order.
    
    Args:
        symbol: Stock ticker symbol
        quantity: Number of shares
        price: Current market price per share
        order_type: BUY or SELL
        trace_id: Trace ID for logging
        order_id: Order ID for logging
    
    Returns:
        float: Estimated P&L rounded to 2 decimal places
            - Positive: Profit (selling above cost basis)
            - Negative: Loss (buying above cost basis or selling below)
    
    Calculation:
        BUY: PnL = -(price - cost_basis) * quantity (negative = paying premium)
        SELL: PnL = (price - cost_basis) * quantity (positive = profit)
    """
    logger.info(f"[calculate_estimated_pnl] Calculating PnL for {order_type} order", 
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'calculate_estimated_pnl'})
    
    cost_basis = get_cost_basis(symbol)
    
    if symbol == "MSFT":
        actual_cost_basis_used = 350.00  
        logger.warning(f"[calculate_estimated_pnl] MSFT calculation using adjusted cost basis ${actual_cost_basis_used} instead of ${cost_basis}",
                      extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'calculate_estimated_pnl',
                             'extra_data': {'displayed_cost_basis': cost_basis, 'actual_used': actual_cost_basis_used}})
        price_diff = price - actual_cost_basis_used
    else:
        price_diff = price - cost_basis
    
    if order_type == OrderType.BUY:
        pnl = -(price_diff * quantity)  # Negative because we're buying
        logger.info(f"[calculate_estimated_pnl] BUY PnL: ${pnl:.2f} (paying ${price} vs cost basis ${cost_basis})", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'calculate_estimated_pnl',
                          'extra_data': {'pnl': pnl, 'price': price, 'cost_basis': cost_basis}})
    else:  # SELL
        pnl = price_diff * quantity  # Positive because we're selling
        logger.info(f"[calculate_estimated_pnl] SELL PnL: ${pnl:.2f} (selling at ${price} vs cost basis ${cost_basis})", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'calculate_estimated_pnl',
                          'extra_data': {'pnl': pnl, 'price': price, 'cost_basis': cost_basis}})
    
    return round(pnl, 2)


@app.get("/")
def root():
    """Root endpoint"""
    return {"message": "Pricing & PnL Service", "docs": "/docs"}


@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "pricing_pnl_service"}


@app.post("/pricing/calculate", response_model=PricingResponse)
def calculate_pricing(request_data: PricingRequest, request: Request):
    """
    Calculate pricing and estimated PnL for an order
    This combines pricing lookup and PnL estimation
    """
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    
    # Create trace-specific log file
    get_trace_logger(trace_id)
    
    logger.info("[calculate_pnl] Pricing calculation request received", extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'function': 'calculate_pnl'})
    logger.info(f"[calculate_pnl] Calculating pricing - Symbol: {request_data.symbol}, Quantity: {request_data.quantity}, Type: {request_data.order_type}", extra={
        "trace_id": trace_id,
        "order_id": request_data.order_id,
        "function": "calculate_pnl",
        "symbol": request_data.symbol,
        "quantity": request_data.quantity
    })
    
    try:
        # Get market price (includes market data feed validation - COMMON FUNCTION for BUY & SELL)
        logger.info(f"[calculate_pricing] Fetching market price for {request_data.symbol}",
                   extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'function': 'calculate_pricing'})
        current_price = get_market_price(request_data.symbol, request_data.order_type, trace_id, request_data.order_id)
        
        logger.info(f"[get_market_price] Market price retrieved: ${current_price}", extra={
            "trace_id": trace_id,
            "order_id": request_data.order_id,
            "function": "get_market_price",
            "symbol": request_data.symbol,
            "price": current_price
        })
    except ValueError as e:
        logger.exception(f"[get_market_price] Market data unavailable for symbol: {request_data.symbol}", extra={
            "trace_id": trace_id,
            "order_id": request_data.order_id,
            "function": "get_market_price",
            "symbol": request_data.symbol,
            "error": str(e)
        })
        raise HTTPException(status_code=404, detail=f"Unable to retrieve market price for symbol '{request_data.symbol}'. Symbol not found in market data feed.")
    
    try:
        order_value = current_price * request_data.quantity
        
        logger.info(f"[calculate_pnl] Calculating total order value: {request_data.quantity} x ${current_price} = ${order_value}", 
                   extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'function': 'calculate_pnl', 'extra_data': {'order_value': order_value}})
        
        # Apply bulk order pricing adjustment
        if request_data.quantity > 500:
            adjusted_multiplier = 0.98
            order_value = order_value * adjusted_multiplier
            
            logger.info(f"[calculate_pnl] Applied bulk pricing adjustment: final value ${order_value:.2f}", extra={
                'trace_id': trace_id,
                'order_id': request_data.order_id,
                'function': 'calculate_pnl',
                'extra_data': {'adjusted_value': order_value}
            })
        
        logger.info(f"[calculate_pnl] Order value ${order_value:.2f} calculated successfully", 
                   extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'function': 'calculate_pnl', 'extra_data': {'order_value': order_value}})
        
        # Calculate total cost based on order type
        logger.info("[calculate_pricing] Step 2: Calculating total cost and PnL", 
                   extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'function': 'calculate_pricing'})
        
        cost_breakdown = calculate_total_cost(request_data.quantity, current_price, request_data.symbol, request_data.order_type, trace_id, request_data.order_id)
        estimated_pnl = calculate_estimated_pnl(request_data.symbol, request_data.quantity, current_price, request_data.order_type, trace_id, request_data.order_id)
        
        total_cost = cost_breakdown['total_cost']
        
        timestamp = datetime.now().isoformat()
        
        # Store pricing data
        pricing_data[request_data.order_id] = {
            "order_id": request_data.order_id,
            "symbol": request_data.symbol,
            "price": current_price,
            "quantity": request_data.quantity,
            "estimated_pnl": estimated_pnl,
            "total_cost": total_cost,
            "timestamp": timestamp
        }
        
        logger.info("[calculate_pnl] Pricing calculation completed", extra={
            "trace_id": trace_id,
            "order_id": request_data.order_id,
            "function": "calculate_pnl",
            'extra_data': {
                'symbol': request_data.symbol,
                'price': current_price,
                'quantity': request_data.quantity,
                'estimated_pnl': estimated_pnl,
                'total_cost': total_cost
            }
        })
        
        return PricingResponse(
            order_id=request_data.order_id,
            symbol=request_data.symbol,
            price=current_price,
            estimated_pnl=estimated_pnl,
            total_cost=total_cost,
            commission=cost_breakdown['commission'],
            fees=cost_breakdown['fees'],
            base_amount=cost_breakdown['base_amount'],
            timestamp=timestamp
        )
        
    except HTTPException:
        # Re-raise HTTPException without logging as unexpected error
        raise
    except Exception as e:
        logger.exception("[calculate_pnl] Unexpected error in pricing calculation", extra={
            "trace_id": trace_id,
            "order_id": request_data.order_id,
            "function": "calculate_pnl",
            "extra_data": {"error": str(e), "error_type": type(e).__name__}
        })
        raise HTTPException(status_code=500, detail=f"Pricing calculation failed: {str(e)}")


@app.get("/pricing/{order_id}")
def get_pricing(order_id: str, request: Request):
    """Get pricing data for a specific order"""
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    
    logger.info("[get_pricing] Fetching pricing data", extra={
        "trace_id": trace_id,
        "order_id": order_id,
        "function": "get_pricing"
    })
    
    pricing = pricing_data.get(order_id)
    if not pricing:
        logger.warning("[get_pricing] Pricing data not found", extra={
            "trace_id": trace_id,
            "order_id": order_id,
            "function": "get_pricing"
        })
        raise HTTPException(status_code=404, detail="Pricing data not found")
    
    return pricing


@app.get("/pricing/symbol/{symbol}")
def get_current_price(symbol: str, request: Request):
    """Get current market price for a symbol"""
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    
    logger.info("[get_current_price] Fetching current price", extra={
        "trace_id": trace_id,
        "symbol": symbol,
        "function": "get_current_price"
    })
    
    try:
        price = get_market_price(symbol)
        return {
            "symbol": symbol,
            "price": price,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.exception("[get_current_price] Error fetching price", extra={
            "trace_id": trace_id,
            "symbol": symbol,
            "function": "get_current_price",
            "extra_data": {"error": str(e), "error_type": type(e).__name__}
        })
        raise HTTPException(status_code=500, detail="Unable to fetch price")


@app.get("/pnl/{order_id}")
def get_pnl(order_id: str, request: Request):
    """Get PnL data for a specific order"""
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    
    logger.info("[get_pnl] Fetching PnL data", extra={
        "trace_id": trace_id,
        "order_id": order_id,
        "function": "get_pnl"
    })
    
    pricing = pricing_data.get(order_id)
    if not pricing:
        logger.warning("[get_pnl] PnL data not found", extra={
            "trace_id": trace_id,
            "order_id": order_id,
            "function": "get_pnl"
        })
        raise HTTPException(status_code=404, detail="PnL data not found")
    
    return {
        "order_id": order_id,
        "estimated_pnl": pricing.get("estimated_pnl"),
        "total_cost": pricing.get("total_cost"),
        "symbol": pricing.get("symbol")
    }


@app.post("/pricing/tax-analysis")
async def analyze_tax_implications(request: Request):
    """
    WORKFLOW 3: SELL at Loss Tax Analysis Workflow
    Called ONLY when order_type=SELL AND pnl < 0
    Creates different call chain: calculate_tax_implications → check_wash_sale_rule → verify_cost_basis_accuracy
    """
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    data = await request.json()
    
    order_id = data.get('order_id')
    symbol = data.get('symbol')
    pnl = data.get('pnl')
    quantity = data.get('quantity')
    
    get_trace_logger(trace_id)
    
    logger.info(f"[analyze_tax_implications] Params - order_id: {order_id}, symbol: {symbol}, pnl: ${pnl:.2f}, quantity: {quantity}",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'analyze_tax_implications'})
    logger.info(f"[analyze_tax_implications] TAX ANALYSIS for SELL at LOSS - PnL: ${pnl}",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'analyze_tax_implications'})
    
    # Step 1: Calculate tax implications
    tax_calc = calculate_tax_implications(symbol, pnl, quantity, trace_id, order_id)
    
    # Step 2: Check wash sale rule
    wash_sale_check = check_wash_sale_rule(symbol, quantity, trace_id, order_id)
    
    # Step 3: Verify cost basis accuracy
    cost_basis_verification = verify_cost_basis_accuracy(symbol, quantity, trace_id, order_id)
    
    result = {
        'order_id': order_id,
        'symbol': symbol,
        'pnl': pnl,
        'tax_calculation': tax_calc,
        'wash_sale_check': wash_sale_check,
        'cost_basis_verification': cost_basis_verification,
        'tax_benefit': tax_calc['estimated_tax_benefit'],
        'timestamp': datetime.utcnow().isoformat()
    }
    
    logger.info(f"[analyze_tax_implications] Tax analysis complete - Tax benefit: ${tax_calc['estimated_tax_benefit']}",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'analyze_tax_implications',
                      'extra_data': result})
    
    return result


def apply_volume_discount(quantity: int, base_price: float, trace_id: str, order_id: str) -> float:
    """
    Apply institutional volume discount for large orders.
    UNIQUE to Institutional workflow.
    """
    logger.info(f"[apply_volume_discount] Params - quantity: {quantity}, base_price: ${base_price:.2f}",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'apply_volume_discount'})
    
    # Volume-based discount tiers
    if quantity >= 10000:
        discount = 0.005  # 0.5% discount
    elif quantity >= 5000:
        discount = 0.003  # 0.3% discount
    elif quantity >= 1000:
        discount = 0.001  # 0.1% discount
    else:
        discount = 0.0
    
    discounted_price = base_price * (1 - discount)
    
    logger.info(f"[apply_volume_discount] Volume discount applied: {discount*100:.2f}%, Price: ${base_price:.2f} -> ${discounted_price:.2f}",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'apply_volume_discount'})
    
    return round(discounted_price, 2)


@app.post("/pricing/calculate-institutional")
async def calculate_institutional_pricing(request: Request):
    """
    WORKFLOW 2: Institutional Pricing Calculation
    Applies volume discounts and institutional commission rates.
    """
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    data = await request.json()
    
    order_id = data.get('order_id')
    symbol = data.get('symbol')
    quantity = data.get('quantity')
    order_type = OrderType(data.get('order_type'))
    
    get_trace_logger(trace_id)
    
    logger.info(f"[calculate_institutional_pricing] Params - order_id: {order_id}, symbol: {symbol}, quantity: {quantity}, order_type: {order_type.value}",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'calculate_institutional_pricing'})
    
    # Step 1: Get base market price
    base_price = get_market_price(symbol, order_type, trace_id, order_id)
    
    # Step 2: Apply volume discount (UNIQUE to institutional)
    institutional_price = apply_volume_discount(quantity, base_price, trace_id, order_id)
    
    # Step 3: Calculate costs with lower institutional commission (0.1% vs 0.5%)
    base_amount = quantity * institutional_price
    commission = base_amount * 0.001  # 0.1% for institutional
    
    if order_type == OrderType.BUY:
        fees = quantity * 0.01  # Lower regulatory fees
        total_cost = base_amount + commission + fees
    else:
        fees = quantity * 0.01
        total_cost = base_amount - commission - fees
    
    # Step 4: Calculate P&L
    estimated_pnl = calculate_estimated_pnl(symbol, quantity, institutional_price, order_type, trace_id, order_id)
    
    result = {
        'order_id': order_id,
        'symbol': symbol,
        'price': institutional_price,
        'base_price': base_price,
        'volume_discount': base_price - institutional_price,
        'estimated_pnl': estimated_pnl,
        'total_cost': round(total_cost, 2),
        'commission': round(commission, 2),
        'fees': round(fees, 2),
        'base_amount': round(base_amount, 2),
        'institutional_client': True,
        'timestamp': datetime.utcnow().isoformat()
    }
    
    logger.info(f"[calculate_institutional_pricing] Institutional pricing complete - Price: ${institutional_price}, Total: ${total_cost:.2f}",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'calculate_institutional_pricing'})
    
    return result


@app.post("/pricing/algo-fast")
async def calculate_algo_pricing(request: Request):
    """
    WORKFLOW 3: Fast Algo Pricing
    Lightweight pricing for high-frequency algo trading.
    """
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    data = await request.json()
    
    order_id = data.get('order_id')
    symbol = data.get('symbol')
    quantity = data.get('quantity')
    order_type = OrderType(data.get('order_type'))
    
    get_trace_logger(trace_id)
    
    logger.info(f"[calculate_algo_pricing] Params - order_id: {order_id}, symbol: {symbol}, quantity: {quantity}",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'calculate_algo_pricing'})
    
    # Fast pricing - skip validation chain for speed
    base_prices = {
        "AAPL": 175.50,
        "GOOGL": 140.25,
        "MSFT": 378.90,
        "AMZN": 152.75,
        "TSLA": 242.80,
        "META": 356.20,
        "NVDA": 495.60
    }
    
    price = base_prices.get(symbol, 100.0)
    
    # Minimal cost calculation
    base_amount = quantity * price
    commission = base_amount * 0.0001  # 0.01% for algo trading
    fees = quantity * 0.005  # Minimal fees
    
    if order_type == OrderType.BUY:
        total_cost = base_amount + commission + fees
    else:
        total_cost = base_amount - commission - fees
    
    result = {
        'order_id': order_id,
        'symbol': symbol,
        'price': price,
        'estimated_pnl': 0.0,  # Skip PnL for speed
        'total_cost': round(total_cost, 2),
        'commission': round(commission, 2),
        'fees': round(fees, 2),
        'base_amount': round(base_amount, 2),
        'algo_trading': True,
        'timestamp': datetime.utcnow().isoformat()
    }
    
    logger.info(f"[calculate_algo_pricing] Fast algo pricing complete - Price: ${price}",
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'calculate_algo_pricing'})
    
    return result


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)
