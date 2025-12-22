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
    timestamp: str


def get_trace_id(x_trace_id: Optional[str] = Header(None)) -> str:
    """Generate or use existing trace ID"""
    return x_trace_id or str(uuid.uuid4())


def get_market_price(symbol: str, scenario: Optional[str] = None) -> float:
    """
    Retrieve current market price for a trading symbol with simulated variance.
    
    Args:
        symbol: Stock ticker symbol (e.g., 'AAPL', 'NVDA')
        scenario: Optional scenario identifier (reserved for future use)
    
    Returns:
        float: Current market price rounded to 2 decimal places
    
    Raises:
        ValueError: If symbol is not found in supported symbols list
    
    Note:
        - Applies ±2% random variance to base price for realistic market simulation
        - Simulates real-time price fluctuations between service calls
        - Used for both validation and execution pricing
    """
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
    price = base_price * (1 + variance)
    
    return round(price, 2)


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
        
        BUG: Large SELL orders (>200 shares) of TSLA/NVDA incorrectly apply
        2% extra fee instead of 0.2%
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
        
        return {'base_amount': base_cost, 'commission': commission, 'fees': exchange_fee, 'total_cost': total_cost}
    else:  # SELL
        gross_proceeds = quantity * price
        commission = gross_proceeds * 0.005  # 0.5%
        sec_fee = gross_proceeds * 0.0000207  # SEC fee
        
        # Bug: For large SELL orders of certain stocks, extra fee applied incorrectly
        if quantity > 200 and symbol in ["TSLA", "NVDA"]:
            logger.warning(f"[calculate_total_cost] Large SELL order of {symbol}, applying additional processing fee", 
                          extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'calculate_total_cost'})
            # BUG: This fee is too high!
            extra_fee = gross_proceeds * 0.02  # 2% extra (should be 0.2%)
            commission += extra_fee
        
        net_proceeds = gross_proceeds - commission - sec_fee
        
        logger.info(f"[calculate_total_cost] SELL proceeds breakdown - Gross: ${gross_proceeds:.2f}, Commission: ${commission:.2f}, SEC Fee: ${sec_fee:.2f}, Net: ${net_proceeds:.2f}", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'calculate_total_cost',
                          'extra_data': {'gross_proceeds': gross_proceeds, 'commission': commission, 'sec_fee': sec_fee, 'net_proceeds': net_proceeds}})
        
        return {'base_amount': gross_proceeds, 'commission': commission, 'fees': sec_fee, 'total_cost': net_proceeds}


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


def calculate_commission(quantity: int, price: float, order_type: OrderType, trace_id: str, order_id: str) -> float:
    """
    Calculate trading commission with volume-based discount tiers.
    
    Args:
        quantity: Number of shares
        price: Price per share
        order_type: BUY or SELL (currently unused)
        trace_id: Trace ID for logging
        order_id: Order ID for logging
    
    Returns:
        float: Commission amount rounded to 2 decimal places
    
    Commission Tiers:
        - Order value > $100,000: 0.2% commission
        - Order value > $50,000: 0.3% commission
        - Order value ≤ $50,000: 0.5% commission (base rate)
    
    Note:
        Early rounding may cause precision loss on large orders
    """
    logger.info("[calculate_commission] Calculating commission", 
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'calculate_commission'})
    
    base_commission = 0.005  # 0.5% base rate
    order_value = quantity * price
    
    logger.info(f"[calculate_commission] Order value: ${order_value:.2f}", 
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'calculate_commission',
                      'extra_data': {'order_value': order_value, 'quantity': quantity, 'price': price}})
    
    # Volume-based discount tiers
    if order_value > 100000:
        commission_rate = 0.002  # 0.2% for large orders
        logger.info("[calculate_commission] Applied large order discount (0.2%)", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'calculate_commission'})
    elif order_value > 50000:
        commission_rate = 0.003  # 0.3% for medium orders
        logger.info("[calculate_commission] Applied medium order discount (0.3%)", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'calculate_commission'})
    else:
        commission_rate = base_commission
    
    commission = order_value * commission_rate
    
    # Round commission to 2 decimal places for standard currency representation
    commission_rounded = round(commission, 2)
    
    logger.info(f"[calculate_commission] Commission calculated: ${commission_rounded:.2f} ({commission_rate*100}% of ${order_value:.2f})", 
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'calculate_commission', 
                      'extra_data': {'commission_before_rounding': commission, 'commission_final': commission_rounded, 'rate': commission_rate}})
    
    return commission_rounded


def estimate_slippage(quantity: int, symbol: str, order_type: OrderType, trace_id: str, order_id: str) -> float:
    """
    Estimate price slippage based on order size and symbol volatility.
    
    Args:
        quantity: Number of shares
        symbol: Stock ticker symbol
        order_type: BUY or SELL (currently unused)
        trace_id: Trace ID for logging
        order_id: Order ID for logging
    
    Returns:
        float: Estimated slippage as a decimal percentage (e.g., 0.015 = 1.5%)
    
    Slippage Factors:
        - Volatile symbols (TSLA, NVDA, META) have higher base slippage
        - Quantity > 1000: 2x base slippage
        - Quantity > 500: 1.5x base slippage
        - Quantity ≤ 500: 1x base slippage
    
    Note:
        Slippage represents expected price movement during order execution
    """
    logger.info(f"[estimate_slippage] Estimating slippage for {quantity} shares of {symbol}", 
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'estimate_slippage'})
    
    # Volatile stocks have higher slippage
    volatile_symbols = {"TSLA": 0.015, "NVDA": 0.01, "META": 0.008}
    base_slippage = volatile_symbols.get(symbol, 0.005)
    
    # Quantity impacts slippage
    if quantity > 1000:
        slippage = base_slippage * 2.0
        logger.warning(f"[estimate_slippage] High slippage expected for large order: {slippage*100:.2f}%", 
                      extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'estimate_slippage'})
    elif quantity > 500:
        slippage = base_slippage * 1.5
    else:
        slippage = base_slippage
    
    logger.info(f"[estimate_slippage] Estimated slippage: {slippage*100:.2f}%", 
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'estimate_slippage', 
                      'extra_data': {'slippage_pct': slippage}})
    
    return slippage


def adjust_price_for_slippage(price: float, slippage: float, order_type: OrderType) -> float:
    """
    Apply slippage adjustment to execution price.
    
    Args:
        price: Original market price
        slippage: Slippage percentage as decimal (e.g., 0.015 for 1.5%)
        order_type: BUY or SELL
    
    Returns:
        float: Adjusted price rounded to 2 decimal places
    
    Price Adjustment:
        - BUY: price increases (unfavorable for buyer)
        - SELL: price decreases (unfavorable for seller)
    
    Note:
        Slippage always works against the trader to simulate real market conditions
    """
    if order_type == OrderType.BUY:
        # Buying: price goes up (unfavorable)
        adjusted_price = price * (1 + slippage)
    else:  # SELL
        # Selling: price goes down (unfavorable)
        adjusted_price = price * (1 - slippage)
    
    return round(adjusted_price, 2)


def calculate_pnl(symbol: str, quantity: int, current_price: float, order_type: OrderType) -> float:
    """
    Calculate estimated profit/loss (simplified version for backward compatibility)
    """
    cost_basis = get_cost_basis(symbol)
    
    if order_type == OrderType.BUY:
        pnl = -(current_price - cost_basis) * quantity
    else:  # SELL
        pnl = (current_price - cost_basis) * quantity
    
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
        # Get market price
        logger.info(f"[calculate_pnl] get_market_price for symbol: {request_data.symbol}", extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'function': 'get_market_price'})
        current_price = get_market_price(request_data.symbol)
        
        logger.info(f"[get_market_price] Market price retrieved: ${current_price}", extra={
            "trace_id": trace_id,
            "order_id": request_data.order_id,
            "function": "get_market_price",
            "symbol": request_data.symbol,
            "price": current_price
        })
    except ValueError as e:
        logger.error(f"[get_market_price] Market data unavailable for symbol: {request_data.symbol}", extra={
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


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)
