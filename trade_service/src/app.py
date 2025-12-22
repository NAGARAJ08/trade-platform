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
        # Include stack trace if exception info is present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
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
    Verify if trading market is currently open.
    
    Returns:
        bool: True if current time is within market hours, False otherwise
    
    Market Hours:
        - Opens: 9:30 AM local time
        - Closes: 11:00 PM local time (extended for demo purposes)
    
    Note:
        Uses local system time. Production systems should use
        exchange-specific timezone (typically US/Eastern)
    """
    current_time = datetime.now().time()
    market_open = time(9, 30)
    market_close = time(23, 0)
    
    return market_open <= current_time <= market_close


def validate_account_balance(quantity: int, price: float, symbol: str, order_type: OrderType, trace_id: str, order_id: str) -> tuple[bool, Optional[str]]:
    """
    Verify sufficient funds (BUY) or holdings (SELL) for order execution.
    
    Args:
        quantity: Number of shares to trade
        price: Estimated price per share
        symbol: Stock ticker symbol
        order_type: BUY or SELL
        trace_id: Trace ID for logging
        order_id: Order ID for logging
    
    Returns:
        tuple: (is_valid, error_message)
            - is_valid: True if sufficient balance/holdings, False otherwise
            - error_message: None if valid, error description if not
    
    Validation Logic:
        BUY: Checks if (quantity × price) ≤ account balance ($500K)
        SELL: Checks if quantity ≤ current holdings for the symbol
    
    Note:
        Uses estimated price for validation. Actual price may differ at execution
    """
    logger.info(f"[validate_account_balance] Validating account for {order_type} order", 
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'validate_account_balance'})
    
    if order_type == OrderType.BUY:
        # Check buying power for purchase
        account_balance = 500000  # $500K available
        required_amount = quantity * price
        
        logger.info(f"[validate_account_balance] BUY - Required: ${required_amount:.2f}, Available: ${account_balance:.2f}", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'validate_account_balance',
                          'extra_data': {'required': required_amount, 'available': account_balance}})
        
        if required_amount > account_balance:
            logger.error(f"[validate_account_balance] Insufficient buying power: need ${required_amount:.2f}, have ${account_balance:.2f}", 
                        extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'validate_account_balance'})
            return False, f"Insufficient buying power: ${required_amount:.2f} required, ${account_balance:.2f} available"
    else:
        # Check holdings for sale
        holdings = {"AAPL": 500, "GOOGL": 200, "MSFT": 800, "TSLA": 300, "NVDA": 300}
        current_holdings = holdings.get(symbol, 0)
        
        logger.info(f"[validate_account_balance] SELL - Current holdings: {current_holdings} shares of {symbol}", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'validate_account_balance',
                          'extra_data': {'symbol': symbol, 'holdings': current_holdings, 'sell_quantity': quantity}})
        
        if current_holdings < quantity:
            logger.error(f"[validate_account_balance] Insufficient shares: have {current_holdings}, trying to sell {quantity}", 
                        extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'validate_account_balance'})
            return False, f"Insufficient shares: have {current_holdings} shares, cannot sell {quantity}"
    
    logger.info("[validate_account_balance] Account validation passed", 
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'validate_account_balance'})
    return True, None


def validate_order_requirements(symbol: str, quantity: int, price: float, order_type: OrderType, trace_id: str, order_id: str) -> tuple[bool, Optional[str]]:
    """
    Validate all order-type specific requirements.
    
    Args:
        symbol: Stock ticker symbol
        quantity: Number of shares
        price: Estimated price per share
        order_type: BUY or SELL
        trace_id: Trace ID for logging
        order_id: Order ID for logging
    
    Returns:
        tuple: (is_valid, error_message)
            - is_valid: True if all requirements met, False otherwise
            - error_message: None if valid, error description if not
    
    Validations Performed:
        - Account balance/holdings verification
        - Order-type specific business rules
    """
    logger.info(f"[validate_order_requirements] Validating {order_type} order requirements", 
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'validate_order_requirements'})
    
    # Validate account balance/holdings
    is_valid, msg = validate_account_balance(quantity, price, symbol, order_type, trace_id, order_id)
    if not is_valid:
        return False, msg
    
    logger.info(f"[validate_order_requirements] {order_type} order validation passed", 
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'validate_order_requirements'})
    return True, None


def get_symbol_metadata(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve trading metadata for a stock symbol.
    
    Args:
        symbol: Stock ticker symbol
    
    Returns:
        dict or None: Symbol metadata if found, None otherwise
            Metadata includes:
                - 'exchange': Trading exchange (e.g., 'NASDAQ')
                - 'sector': Market sector
                - 'lot_size': Minimum trading lot size
                - 'max_order': Maximum order quantity allowed
    
    Example:
        >>> get_symbol_metadata('AAPL')
        {'exchange': 'NASDAQ', 'sector': 'Technology', 'lot_size': 1, 'max_order': 10000}
    """
    symbol_registry = {
        "AAPL": {"exchange": "NASDAQ", "sector": "Technology", "lot_size": 1, "max_order": 10000},
        "GOOGL": {"exchange": "NASDAQ", "sector": "Technology", "lot_size": 1, "max_order": 5000},
        "MSFT": {"exchange": "NASDAQ", "sector": "Technology", "lot_size": 1, "max_order": 10000},
        "AMZN": {"exchange": "NASDAQ", "sector": "Consumer", "lot_size": 1, "max_order": 5000},
        "TSLA": {"exchange": "NASDAQ", "sector": "Automotive", "lot_size": 1, "max_order": 3000},
        "META": {"exchange": "NASDAQ", "sector": "Technology", "lot_size": 1, "max_order": 5000},
        "NVDA": {"exchange": "NASDAQ", "sector": "Technology", "lot_size": 1, "max_order": 5000}
    }
    return symbol_registry.get(symbol)


def check_symbol_tradeable(symbol: str, trace_id: str, order_id: str) -> tuple[bool, Optional[str]]:
    """
    Verify if a symbol is tradeable and registered in the system.
    
    Args:
        symbol: Stock ticker symbol
        trace_id: Trace ID for logging
        order_id: Order ID for logging
    
    Returns:
        tuple: (is_tradeable, error_message)
            - is_tradeable: True if symbol is tradeable, False otherwise
            - error_message: None if tradeable, error description if not
    
    Checks:
        - Symbol exists in registry
        - Exchange information available
        - Trading is enabled for the symbol
    """
    logger.info(f"[check_symbol_tradeable] Checking tradeability for {symbol}", 
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'check_symbol_tradeable'})
    
    metadata = get_symbol_metadata(symbol)
    if not metadata:
        logger.error(f"[check_symbol_tradeable] Symbol {symbol} not found in registry", 
                    extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'check_symbol_tradeable'})
        return False, f"Symbol '{symbol}' is not supported for trading"
    
    # Check exchange status (simulated)
    exchange = metadata['exchange']
    logger.info(f"[check_symbol_tradeable] Symbol {symbol} found on {exchange} exchange", 
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'check_symbol_tradeable', 'extra_data': metadata})
    
    return True, None


def validate_symbol(symbol: str) -> bool:
    """
    Check if symbol is in the list of supported trading symbols.
    
    Args:
        symbol: Stock ticker symbol
    
    Returns:
        bool: True if symbol is supported, False otherwise
    
    Supported Symbols:
        AAPL, GOOGL, MSFT, AMZN, TSLA, META, NVDA
    """
    supported_symbols = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "META", "NVDA"]
    return symbol in supported_symbols


def normalize_quantity_to_lot_size(quantity: int, symbol: str, trace_id: str, order_id: str) -> int:
    """
    Adjust order quantity to meet exchange lot size requirements.
    
    Args:
        quantity: Requested number of shares
        symbol: Stock ticker symbol
        trace_id: Trace ID for logging
        order_id: Order ID for logging
    
    Returns:
        int: Normalized quantity (rounded down to nearest lot size multiple)
    
    Example:
        If lot_size = 10:
        - Input: 157 → Output: 150
        - Input: 100 → Output: 100 (no change)
    
    Note:
        Rounds DOWN to nearest lot size. Fractional shares are not supported.
        If symbol metadata unavailable, returns original quantity unchanged.
    """
    logger.info(f"[normalize_quantity_to_lot_size] Normalizing quantity {quantity} for {symbol}", 
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'normalize_quantity_to_lot_size'})
    
    metadata = get_symbol_metadata(symbol)
    if not metadata:
        logger.warning(f"[normalize_quantity_to_lot_size] No metadata for {symbol}, using quantity as-is", 
                      extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'normalize_quantity_to_lot_size'})
        return quantity
    
    lot_size = metadata['lot_size']
    if quantity % lot_size != 0:
        normalized = (quantity // lot_size) * lot_size
        logger.info(f"[normalize_quantity_to_lot_size] Adjusted quantity from {quantity} to {normalized} (lot size: {lot_size})", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'normalize_quantity_to_lot_size', 
                          'extra_data': {'original': quantity, 'normalized': normalized, 'lot_size': lot_size}})
        return normalized
    
    return quantity


def check_order_limits(quantity: int, symbol: str, trace_id: str, order_id: str) -> tuple[bool, Optional[str]]:
    """
    Validate order quantity against exchange and global limits.
    
    Args:
        quantity: Number of shares to trade
        symbol: Stock ticker symbol
        trace_id: Trace ID for logging
        order_id: Order ID for logging
    
    Returns:
        tuple: (is_valid, error_message)
            - is_valid: True if within limits, False otherwise
            - error_message: None if valid, error description if exceeded
    
    Limits Checked:
        1. Symbol-specific maximum (varies by symbol, typically 3K-10K shares)
        2. Global maximum: 10,000 shares per order
    
    Note:
        Global limit takes precedence if no symbol-specific metadata exists
    """
    logger.info(f"[check_order_limits] Checking limits for {quantity} shares of {symbol}", 
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'check_order_limits'})
    
    metadata = get_symbol_metadata(symbol)
    if metadata:
        max_order = metadata['max_order']
        if quantity > max_order:
            logger.warning(f"[check_order_limits] Order quantity {quantity} exceeds maximum {max_order} for {symbol}", 
                          extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'check_order_limits', 
                                 'extra_data': {'quantity': quantity, 'max_allowed': max_order}})
            return False, f"Order quantity {quantity} exceeds maximum allowed {max_order} for {symbol}"
    
    # Global limit check
    if quantity > 10000:
        logger.error(f"[check_order_limits] Order quantity {quantity} exceeds global maximum 10000", 
                    extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'check_order_limits'})
        return False, f"Order quantity {quantity} exceeds global maximum limit of 10000"
    
    logger.info(f"[check_order_limits] Order limits check passed", 
               extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'check_order_limits'})
    return True, None


def validate_quantity(quantity: int) -> int:
    """
    Perform basic quantity validation and normalization.
    
    Args:
        quantity: Requested order quantity
    
    Returns:
        int: Validated quantity, or error codes:
            - Returns quantity if valid (0 < quantity ≤ 10,000)
            - Returns 0 if quantity < 0
            - Returns -1 if quantity > 10,000 (exceeds maximum)
    
    Note:
        This is a simple validation. Use check_order_limits() for
        comprehensive limit checking with proper error messages.
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
def validate_trade(trade: TradeValidationRequest, request: Request):
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
    
    # Step 1: Check if symbol is tradeable
    logger.info("[validate_trade] Step 1: Checking symbol tradeability", 
               extra={'trace_id': trace_id, 'order_id': trade.order_id, 'function': 'validate_trade'})
    is_tradeable, reason = check_symbol_tradeable(trade.symbol, trace_id, trade.order_id)
    if not is_tradeable:
        logger.warning(f"[validate_trade] Symbol validation failed: {reason}", 
                      extra={'trace_id': trace_id, 'order_id': trade.order_id, 'function': 'validate_trade'})
        return TradeValidationResponse(
            valid=False,
            reason=reason,
            order_id=trade.order_id,
            normalized_quantity=trade.quantity,
            timestamp=timestamp
        )
    
    # Step 2: Check market hours
    logger.info("[validate_trade] Step 2: Checking market hours", 
               extra={'trace_id': trace_id, 'order_id': trade.order_id, 'function': 'validate_trade'})
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
    
    # Step 3: Validate order type specific requirements
    logger.info("[validate_trade] Step 3: Validating order type specific requirements", 
               extra={'trace_id': trace_id, 'order_id': trade.order_id, 'function': 'validate_trade'})
    
    # Basic quantity validation
    if trade.quantity <= 0:
        logger.error(f"[validate_trade] Invalid quantity: {trade.quantity}", 
                    extra={'trace_id': trace_id, 'order_id': trade.order_id, 'function': 'validate_trade'})
        return TradeValidationResponse(
            valid=False,
            reason=f"Quantity must be positive (received: {trade.quantity})",
            order_id=trade.order_id,
            normalized_quantity=trade.quantity,
            timestamp=timestamp
        )
    
    # Use estimated price for quick validation check
    # Full pricing calculation happens in pricing service during execution
    estimated_price = 175.0  # Standard reference price for validation
    
    logger.info(f"[validate_trade] Using estimated price ${estimated_price} for validation", 
               extra={'trace_id': trace_id, 'order_id': trade.order_id, 'function': 'validate_trade',
                      'extra_data': {'estimated_price': estimated_price, 'symbol': trade.symbol}})
    
    # Call generic validation function
    order_valid, validation_msg = validate_order_requirements(trade.symbol, trade.quantity, estimated_price, trade.order_type, trace_id, trade.order_id)
    
    if not order_valid:
        logger.warning(f"[validate_trade] Order validation failed: {validation_msg}", 
                      extra={'trace_id': trace_id, 'order_id': trade.order_id, 'function': 'validate_trade'})
        return TradeValidationResponse(
            valid=False,
            reason=validation_msg,
            order_id=trade.order_id,
            normalized_quantity=trade.quantity,
            timestamp=timestamp
        )
    
    # Normalize to lot size
    normalized_qty = normalize_quantity_to_lot_size(trade.quantity, trade.symbol, trace_id, trade.order_id)
    
    # Check order limits
    limits_ok, limit_reason = check_order_limits(normalized_qty, trade.symbol, trace_id, trade.order_id)
    if not limits_ok:
        logger.warning(f"[validate_trade] VALIDATION FAILED - {limit_reason}", extra={
            "trace_id": trace_id,
            "order_id": trade.order_id,
            "function": "validate_trade",
            "quantity": trade.quantity
        })
        return TradeValidationResponse(
            valid=False,
            reason=limit_reason,
            order_id=trade.order_id,
            normalized_quantity=normalized_qty,
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
def execute_trade(trade: TradeExecutionRequest, request: Request):
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
def get_trade(order_id: str, request: Request):
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
def list_trades(request: Request):
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