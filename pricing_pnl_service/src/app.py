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
    Get current market price for a symbol
    Returns mock prices with some variance
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
    
    # Add some variance (±2%)
    variance = random.uniform(-0.02, 0.02)
    price = base_price * (1 + variance)
    
    return round(price, 2)


def get_cost_basis(symbol: str) -> float:
    """
    Get cost basis for PnL calculation
    This represents the average purchase price
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


def calculate_pnl(symbol: str, quantity: int, current_price: float, order_type: OrderType) -> float:
    """
    Calculate estimated profit/loss
    For BUY orders: negative (cost to buy)
    For SELL orders: positive (gain from selling)
    """
    cost_basis = get_cost_basis(symbol)
    
    # Bug: For large SELL orders, accidentally use inflated cost basis
    if order_type == OrderType.SELL and quantity > 200:
        cost_basis = cost_basis * 1.8  # Wrong calculation!
    
    if order_type == OrderType.BUY:
        # PnL is negative (we're spending money to buy)
        pnl = -(current_price - cost_basis) * quantity
    else:  # SELL
        # PnL is positive (we're making money from selling)
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
        
        # Calculate PnL
        logger.info("[calculate_pnl] Calculating estimated profit/loss (PnL)", extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'function': 'calculate_pnl'})
        cost_basis = get_cost_basis(request_data.symbol)
        logger.info(f"[get_cost_basis] Cost basis for {request_data.symbol}: ${cost_basis}", 
                   extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'function': 'get_cost_basis', 'extra_data': {'cost_basis': cost_basis}})
        
        estimated_pnl = calculate_pnl(
            request_data.symbol,
            request_data.quantity,
            current_price,
            request_data.order_type
        )
        logger.info(f"[calculate_pnl] Estimated PnL calculated: ${estimated_pnl} ({request_data.order_type} order)", 
                   extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'function': 'calculate_pnl', 'extra_data': {'estimated_pnl': estimated_pnl, 'order_type': request_data.order_type.value}})
        
        # Calculate total cost
        total_cost = current_price * request_data.quantity
        logger.info(f"[calculate_pnl] Total order cost: ${total_cost}", 
                   extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'function': 'calculate_pnl', 'extra_data': {'total_cost': total_cost}})
        
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
        logger.error("[calculate_pnl] Unexpected error in pricing calculation", extra={
            "trace_id": trace_id,
            "order_id": request_data.order_id,
            "function": "calculate_pnl",
            "error": str(e)
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
        logger.error("[get_current_price] Error fetching price", extra={
            "trace_id": trace_id,
            "symbol": symbol,
            "function": "get_current_price",
            "error": str(e)
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
