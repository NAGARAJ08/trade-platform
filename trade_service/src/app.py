import logging
import json
import uuid
from datetime import datetime, time
from typing import Optional, Dict, Any
from enum import Enum

from fastapi import FastAPI, HTTPException, Header, Request
from pydantic import BaseModel, Field
import uvicorn

# Custom JSON formatter for Splunk-style logs
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "service": "trade_service",
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
file_handler = logging.FileHandler('../logs/trade_service.log')
file_handler.setFormatter(JsonFormatter())

# Console handler with readable format
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - trade_service - %(message)s'))

logger.addHandler(file_handler)
logger.addHandler(console_handler)

# FastAPI app
app = FastAPI(
    title="Trade Service",
    description="Handles trade validation and execution",
    version="1.0.0"
)

# In-memory storage for trades
trades_db: Dict[str, Dict[str, Any]] = {}


class OrderType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class TradeValidationRequest(BaseModel):
    order_id: str
    symbol: str = Field(..., example="AAPL")
    quantity: int = Field(..., gt=0)
    order_type: OrderType
    scenario: Optional[str] = None


class TradeExecutionRequest(BaseModel):
    order_id: str
    symbol: str
    quantity: int
    price: float
    order_type: OrderType


class TradeValidationResponse(BaseModel):
    valid: bool
    reason: Optional[str] = None
    order_id: str
    timestamp: str


class TradeExecutionResponse(BaseModel):
    order_id: str
    status: str
    execution_time: str
    symbol: str
    quantity: int
    price: float


def get_trace_id(x_trace_id: Optional[str] = Header(None)) -> str:
    """Generate or use existing trace ID"""
    return x_trace_id or str(uuid.uuid4())


def is_market_open(scenario: Optional[str] = None) -> bool:
    """
    Check if market is open (dummy implementation)
    Market hours: 9:30 AM - 4:00 PM (simulated)
    """
    if scenario == "market_closed":
        return False
    
    # Dummy check: consider market open between 9 AM and 4 PM
    current_time = datetime.now().time()
    market_open = time(9, 0)
    market_close = time(23, 0)
    
    # For demo purposes, let's say market is always "open" unless scenario says otherwise
    return market_open <= current_time <= market_close or scenario == "success"


def validate_symbol(symbol: str, scenario: Optional[str] = None) -> bool:
    """Validate if symbol is supported"""
    # Calculation errors should occur in Pricing Service, not here
    # Trade Service only validates if symbol exists in supported list
    supported_symbols = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "META", "NVDA"]
    return symbol in supported_symbols


def validate_quantity(quantity: int) -> bool:
    """Validate quantity constraints"""
    # Quantity must be positive and less than 10000
    return 0 < quantity < 10000


@app.get("/")
def root():
    """Root endpoint"""
    return {"message": "Trade Service", "docs": "/docs"}


@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "trade_service"}


@app.post("/trades/validate", response_model=TradeValidationResponse)
async def validate_trade(trade: TradeValidationRequest, request: Request):
    """
    Validate a trade before execution
    Checks: market hours, symbol validity, quantity constraints
    """
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    
    logger.info("========== TRADE VALIDATION REQUEST RECEIVED ==========", extra={'trace_id': trace_id, 'order_id': trade.order_id})
    logger.info(f"Validating trade - Symbol: {trade.symbol}, Quantity: {trade.quantity}, Type: {trade.order_type}, Scenario: {trade.scenario}", extra={
        "trace_id": trace_id,
        "order_id": trade.order_id,
        "symbol": trade.symbol,
        "quantity": trade.quantity,
        "order_type": trade.order_type
    })
    
    timestamp = datetime.now().isoformat()
    
    # Check market hours
    logger.info("Checking market hours...", extra={'trace_id': trace_id, 'order_id': trade.order_id})
    market_open = is_market_open(trade.scenario)
    logger.info(f"Market status: {'OPEN' if market_open else 'CLOSED'}", extra={'trace_id': trace_id, 'order_id': trade.order_id, 'extra_data': {'market_open': market_open}})
    
    if not market_open:
        logger.warning("VALIDATION FAILED - Market is currently closed", extra={
            "trace_id": trace_id,
            "order_id": trade.order_id,
            'extra_data': {'reason': 'market_closed', 'trading_hours': '9:00 AM - 4:00 PM'}
        })
        return TradeValidationResponse(
            valid=False,
            reason="Market is currently closed. Trading hours: 9:00 AM - 4:00 PM",
            order_id=trade.order_id,
            timestamp=timestamp
        )
    
    # Validate symbol
    logger.info(f"Validating symbol: {trade.symbol}", extra={'trace_id': trace_id, 'order_id': trade.order_id})
    symbol_valid = validate_symbol(trade.symbol, trade.scenario)
    logger.info(f"Symbol validation result: {'VALID' if symbol_valid else 'INVALID'}", 
               extra={'trace_id': trace_id, 'order_id': trade.order_id, 'extra_data': {'symbol': trade.symbol, 'valid': symbol_valid}})
    
    if not symbol_valid:
        logger.warning(f"VALIDATION FAILED - Symbol '{trade.symbol}' is not supported", extra={
            "trace_id": trace_id,
            "order_id": trade.order_id,
            "symbol": trade.symbol,
            'extra_data': {'supported_symbols': ['AAPL', 'GOOGL', 'MSFT', 'AMZN', 'TSLA', 'META', 'NVDA']}
        })
        return TradeValidationResponse(
            valid=False,
            reason=f"Symbol '{trade.symbol}' is not supported or invalid",
            order_id=trade.order_id,
            timestamp=timestamp
        )
    
    # Validate quantity
    logger.info(f"Validating quantity: {trade.quantity}", extra={'trace_id': trace_id, 'order_id': trade.order_id})
    quantity_valid = validate_quantity(trade.quantity)
    logger.info(f"Quantity validation result: {'VALID' if quantity_valid else 'INVALID'}", 
               extra={'trace_id': trace_id, 'order_id': trade.order_id, 'extra_data': {'quantity': trade.quantity, 'valid': quantity_valid, 'max_allowed': 9999}})
    
    if not quantity_valid:
        logger.warning(f"VALIDATION FAILED - Quantity {trade.quantity} exceeds allowed limits", extra={
            "trace_id": trace_id,
            "order_id": trade.order_id,
            "quantity": trade.quantity,
            'extra_data': {'reason': 'quantity_out_of_range', 'max_allowed': 9999, 'min_allowed': 1}
        })
        return TradeValidationResponse(
            valid=False,
            reason=f"Quantity {trade.quantity} is outside acceptable range (1-9999)",
            order_id=trade.order_id,
            timestamp=timestamp
        )
    
    logger.info("========== TRADE VALIDATION SUCCESSFUL ==========", extra={
        "trace_id": trace_id,
        "order_id": trade.order_id,
        'extra_data': {'symbol': trade.symbol, 'quantity': trade.quantity, 'order_type': trade.order_type.value}
    })
    
    return TradeValidationResponse(
        valid=True,
        reason=None,
        order_id=trade.order_id,
        timestamp=timestamp
    )


@app.post("/trades/execute", response_model=TradeExecutionResponse)
async def execute_trade(trade: TradeExecutionRequest, request: Request):
    """
    Execute a validated trade
    """
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    
    logger.info("========== TRADE EXECUTION REQUEST RECEIVED ==========", extra={'trace_id': trace_id, 'order_id': trade.order_id})
    logger.info(f"Executing trade - Symbol: {trade.symbol}, Quantity: {trade.quantity}, Price: ${trade.price}, Type: {trade.order_type}", extra={
        "trace_id": trace_id,
        "order_id": trade.order_id,
        "symbol": trade.symbol,
        "quantity": trade.quantity,
        "price": trade.price
    })
    
    execution_time = datetime.now().isoformat()
    
    # Store trade in database
    logger.info("Storing trade in database...", extra={'trace_id': trace_id, 'order_id': trade.order_id})
    trades_db[trade.order_id] = {
        "order_id": trade.order_id,
        "symbol": trade.symbol,
        "quantity": trade.quantity,
        "price": trade.price,
        "order_type": trade.order_type.value,
        "status": "EXECUTED",
        "execution_time": execution_time
    }
    
    logger.info("========== TRADE EXECUTED SUCCESSFULLY ==========", extra={
        "trace_id": trace_id,
        "order_id": trade.order_id,
        'extra_data': {
            "status": "EXECUTED",
            "execution_time": execution_time,
            "symbol": trade.symbol,
            "quantity": trade.quantity,
            "price": trade.price,
            "total_value": trade.quantity * trade.price
        }
    })
    
    return TradeExecutionResponse(
        order_id=trade.order_id,
        status="EXECUTED",
        execution_time=execution_time,
        symbol=trade.symbol,
        quantity=trade.quantity,
        price=trade.price
    )


@app.get("/trades/{order_id}")
async def get_trade(order_id: str, request: Request):
    """Get trade details by order ID"""
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    
    logger.info("Fetching trade details", extra={
        "trace_id": trace_id,
        "order_id": order_id
    })
    
    trade = trades_db.get(order_id)
    if not trade:
        logger.warning("Trade not found", extra={
            "trace_id": trace_id,
            "order_id": order_id
        })
        raise HTTPException(status_code=404, detail="Trade not found")
    
    return trade


@app.get("/trades")
async def list_trades(request: Request):
    """List all trades"""
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    
    logger.info("Listing all trades", extra={
        "trace_id": trace_id,
        "count": len(trades_db)
    })
    
    return {"trades": list(trades_db.values()), "count": len(trades_db)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)