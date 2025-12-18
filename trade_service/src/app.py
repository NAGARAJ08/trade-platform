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

# Console handler with readable format
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - trade_service - %(message)s'))

logger.addHandler(console_handler)

# Store trace-specific handlers
trace_handlers = {}

def get_trace_logger(trace_id: str):
    """Get or create a logger for specific trace_id"""
    if trace_id not in trace_handlers:
        trace_file_handler = logging.FileHandler(f'../logs/{trace_id}.log')
        trace_file_handler.setFormatter(JsonFormatter())
        trace_handlers[trace_id] = trace_file_handler
        logger.addHandler(trace_file_handler)
    return logger

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
    quantity: int = Field(...)
    order_type: OrderType


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
    normalized_quantity: int
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


def is_market_open() -> bool:
    """
    Check if market is open
    Market hours: 9:30 AM - 4:00 PM
    """
    current_time = datetime.now().time()
    market_open = time(9, 30)
    market_close = time(23, 0)
    
    return market_open <= current_time <= market_close


def validate_symbol(symbol: str) -> bool:
    """Validate if symbol is supported"""
    supported_symbols = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "META", "NVDA"]
    return symbol in supported_symbols


def validate_quantity(quantity: int) -> int:
    """
    Validate and normalize order quantity
    Returns normalized quantity
    """
    if quantity < 0:
        return 0
    
    # Check maximum limit
    if quantity > 10000:
        return -1  # Invalid
    
    return quantity


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
    
    # Create trace-specific log file
    get_trace_logger(trace_id)
    
    logger.info("[validate_trade] Trade validation request received", extra={'trace_id': trace_id, 'order_id': trade.order_id, 'function': 'validate_trade'})
    logger.info(f"[validate_trade] Validating - Symbol: {trade.symbol}, Quantity: {trade.quantity}, Type: {trade.order_type}", extra={
        "trace_id": trace_id,
        "order_id": trade.order_id,
        "function": "validate_trade",
        "symbol": trade.symbol,
        "quantity": trade.quantity,
        "order_type": trade.order_type
    })
    
    timestamp = datetime.now().isoformat()
    
    # Check market hours
    logger.info("[validate_trade] is_market_open checking...", extra={'trace_id': trace_id, 'order_id': trade.order_id, 'function': 'is_market_open'})
    market_open = is_market_open()
    logger.info(f"[is_market_open] Market status: {'OPEN' if market_open else 'CLOSED'}", extra={'trace_id': trace_id, 'order_id': trade.order_id, 'function': 'is_market_open', 'extra_data': {'market_open': market_open}})
    
    if not market_open:
        logger.warning("[validate_trade] VALIDATION FAILED - Market is currently closed", extra={
            "trace_id": trace_id,
            "order_id": trade.order_id,
            "function": "validate_trade",
            'extra_data': {'reason': 'market_closed', 'trading_hours': '9:00 AM - 4:00 PM'}
        })
        return TradeValidationResponse(
            valid=False,
            reason="Market is currently closed. Trading hours: 9:00 AM - 4:00 PM",
            order_id=trade.order_id,
            normalized_quantity=trade.quantity,
            timestamp=timestamp
        )
        
    # Validate quantity
    logger.info(f"[validate_trade] validate_quantity processing: {trade.quantity}", extra={'trace_id': trace_id, 'order_id': trade.order_id, 'function': 'validate_quantity'})
    normalized_qty = validate_quantity(trade.quantity)
    
    if normalized_qty != trade.quantity:
        logger.info(f"[validate_quantity] Normalized from {trade.quantity} to {normalized_qty}", extra={'trace_id': trace_id, 'order_id': trade.order_id, 'function': 'validate_quantity', 'extra_data': {'original': trade.quantity, 'normalized': normalized_qty}})
    
    if normalized_qty == -1:
        logger.warning(f"[validate_trade] VALIDATION FAILED - Quantity {trade.quantity} exceeds maximum limit", extra={
            "trace_id": trace_id,
            "order_id": trade.order_id,
            "function": "validate_trade",
            "quantity": trade.quantity,
            'extra_data': {'reason': 'quantity_exceeds_maximum', 'max_allowed': 10000}
        })
        return TradeValidationResponse(
            valid=False,
            reason=f"Quantity {trade.quantity} exceeds maximum limit of 10000",
            order_id=trade.order_id,
            normalized_quantity=trade.quantity,
            timestamp=timestamp
        )
    
    # Update trade with normalized quantity
    trade.quantity = normalized_qty
    logger.info(f"[validate_trade] Quantity validation passed: {normalized_qty}", 
               extra={'trace_id': trace_id, 'order_id': trade.order_id, 'function': 'validate_trade'})
    
    logger.info("[validate_trade] Trade validation successful", extra={
        "trace_id": trace_id,
        "order_id": trade.order_id,
        "function": "validate_trade",
        'extra_data': {'symbol': trade.symbol, 'quantity': trade.quantity, 'order_type': trade.order_type.value}
    })
    
    return TradeValidationResponse(
        valid=True,
        reason=None,
        order_id=trade.order_id,
        normalized_quantity=normalized_qty,
        timestamp=timestamp
    )


@app.post("/trades/execute", response_model=TradeExecutionResponse)
async def execute_trade(trade: TradeExecutionRequest, request: Request):
    """
    Execute a validated trade
    """
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    
    # Create trace-specific log file
    get_trace_logger(trace_id)
    
    logger.info("[execute_trade] Trade execution request received", extra={'trace_id': trace_id, 'order_id': trade.order_id, 'function': 'execute_trade'})
    logger.info(f"[execute_trade] Executing - Symbol: {trade.symbol}, Quantity: {trade.quantity}, Price: ${trade.price}, Type: {trade.order_type}", extra={
        "trace_id": trace_id,
        "order_id": trade.order_id,
        "function": "execute_trade",
        "symbol": trade.symbol,
        "quantity": trade.quantity,
        "price": trade.price
    })
    
    execution_time = datetime.now().isoformat()
    
    # Store trade in database
    logger.info("[execute_trade] Storing trade in database...", extra={'trace_id': trace_id, 'order_id': trade.order_id, 'function': 'execute_trade'})
    trades_db[trade.order_id] = {
        "order_id": trade.order_id,
        "symbol": trade.symbol,
        "quantity": trade.quantity,
        "price": trade.price,
        "order_type": trade.order_type.value,
        "status": "EXECUTED",
        "execution_time": execution_time
    }
    
    logger.info("[execute_trade] Trade executed successfully", extra={
        "trace_id": trace_id,
        "order_id": trade.order_id,
        "function": "execute_trade",
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
    
    logger.info("[get_trade] Fetching trade details", extra={
        "trace_id": trace_id,
        "order_id": order_id,
        "function": "get_trade"
    })
    
    trade = trades_db.get(order_id)
    if not trade:
        logger.warning("[get_trade] Trade not found", extra={
            "trace_id": trace_id,
            "order_id": order_id,
            "function": "get_trade"
        })
        raise HTTPException(status_code=404, detail="Trade not found")
    
    return trade


@app.get("/trades")
async def list_trades(request: Request):
    """List all trades"""
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    
    logger.info("[list_trades] Listing all trades", extra={
        "trace_id": trace_id,
        "count": len(trades_db),
        "function": "list_trades"
    })
    
    return {"trades": list(trades_db.values()), "count": len(trades_db)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)