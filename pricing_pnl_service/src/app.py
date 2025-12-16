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

# File handler with JSON format
file_handler = logging.FileHandler('../logs/pricing_pnl_service.log')
file_handler.setFormatter(JsonFormatter())

# Console handler with readable format
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - pricing_pnl_service - %(message)s'))

logger.addHandler(file_handler)
logger.addHandler(console_handler)

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
async def calculate_pricing(request_data: PricingRequest, request: Request):
    """
    Calculate pricing and estimated PnL for an order
    This combines pricing lookup and PnL estimation
    """
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    
    logger.info("========== PRICING CALCULATION REQUEST RECEIVED ==========", extra={'trace_id': trace_id, 'order_id': request_data.order_id})
    logger.info(f"Calculating pricing for - Symbol: {request_data.symbol}, Quantity: {request_data.quantity}, Type: {request_data.order_type}", extra={
        "trace_id": trace_id,
        "order_id": request_data.order_id,
        "symbol": request_data.symbol,
        "quantity": request_data.quantity
    })
    
    try:
        # Get market price
        logger.info(f"Fetching market price for symbol: {request_data.symbol}", extra={'trace_id': trace_id, 'order_id': request_data.order_id})
        current_price = get_market_price(request_data.symbol)
        
        logger.info(f"Market price retrieved: ${current_price}", extra={
            "trace_id": trace_id,
            "order_id": request_data.order_id,
            "symbol": request_data.symbol,
            "price": current_price
        })
    except ValueError as e:
        logger.error(f"Market data unavailable for symbol: {request_data.symbol}", extra={
            "trace_id": trace_id,
            "order_id": request_data.order_id,
            "symbol": request_data.symbol,
            "error": str(e)
        })
        raise HTTPException(status_code=404, detail=f"Unable to retrieve market price for symbol '{request_data.symbol}'. Symbol not found in market data feed.")
    
    try:
        order_value = current_price * request_data.quantity
        
        logger.info(f"Calculating total order value: {request_data.quantity} x ${current_price} = ${order_value}", 
                   extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'extra_data': {'order_value': order_value}})
        
        # Apply bulk order pricing adjustment
        if request_data.quantity > 500:
            adjusted_multiplier = 0.98
            order_value = order_value * adjusted_multiplier
            
            logger.info(f"Applied bulk pricing adjustment: final value ${order_value:.2f}", extra={
                'trace_id': trace_id,
                'order_id': request_data.order_id,
                'extra_data': {'adjusted_value': order_value}
            })
        
        logger.info(f"Order value ${order_value:.2f} calculated successfully", 
                   extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'extra_data': {'order_value': order_value}})
        
        # Calculate PnL
        logger.info("Calculating estimated profit/loss (PnL)", extra={'trace_id': trace_id, 'order_id': request_data.order_id})
        cost_basis = get_cost_basis(request_data.symbol)
        logger.info(f"Cost basis for {request_data.symbol}: ${cost_basis}", 
                   extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'extra_data': {'cost_basis': cost_basis}})
        
        estimated_pnl = calculate_pnl(
            request_data.symbol,
            request_data.quantity,
            current_price,
            request_data.order_type
        )
        logger.info(f"Estimated PnL calculated: ${estimated_pnl} ({request_data.order_type} order)", 
                   extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'extra_data': {'estimated_pnl': estimated_pnl, 'order_type': request_data.order_type.value}})
        
        # Calculate total cost
        total_cost = current_price * request_data.quantity
        logger.info(f"Total order cost: ${total_cost}", 
                   extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'extra_data': {'total_cost': total_cost}})
        
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
        
        logger.info("========== PRICING CALCULATION COMPLETED ==========", extra={
            "trace_id": trace_id,
            "order_id": request_data.order_id,
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
        logger.error("Unexpected error in pricing calculation", extra={
            "trace_id": trace_id,
            "order_id": request_data.order_id,
            "error": str(e)
        })
        raise HTTPException(status_code=500, detail=f"Pricing calculation failed: {str(e)}")


@app.get("/pricing/{order_id}")
async def get_pricing(order_id: str, request: Request):
    """Get pricing data for a specific order"""
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    
    logger.info("Fetching pricing data", extra={
        "trace_id": trace_id,
        "order_id": order_id
    })
    
    pricing = pricing_data.get(order_id)
    if not pricing:
        logger.warning("Pricing data not found", extra={
            "trace_id": trace_id,
            "order_id": order_id
        })
        raise HTTPException(status_code=404, detail="Pricing data not found")
    
    return pricing


@app.get("/pricing/symbol/{symbol}")
async def get_current_price(symbol: str, request: Request):
    """Get current market price for a symbol"""
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    
    logger.info("Fetching current price", extra={
        "trace_id": trace_id,
        "symbol": symbol
    })
    
    try:
        price = get_market_price(symbol)
        return {
            "symbol": symbol,
            "price": price,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error("Error fetching price", extra={
            "trace_id": trace_id,
            "symbol": symbol,
            "error": str(e)
        })
        raise HTTPException(status_code=500, detail="Unable to fetch price")


@app.get("/pnl/{order_id}")
async def get_pnl(order_id: str, request: Request):
    """Get PnL data for a specific order"""
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    
    logger.info("Fetching PnL data", extra={
        "trace_id": trace_id,
        "order_id": order_id
    })
    
    pricing = pricing_data.get(order_id)
    if not pricing:
        logger.warning("PnL data not found", extra={
            "trace_id": trace_id,
            "order_id": order_id
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
