import logging
import json
import uuid
import time as time_module
from datetime import datetime, time
from typing import Optional, Dict, Any
from enum import Enum

from fastapi import FastAPI, HTTPException, Header, Request
from pydantic import BaseModel, Field
import requests
import uvicorn

# Custom JSON formatter for Splunk-style logs
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "service": "orchestrator",
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
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - orchestrator - %(message)s'))

logger.addHandler(console_handler)

# Store trace-specific handlers
trace_handlers = {}

# FastAPI app
app = FastAPI(
    title="Trade Orchestrator Service",
    description="Orchestrates trade execution across multiple microservices",
    version="1.0.0"
)

# Service URLs - Always use localhost
TRADE_SERVICE_URL = "http://localhost:8001"
PRICING_PNL_SERVICE_URL = "http://localhost:8002"
RISK_SERVICE_URL = "http://localhost:8003"


class OrderType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderRequest(BaseModel):
    symbol: str = Field(..., example="AAPL")
    quantity: int = Field(..., example=100)
    order_type: OrderType = Field(..., example="BUY")


class OrderResponse(BaseModel):
    order_id: str
    status: str
    message: str
    trace_id: str
    latency_ms: Optional[int] = None
    details: Optional[Dict[str, Any]] = None


def get_trace_id(x_trace_id: Optional[str] = Header(None)) -> str:
    """
    Generate or retrieve trace ID for request tracking.
    
    Args:
        x_trace_id: Optional trace ID from request header 'X-Trace-Id'
    
    Returns:
        str: Existing trace ID from header or newly generated UUID
    
    Note:
        Trace IDs enable end-to-end tracking of requests across all microservices
    """
    return x_trace_id or str(uuid.uuid4())


class TraceFilter(logging.Filter):
    """Filter logs by trace_id"""
    def __init__(self, trace_id):
        super().__init__()
        self.trace_id = trace_id
    
    def filter(self, record):
        return hasattr(record, 'trace_id') and record.trace_id == self.trace_id

def get_trace_logger(trace_id: str):
    """
    Get or create a trace-specific file logger for structured logging.
    
    Args:
        trace_id: Unique trace identifier for the request
    
    Returns:
        logging.Logger: Configured logger instance with trace-specific file handler
    
    Side Effects:
        - Creates a new log file at '../logs/{trace_id}.log' if not exists
        - Adds a TraceFilter to only log events matching this trace_id
        - Configures JsonFormatter for structured JSON output
    """
    if trace_id not in trace_handlers:
        trace_file_handler = logging.FileHandler(f'../logs/{trace_id}.log')
        trace_file_handler.setFormatter(JsonFormatter())
        trace_file_handler.addFilter(TraceFilter(trace_id))  # Only log for this trace_id
        trace_handlers[trace_id] = trace_file_handler
        logger.addHandler(trace_file_handler)
    return logger

def call_service(url: str, method: str, trace_id: str, json_data: dict = None, timeout: float = 5.0):
    """
    Execute HTTP request to downstream microservice with error handling.
    
    Args:
        url: Full URL of the service endpoint
        method: HTTP method ('POST' or 'GET')
        trace_id: Trace ID to propagate in request headers
        json_data: Optional JSON payload for POST requests
        timeout: Request timeout in seconds (default: 5.0)
    
    Returns:
        dict: JSON response from the service
    
    Raises:
        HTTPException: On timeout, HTTP errors, or service failures with appropriate status codes
    
    Note:
        Automatically adds 'X-Trace-Id' header for distributed tracing
    """
    headers = {"X-Trace-Id": trace_id}
    try:
        if method == "POST":
            response = requests.post(url, json=json_data, headers=headers, timeout=timeout)
        elif method == "GET":
            response = requests.get(url, headers=headers, timeout=timeout)
        else:
            raise ValueError(f"Unsupported method: {method}")
        
        response.raise_for_status()
        return response.json()
    except requests.Timeout as e:
        logger.exception(f"[call_service] Timeout exception calling {url}", 
                        extra={'trace_id': trace_id, 'function': 'call_service', 'url': url},
                        exc_info=True)
        raise HTTPException(status_code=504, detail=f"Service timeout: {url}")
    except requests.HTTPError as e:
        # Extract detailed error message from service response
        try:
            error_detail = e.response.json().get('detail', f"Service error: {url}")
        except:
            error_detail = f"Service error: {url}"
        logger.exception(f"[call_service] HTTPError calling {url}", 
                    extra={'trace_id': trace_id, 'function': 'call_service', 
                           'url': url, 'status_code': e.response.status_code, 
                           'response_body': error_detail},
                    exc_info=True)
        raise HTTPException(status_code=e.response.status_code, detail=error_detail)
    except Exception as e:
        logger.exception(f"[call_service] Unexpected exception calling {url}", 
                        extra={'trace_id': trace_id, 'function': 'call_service', 
                               'url': url, 'error_type': type(e).__name__},
                        exc_info=True)
        raise HTTPException(status_code=500, detail=f"Service call failed: {url}")


def build_error_response(order_id: str, trace_id: str, overall_start: float, 
                        trade_result: Optional[Dict], pricing_result: Optional[Dict], 
                        risk_result: Optional[Dict], exception: HTTPException, 
                        workflow_type: str = "retail") -> OrderResponse:
    """
    Build standardized error response with execution_flow breakdown.
    Used by all three workflows (retail, institutional, algo).
    """
    # Determine failure stage
    if not trade_result:
        failure_stage = "validation"
    elif not pricing_result:
        failure_stage = "pricing_calculation"
    elif not risk_result:
        failure_stage = "risk_assessment"
    else:
        failure_stage = "execution"
    
    # Build execution flow showing completed stages
    execution_flow = {}
    
    if trade_result:
        execution_flow["validation"] = {
            "status": "passed",
            "normalized_quantity": trade_result.get('normalized_quantity'),
            "timestamp": trade_result.get('timestamp')
        }
    
    if pricing_result:
        execution_flow["pricing_calculation"] = {
            "execution_price": pricing_result.get('price'),
            "total_cost": pricing_result.get('total_cost'),
            "estimated_pnl": pricing_result.get('estimated_pnl'),
            "commission": pricing_result.get('commission'),
            "fees": pricing_result.get('fees'),
            "base_amount": pricing_result.get('base_amount'),
            "timestamp": pricing_result.get('timestamp')
        }
    
    if risk_result:
        execution_flow["risk_assessment"] = {
            "risk_score": risk_result.get('risk_score'),
            "approved": risk_result.get('approved'),
            "timestamp": risk_result.get('timestamp')
        }
    
    # Add failure information
    execution_flow["failure"] = {
        "stage": failure_stage,
        "message": str(exception.detail),
        "status_code": exception.status_code
    }
    
    # Calculate overall duration
    overall_duration_ms = int((time_module.time() - overall_start) * 1000)
    
    logger.exception(f"[place_{workflow_type}_order] Order failed after {overall_duration_ms}ms at {failure_stage}", 
                extra={'trace_id': trace_id, 'order_id': order_id, 
                       'function': f'place_{workflow_type}_order',
                       'extra_data': {
                           'total_duration_ms': overall_duration_ms, 
                           'status': 'FAILED', 
                           'failure_stage': failure_stage
                       }},
                exc_info=True)
    
    return OrderResponse(
        order_id=order_id,
        status="FAILED",
        message=f"{workflow_type.capitalize()} order failed at {failure_stage.replace('_', ' ')}: {str(exception.detail)}",
        trace_id=trace_id,
        latency_ms=overall_duration_ms,
        details={
            "execution_flow": execution_flow
        }
    )


@app.get("/")
def root():
    """Root endpoint"""
    return {"message": "Trade Orchestrator Service", "docs": "/docs"}


@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "orchestrator"}


@app.post("/orders/retail", response_model=OrderResponse)
def place_order(order: OrderRequest, request: Request):
    """
    WORKFLOW 1: Retail Order Flow
    Place order for retail/individual investors
    
    Example payload:
    {
        "symbol": "AAPL",
        "quantity": 50,
        "order_type": "BUY"
    }
    """
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    order_id = str(uuid.uuid4())
    
    # Start overall timing
    overall_start = time_module.time()
    
    # Create trace-specific log file
    get_trace_logger(trace_id)
    
    logger.info(f"[place_order] Order placement initiated", extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order'})
    logger.info(f"[place_order] Order Details - Symbol: {order.symbol}, Quantity: {order.quantity}, Type: {order.order_type}", 
                extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 'extra_data': {'symbol': order.symbol, 'quantity': order.quantity, 'order_type': order.order_type.value}})
    
    # Store partial results for detailed error reporting
    trade_result = None
    pricing_result = None
    risk_result = None
    
    try:
        # Step 1: Validate trade with Trade Service
        logger.info("[place_order] STEP 1: Starting trade validation with Trade Service", extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order'})
        trade_data = {
            "order_id": order_id,
            "symbol": order.symbol,
            "quantity": order.quantity,
            "order_type": order.order_type.value
        }
        logger.info(f"[place_order] Sending validation request to {TRADE_SERVICE_URL}/trades/validate", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 'extra_data': trade_data})
        
        validation_start = time_module.time()
        trade_result = call_service(
            f"{TRADE_SERVICE_URL}/trades/validate",
            "POST",
            trace_id,
            trade_data
        )
        validation_duration_ms = int((time_module.time() - validation_start) * 1000)
        
        logger.info(f"[place_order] validate_trade completed in {validation_duration_ms}ms", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 'extra_data': {'duration_ms': validation_duration_ms, 'service': 'trade_service'}})
        logger.info(f"[place_order] validate_trade response - Valid: {trade_result.get('valid')}", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 'extra_data': trade_result})
        
        if not trade_result.get("valid"):
            logger.warning(f"[place_order] VALIDATION FAILED - Reason: {trade_result.get('reason')}", 
                         extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 'extra_data': {'reason': trade_result.get('reason')}})
            return OrderResponse(
                order_id=order_id,
                status="REJECTED",
                message=trade_result.get("reason", "Trade validation failed"),
                trace_id=trace_id,
                details={
                    "execution_flow": {
                        "validation": {
                            "status": "failed",
                            "reason": trade_result.get('reason'),
                            "duration_ms": validation_duration_ms,
                            "timestamp": trade_result.get('timestamp')
                        }
                    }
                }
            )
        
        # Use normalized quantity from validation
        actual_quantity = trade_result.get("normalized_quantity", order.quantity)
        if actual_quantity != order.quantity:
            logger.info(f"[place_order] Using normalized quantity: {actual_quantity} (original: {order.quantity})", 
                       extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 'extra_data': {'original': order.quantity, 'normalized': actual_quantity}})
        
        # Step 1.5: Get validation price for comparison (demonstrates price variance)
        logger.info("[place_order] Getting validation price snapshot from Pricing-PnL Service", extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order'})
        validation_pricing_data = {
            "order_id": order_id,
            "symbol": order.symbol,
            "quantity": actual_quantity,
            "order_type": order.order_type.value
        }
        validation_pricing_start = time_module.time()
        validation_pricing_result = call_service(
            f"{PRICING_PNL_SERVICE_URL}/pricing/calculate",
            "POST",
            trace_id,
            validation_pricing_data
        )
        validation_pricing_duration_ms = int((time_module.time() - validation_pricing_start) * 1000)
        validation_price = validation_pricing_result.get("price")
        logger.info(f"[place_order] Validation price snapshot: ${validation_price}", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 'extra_data': {'validation_price': validation_price, 'duration_ms': validation_pricing_duration_ms}})
        
        # Step 2: Get execution execution pricing and PnL from Pricing-PnL Service
        logger.info("[place_order] STEP 2: Getting execution pricing and PnL calculation with Pricing-PnL Service", extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order'})
        pricing_data = {
            "order_id": order_id,
            "symbol": order.symbol,
            "quantity": actual_quantity,
            "order_type": order.order_type.value
        }
        logger.info(f"[place_order] Sending execution pricing request to {PRICING_PNL_SERVICE_URL}/pricing/calculate", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 'extra_data': pricing_data})
        
        pricing_start = time_module.time()
        pricing_result = call_service(
            f"{PRICING_PNL_SERVICE_URL}/pricing/calculate",
            "POST",
            trace_id,
            pricing_data
        )
        pricing_duration_ms = int((time_module.time() - pricing_start) * 1000)
        execution_price = pricing_result.get('price')
        
        logger.info(f"[place_order] calculate_pricing completed in {pricing_duration_ms}ms", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 'extra_data': {'duration_ms': pricing_duration_ms, 'service': 'pricing_service'}})
        logger.info(f"[place_order] Execution pricing - Price: ${execution_price}, Total Cost: ${pricing_result.get('total_cost')}, Est. PnL: ${pricing_result.get('estimated_pnl')}", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 'extra_data': pricing_result})
        
        # Log price variance between validation and execution
        price_variance = execution_price - validation_price
        price_variance_pct = (price_variance / validation_price) * 100
        logger.info(f"[place_order] Price variance detected - Validation: ${validation_price}, Execution: ${execution_price}, Difference: ${price_variance:.2f} ({price_variance_pct:+.2f}%)", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 'extra_data': {'validation_price': validation_price, 'execution_price': execution_price, 'variance': price_variance, 'variance_pct': price_variance_pct}})
        
        # Step 3: Assess risk with Risk Service
        logger.info("[place_order] STEP 3: Starting risk assessment with Risk Service", extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order'})
        risk_data = {
            "order_id": order_id,
            "symbol": order.symbol,
            "quantity": actual_quantity,
            "price": pricing_result.get("price"),
            "pnl": pricing_result.get("estimated_pnl"),
            "order_type": order.order_type.value
        }
        logger.info(f"[place_order] Sending risk assessment request to {RISK_SERVICE_URL}/risk/assess", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 'extra_data': risk_data})
        
        risk_start = time_module.time()
        try:
            risk_result = call_service(
                f"{RISK_SERVICE_URL}/risk/assess",
                "POST",
                trace_id,
                risk_data,
                timeout=15.0
            )
            risk_duration_ms = int((time_module.time() - risk_start) * 1000)
            
            logger.info(f"[place_order] assess_risk completed in {risk_duration_ms}ms", 
                       extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 'extra_data': {'duration_ms': risk_duration_ms, 'service': 'risk_service'}})
        except HTTPException as timeout_ex:
            risk_duration_ms = int((time_module.time() - risk_start) * 1000)
            if timeout_ex.status_code == 504:
                logger.error(f"[place_order] Risk service timeout - request exceeded limit after {risk_duration_ms}ms", 
                            extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 'extra_data': {'service': 'risk_service', 'duration_ms': risk_duration_ms}})
                return OrderResponse(
                    order_id=order_id,
                    status="FAILED",
                    message="Risk assessment service timeout",
                    trace_id=trace_id,
                    details={
                        "execution_flow": {
                            "validation": {
                                "status": "passed",
                                "normalized_quantity": actual_quantity,
                                "validation_price": validation_price,
                                "duration_ms": validation_duration_ms,
                                "timestamp": trade_result.get('timestamp')
                            },
                            "pricing_calculation": {
                                "execution_price": pricing_result.get('price'),
                                "total_cost": pricing_result.get('total_cost'),
                                "estimated_pnl": pricing_result.get('estimated_pnl'),
                                "commission": pricing_result.get('commission'),
                                "fees": pricing_result.get('fees'),
                                "base_amount": pricing_result.get('base_amount'),
                                "duration_ms": pricing_duration_ms,
                                "timestamp": pricing_result.get('timestamp')
                            },
                            "risk_assessment": {
                                "error": "timeout",
                                "message": "Risk service did not respond within timeout period (15 seconds)",
                                "attempted_at": datetime.now().isoformat(),
                                "duration_ms": risk_duration_ms
                            }
                        }
                    }
                )
            raise
        
        logger.info(f"[place_order] Risk Service response - Level: {risk_result.get('risk_level')}, Score: {risk_result.get('risk_score')}, Approved: {risk_result.get('approved')}", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 'extra_data': risk_result})
        logger.info(f"[place_order] Risk Recommendation: {risk_result.get('recommendation')}", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order'})
        
        # Triggered ONLY when risk_score > 75
        risk_score = risk_result.get('risk_score', 0)
        if risk_score > 75:
            logger.info(f"[place_order] ⚠️ HIGH RISK DETECTED (Score: {risk_score}) - Triggering escalation workflow",
                       extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order'})
            
            # Call escalation functions (these are ONLY called for high-risk orders)
            escalation_data = {
                'order_id': order_id,
                'risk_score': risk_score,
                'risk_factors': risk_result.get('risk_factors', {})
            }
            
            # This creates a DIFFERENT call chain: escalate_to_risk_manager → check_portfolio_impact
            escalation_result = call_service(
                f"{RISK_SERVICE_URL}/risk/escalate",
                "POST",
                trace_id,
                escalation_data
            )
            
            logger.info(f"[place_order] Escalation result: Auto-approved={escalation_result.get('auto_approved')}",
                       extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 'extra_data': escalation_result})
            
            if not escalation_result.get('auto_approved'):
                logger.warning(f"[place_order] Manual approval required - Order cannot be auto-processed",
                             extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order'})
                return OrderResponse(
                    order_id=order_id,
                    status="PENDING_APPROVAL",
                    message="Order requires manual approval due to extremely high risk",
                    trace_id=trace_id,
                    details={'escalation': escalation_result, 'risk': risk_result}
                )
        
        # Triggered ONLY when order_type=SELL AND estimated_pnl < 0
        if order.order_type == OrderType.SELL and pricing_result.get('estimated_pnl', 0) < 0:
            logger.info(f"[place_order] SELL AT LOSS detected (PnL: ${pricing_result.get('estimated_pnl')}) - Triggering tax validation workflow",
                       extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order'})
            
            # Call loss-specific functions (these are ONLY called for loss-selling)
            tax_data = {
                'order_id': order_id,
                'symbol': order.symbol,
                'pnl': pricing_result.get('estimated_pnl'),
                'quantity': actual_quantity
            }
            
            # This creates a DIFFERENT call chain: calculate_tax_implications → check_wash_sale_rule → verify_cost_basis
            tax_result = call_service(
                f"{PRICING_PNL_SERVICE_URL}/pricing/tax-analysis",
                "POST",
                trace_id,
                tax_data
            )
            
            logger.info(f"[place_order] Tax analysis complete - Tax benefit: ${tax_result.get('tax_benefit')}",
                       extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 'extra_data': tax_result})
        
        # Check if risk is acceptable
        if risk_result.get("risk_level") == "HIGH" and risk_result.get("approved") is False:
            logger.warning("[place_order] ORDER REJECTED - High risk assessment failed approval", 
                         extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 'extra_data': {'risk_level': 'HIGH', 'risk_score': risk_result.get('risk_score')}})
            return OrderResponse(
                order_id=order_id,
                status="REJECTED",
                message="Order rejected due to high risk",
                trace_id=trace_id,
                details={
                    "execution_flow": {
                        "validation": {
                            "status": "passed",
                            "normalized_quantity": actual_quantity,
                            "validation_price": validation_price,
                            "duration_ms": validation_duration_ms,
                            "timestamp": trade_result.get('timestamp')
                        },
                        "pricing_calculation": {
                            "execution_price": pricing_result.get('price'),
                            "total_cost": pricing_result.get('total_cost'),
                            "estimated_pnl": pricing_result.get('estimated_pnl'),
                            "commission": pricing_result.get('commission'),
                            "fees": pricing_result.get('fees'),
                            "base_amount": pricing_result.get('base_amount'),
                            "duration_ms": pricing_duration_ms,
                            "timestamp": pricing_result.get('timestamp')
                        },
                        "risk_assessment": {
                            "risk_level": risk_result.get('risk_level'),
                            "risk_score": risk_result.get('risk_score'),
                            "approved": risk_result.get('approved'),
                            "risk_factors": risk_result.get('risk_factors'),
                            "duration_ms": risk_duration_ms,
                            "timestamp": risk_result.get('timestamp')
                        }
                    }
                }
            )
        
        # Step 4: Execute the trade
        logger.info("[place_order] STEP 4: Proceeding with trade execution at Trade Service", extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order'})
        execution_data = {
            "order_id": order_id,
            "symbol": order.symbol,
            "quantity": actual_quantity,
            "price": pricing_result.get("price"),
            "order_type": order.order_type.value
        }
        logger.info(f"[place_order] Sending execution request to {TRADE_SERVICE_URL}/trades/execute", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 'extra_data': execution_data})
        
        execution_start = time_module.time()
        execution_result = call_service(
            f"{TRADE_SERVICE_URL}/trades/execute",
            "POST",
            trace_id,
            execution_data
        )
        execution_duration_ms = int((time_module.time() - execution_start) * 1000)
        
        logger.info(f"[place_order] execute_trade completed in {execution_duration_ms}ms", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 'extra_data': {'duration_ms': execution_duration_ms, 'service': 'trade_service'}})
        logger.info(f"[place_order] Trade execution completed - Status: {execution_result.get('status')}, Time: {execution_result.get('execution_time')}", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 'extra_data': execution_result})
        logger.info("[place_order] Order executed successfully", extra={
            'trace_id': trace_id,
            'order_id': order_id,
            'function': 'place_order',
            'extra_data': {
                'final_status': 'EXECUTED',
                'symbol': order.symbol,
                'quantity': actual_quantity,
                'price': pricing_result.get('price'),
                'total_cost': pricing_result.get('total_cost'),
                'estimated_pnl': pricing_result.get('estimated_pnl'),
                'risk_level': risk_result.get('risk_level'),
                'risk_score': risk_result.get('risk_score')
            }
        })
                
        # Calculate overall end-to-end latency
        overall_duration_ms = int((time_module.time() - overall_start) * 1000)
        
        logger.info(f"[place_order] Order completed successfully in {overall_duration_ms}ms (end-to-end)", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 
                          'extra_data': {'total_duration_ms': overall_duration_ms, 'status': 'EXECUTED'}})
        
        return OrderResponse(
            order_id=order_id,
            status="EXECUTED",
            message=f"Order executed successfully: {order.order_type} {actual_quantity} {order.symbol} @ ${execution_price}",
            trace_id=trace_id,
            latency_ms=overall_duration_ms,
            details={
                "execution_flow": {
                    "validation": {
                        "status": "passed",
                        "normalized_quantity": actual_quantity,
                        "validation_price": validation_price,
                        "duration_ms": validation_duration_ms,
                        "timestamp": trade_result.get('timestamp')
                    },
                    "pricing_calculation": {
                        "execution_price": pricing_result.get('price'),
                        "total_cost": pricing_result.get('total_cost'),
                        "estimated_pnl": pricing_result.get('estimated_pnl'),
                        "commission": pricing_result.get('commission'),
                        "fees": pricing_result.get('fees'),
                        "base_amount": pricing_result.get('base_amount'),
                        "duration_ms": pricing_duration_ms,
                        "timestamp": pricing_result.get('timestamp')
                    },
                    "risk_assessment": {
                        "risk_level": risk_result.get('risk_level'),
                        "risk_score": risk_result.get('risk_score'),
                        "approved": risk_result.get('approved'),
                        "risk_factors": risk_result.get('risk_factors'),
                        "duration_ms": risk_duration_ms,
                        "timestamp": risk_result.get('timestamp')
                    },
                    "execution": {
                        "status": execution_result.get('status'),
                        "duration_ms": execution_duration_ms,
                        "execution_time": execution_result.get('execution_time')
                    }
                },
                "summary": {
                    "symbol": order.symbol,
                    "order_type": order.order_type.value,
                    "quantity": actual_quantity,
                    "price": pricing_result.get('price'),
                    "total_cost": pricing_result.get('total_cost'),
                    "estimated_pnl": pricing_result.get('estimated_pnl'),
                    "commission": pricing_result.get('commission'),
                    "fees": pricing_result.get('fees'),
                    "base_amount": pricing_result.get('base_amount'),
                    "risk_level": risk_result.get('risk_level')
                }
            }
        )
        
    except HTTPException as e:
        logger.exception(f"[place_order] Order placement failed", extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order'}, exc_info=True)
        
        # Determine failure stage
        if not trade_result:
            failure_stage = "validation"
        elif not pricing_result:
            failure_stage = "pricing_calculation"
        elif not risk_result:
            failure_stage = "risk_assessment"
        else:
            failure_stage = "execution"
        
        # Build execution flow showing where it failed
        execution_flow = {}
        
        if trade_result:
            execution_flow["validation"] = {
                "status": "passed",
                "normalized_quantity": trade_result.get('normalized_quantity'),
                "validation_price": validation_price if 'validation_price' in locals() else None,
                "duration_ms": validation_duration_ms if 'validation_duration_ms' in locals() else None,
                "timestamp": trade_result.get('timestamp')
            }
        
        if pricing_result:
            execution_flow["pricing_calculation"] = {
                "execution_price": pricing_result.get('price'),
                "total_cost": pricing_result.get('total_cost'),
                "estimated_pnl": pricing_result.get('estimated_pnl'),
                "commission": pricing_result.get('commission'),
                "fees": pricing_result.get('fees'),
                "base_amount": pricing_result.get('base_amount'),
                "duration_ms": pricing_duration_ms if 'pricing_duration_ms' in locals() else None,
                "timestamp": pricing_result.get('timestamp')
            }
        
        if risk_result:
            execution_flow["risk_assessment"] = {
                "risk_level": risk_result.get('risk_level'),
                "risk_score": risk_result.get('risk_score'),
                "approved": risk_result.get('approved'),
                "timestamp": risk_result.get('timestamp')
            }
        
        # Add failure information
        execution_flow["failure"] = {
            "stage": failure_stage,
            "message": str(e.detail),
            "status_code": e.status_code
        }
        
        # Calculate overall duration even for failures
        overall_duration_ms = int((time_module.time() - overall_start) * 1000)
        
        logger.exception(f"[place_order] Order failed after {overall_duration_ms}ms", 
                    extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 
                           'extra_data': {'total_duration_ms': overall_duration_ms, 'status': 'FAILED', 'failure_stage': failure_stage}},
                    exc_info=True)
        
        return OrderResponse(
            order_id=order_id,
            status="FAILED",
            message=f"Order failed at {failure_stage.replace('_', ' ')}: {str(e.detail)}",
            trace_id=trace_id,
            latency_ms=overall_duration_ms,
            details={
                "execution_flow": execution_flow
            }
        )
    except Exception as e:
        logger.exception(f"[place_order] Order placement failed", extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_order', 'extra_data': {'error_type': type(e).__name__}}, exc_info=True)
        raise HTTPException(status_code=500, detail="Order placement failed")





@app.get("/orders/{order_id}")
def get_order_status(order_id: str, request: Request):
    """Get the status of a specific order"""
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    
    logger.info("[get_order_status] Fetching order status", extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'get_order_status'})
    
    try:
        # Query all services for order information
        trade_info = call_service(f"{TRADE_SERVICE_URL}/trades/{order_id}", "GET", trace_id)
        
        return {
            "order_id": order_id,
            "trace_id": trace_id,
            "trade_info": trade_info
        }
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(status_code=404, detail="Order not found")
        raise


@app.post("/orders/institutional", response_model=OrderResponse)
def place_institutional_order(order: OrderRequest, request: Request):
    """
    WORKFLOW 2: Institutional Order Flow
    Place order for institutional clients (portfolio managers, hedge funds)
    
    Example payload:
    {
        "symbol": "AAPL",
        "quantity": 5000,
        "order_type": "BUY"
    }
    """
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    order_id = str(uuid.uuid4())
    
    overall_start = time_module.time()
    get_trace_logger(trace_id)
    
    logger.info(f"[place_institutional_order] Institutional order placement initiated", 
                extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_institutional_order'})
    logger.info(f"[place_institutional_order] Params - symbol: {order.symbol}, quantity: {order.quantity}, order_type: {order.order_type}", 
                extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_institutional_order'})
    
    trade_result = None
    pricing_result = None
    risk_result = None
    
    try:
        # Step 1: Validate institutional order
        logger.info("[place_institutional_order] STEP 1: Starting institutional order validation", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_institutional_order'})
        
        institutional_data = {
            "order_id": order_id,
            "symbol": order.symbol,
            "quantity": order.quantity,
            "order_type": order.order_type.value
        }
        
        validation_start = time_module.time()
        trade_result = call_service(
            f"{TRADE_SERVICE_URL}/trades/validate-institutional",
            "POST",
            trace_id,
            institutional_data
        )
        validation_duration_ms = int((time_module.time() - validation_start) * 1000)
        
        logger.info(f"[place_institutional_order] validate_institutional_order completed in {validation_duration_ms}ms", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_institutional_order', 
                          'extra_data': {'duration_ms': validation_duration_ms}})        
        if not trade_result.get("valid"):
            logger.warning(f"[place_institutional_order] Institutional validation failed: {trade_result.get('reason')}", 
                         extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_institutional_order'})
            return OrderResponse(
                order_id=order_id,
                status="REJECTED",
                message=trade_result.get("reason", "Institutional validation failed"),
                trace_id=trace_id
            )
        
        actual_quantity = trade_result.get("normalized_quantity", order.quantity)
        
        # Step 2: Calculate institutional pricing
        logger.info("[place_institutional_order] STEP 2: Calculating institutional pricing", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_institutional_order'})
        
        pricing_data = {
            "order_id": order_id,
            "symbol": order.symbol,
            "quantity": actual_quantity,
            "order_type": order.order_type.value,
            "client_type": "institutional"
        }
        
        pricing_start = time_module.time()
        pricing_result = call_service(
            f"{PRICING_PNL_SERVICE_URL}/pricing/calculate-institutional",
            "POST",
            trace_id,
            pricing_data
        )
        pricing_duration_ms = int((time_module.time() - pricing_start) * 1000)
        
        logger.info(f"[place_institutional_order] calculate_institutional_pricing completed in {pricing_duration_ms}ms", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_institutional_order', 
                          'extra_data': {'duration_ms': pricing_duration_ms, 'price': pricing_result.get('price')}})
        
        # Step 3: Assess institutional risk
        logger.info("[place_institutional_order] STEP 3: Assessing institutional risk", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_institutional_order'})
        
        risk_data = {
            "order_id": order_id,
            "symbol": order.symbol,
            "quantity": actual_quantity,
            "price": pricing_result.get("price"),
            "pnl": pricing_result.get("estimated_pnl"),
            "order_type": order.order_type.value,
            "client_type": "institutional"
        }
        
        risk_start = time_module.time()
        risk_result = call_service(
            f"{RISK_SERVICE_URL}/risk/assess-institutional",
            "POST",
            trace_id,
            risk_data
        )
        risk_duration_ms = int((time_module.time() - risk_start) * 1000)
        
        logger.info(f"[place_institutional_order] assess_institutional_risk completed in {risk_duration_ms}ms", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_institutional_order', 
                          'extra_data': {'duration_ms': risk_duration_ms, 'risk_score': risk_result.get('risk_score')}})
        
        if not risk_result.get("approved"):
            logger.warning(f"[place_institutional_order] Risk assessment rejected", 
                         extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_institutional_order'})
            return OrderResponse(
                order_id=order_id,
                status="REJECTED",
                message="Institutional order rejected due to risk assessment",
                trace_id=trace_id,
                details={'risk': risk_result}
            )
        
        # Step 4: Execute institutional trade
        logger.info("[place_institutional_order] STEP 4: Executing institutional trade", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_institutional_order'})
        
        execution_data = {
            "order_id": order_id,
            "symbol": order.symbol,
            "quantity": actual_quantity,
            "price": pricing_result.get("price"),
            "order_type": order.order_type.value
        }
        
        execution_result = call_service(
            f"{TRADE_SERVICE_URL}/trades/execute",
            "POST",
            trace_id,
            execution_data
        )
        
        overall_duration_ms = int((time_module.time() - overall_start) * 1000)
        
        logger.info(f"[place_institutional_order] Institutional order completed successfully in {overall_duration_ms}ms", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_institutional_order', 
                          'extra_data': {'total_duration_ms': overall_duration_ms}})
        
        return OrderResponse(
            order_id=order_id,
            status="EXECUTED",
            message="Institutional order executed successfully",
            trace_id=trace_id,
            latency_ms=overall_duration_ms,
            details={
                "execution_flow": {
                    "validation": {
                        "status": "passed",
                        "normalized_quantity": actual_quantity,
                        "duration_ms": validation_duration_ms,
                        "timestamp": trade_result.get('timestamp')
                    },
                    "pricing_calculation": {
                        "execution_price": pricing_result.get('price'),
                        "total_cost": pricing_result.get('total_cost'),
                        "estimated_pnl": pricing_result.get('estimated_pnl'),
                        "commission": pricing_result.get('commission'),
                        "fees": pricing_result.get('fees'),
                        "base_amount": pricing_result.get('base_amount'),
                        "volume_discount": pricing_result.get('volume_discount'),
                        "duration_ms": pricing_duration_ms,
                        "timestamp": pricing_result.get('timestamp')
                    },
                    "risk_assessment": {
                        "risk_score": risk_result.get('risk_score'),
                        "approved": risk_result.get('approved'),
                        "aggregate_exposure": risk_result.get('aggregate_exposure'),
                        "regulatory_compliance": risk_result.get('regulatory_compliance'),
                        "duration_ms": risk_duration_ms,
                        "timestamp": risk_result.get('timestamp')
                    },
                    "execution": {
                        "status": execution_result.get('status'),
                        "execution_time": execution_result.get('execution_time')
                    }
                }
            }
        )
        
    except HTTPException as e:
        return build_error_response(
            order_id=order_id,
            trace_id=trace_id,
            overall_start=overall_start,
            trade_result=trade_result,
            pricing_result=pricing_result,
            risk_result=risk_result,
            exception=e,
            workflow_type="institutional"
        )
    except Exception as e:
        logger.exception(f"[place_institutional_order] Unexpected exception during institutional order processing", 
                        extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_institutional_order',
                               'error_type': type(e).__name__},
                        exc_info=True)
        raise HTTPException(status_code=500, detail="Institutional order processing failed")


@app.post("/orders/algo", response_model=OrderResponse)
def place_algo_order(order: OrderRequest, request: Request):
    """
    WORKFLOW 3: Algorithmic Trading Order Flow
    High-speed order placement for algorithmic trading systems
    
    Example payload:
    {
        "symbol": "AAPL",
        "quantity": 1000,
        "order_type": "BUY"
    }
    """
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    order_id = str(uuid.uuid4())
    
    overall_start = time_module.time()
    get_trace_logger(trace_id)
    
    logger.info(f"[place_algo_order] Algo trading order initiated", 
                extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_algo_order'})
    logger.info(f"[place_algo_order] Params - symbol: {order.symbol}, quantity: {order.quantity}, order_type: {order.order_type}", 
                extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_algo_order'})
    
    trade_result = None
    pricing_result = None
    risk_result = None
    
    try:
        # Step 1: Validate algo credentials and strategy limits
        logger.info("[place_algo_order] STEP 1: Validating algo credentials", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_algo_order'})
        
        algo_data = {
            "order_id": order_id,
            "symbol": order.symbol,
            "quantity": order.quantity,
            "order_type": order.order_type.value,
            "strategy_id": "MOMENTUM_v2"
        }
        
        validation_start = time_module.time()
        trade_result = call_service(
            f"{TRADE_SERVICE_URL}/trades/validate-algo",
            "POST",
            trace_id,
            algo_data
        )
        validation_duration_ms = int((time_module.time() - validation_start) * 1000)
        
        logger.info(f"[place_algo_order] validate_algo_order completed in {validation_duration_ms}ms", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_algo_order', 
                          'extra_data': {'duration_ms': validation_duration_ms}})
        
        if not trade_result.get("valid"):
            logger.warning(f"[place_algo_order] Algo validation failed: {trade_result.get('reason')}", 
                         extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_algo_order'})
            return OrderResponse(
                order_id=order_id,
                status="REJECTED",
                message=trade_result.get("reason", "Algo validation failed"),
                trace_id=trace_id
            )
        
        # Step 2: Fast pricing calculation
        logger.info("[place_algo_order] STEP 2: Fast algo pricing", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_algo_order'})
        
        pricing_data = {
            "order_id": order_id,
            "symbol": order.symbol,
            "quantity": order.quantity,
            "order_type": order.order_type.value
        }
        
        pricing_start = time_module.time()
        pricing_result = call_service(
            f"{PRICING_PNL_SERVICE_URL}/pricing/algo-fast",
            "POST",
            trace_id,
            pricing_data
        )
        pricing_duration_ms = int((time_module.time() - pricing_start) * 1000)
        
        logger.info(f"[place_algo_order] calculate_algo_pricing completed in {pricing_duration_ms}ms", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_algo_order', 
                          'extra_data': {'duration_ms': pricing_duration_ms}})
        
        # Step 3: Pre-trade risk check (lightweight)
        logger.info("[place_algo_order] STEP 3: Pre-trade risk check", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_algo_order'})
        
        risk_data = {
            "order_id": order_id,
            "symbol": order.symbol,
            "quantity": order.quantity,
            "price": pricing_result.get("price"),
            "strategy_id": "MOMENTUM_v2"
        }
        
        risk_start = time_module.time()
        risk_result = call_service(
            f"{RISK_SERVICE_URL}/risk/pre-trade-check",
            "POST",
            trace_id,
            risk_data
        )
        risk_duration_ms = int((time_module.time() - risk_start) * 1000)
        
        logger.info(f"[place_algo_order] verify_pre_trade_risk completed in {risk_duration_ms}ms", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_algo_order', 
                          'extra_data': {'duration_ms': risk_duration_ms}})
        
        if not risk_result.get("approved"):
            logger.warning(f"[place_algo_order] Pre-trade risk check failed", 
                         extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_algo_order'})
            return OrderResponse(
                order_id=order_id,
                status="REJECTED",
                message="Algo order rejected - circuit breaker triggered",
                trace_id=trace_id,
                details={'risk': risk_result}
            )
        
        # Step 4: Route to execution engine
        logger.info("[place_algo_order] STEP 4: Routing to execution engine", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_algo_order'})
        
        execution_data = {
            "order_id": order_id,
            "symbol": order.symbol,
            "quantity": order.quantity,
            "price": pricing_result.get("price"),
            "order_type": order.order_type.value
        }
        
        execution_result = call_service(
            f"{TRADE_SERVICE_URL}/trades/execute",
            "POST",
            trace_id,
            execution_data
        )
        
        overall_duration_ms = int((time_module.time() - overall_start) * 1000)
        
        logger.info(f"[place_algo_order] Algo order completed in {overall_duration_ms}ms", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_algo_order', 
                          'extra_data': {'total_duration_ms': overall_duration_ms}})
        
        return OrderResponse(
            order_id=order_id,
            status="EXECUTED",
            message="Algo order executed successfully",
            trace_id=trace_id,
            latency_ms=overall_duration_ms,
            details={
                "execution_flow": {
                    "validation": {
                        "status": "passed",
                        "strategy_id": "MOMENTUM_v2",
                        "normalized_quantity": trade_result.get('normalized_quantity'),
                        "duration_ms": validation_duration_ms,
                        "timestamp": trade_result.get('timestamp')
                    },
                    "pricing_calculation": {
                        "execution_price": pricing_result.get('price'),
                        "total_cost": pricing_result.get('total_cost'),
                        "commission": pricing_result.get('commission'),
                        "algo_trading": pricing_result.get('algo_trading'),
                        "duration_ms": pricing_duration_ms,
                        "timestamp": pricing_result.get('timestamp')
                    },
                    "risk_assessment": {
                        "approved": risk_result.get('approved'),
                        "quick_risk_score": risk_result.get('quick_risk_score'),
                        "strategy_id": risk_result.get('strategy_id'),
                        "duration_ms": risk_duration_ms,
                        "timestamp": risk_result.get('timestamp')
                    },
                    "execution": {
                        "status": execution_result.get('status'),
                        "execution_time": execution_result.get('execution_time')
                    }
                }
            }
        )
        
    except HTTPException as e:
        return build_error_response(
            order_id=order_id,
            trace_id=trace_id,
            overall_start=overall_start,
            trade_result=trade_result,
            pricing_result=pricing_result,
            risk_result=risk_result,
            exception=e,
            workflow_type="algo"
        )
    except Exception as e:
        logger.exception(f"[place_algo_order] Unexpected exception during algo order processing", 
                        extra={'trace_id': trace_id, 'order_id': order_id, 'function': 'place_algo_order',
                               'error_type': type(e).__name__},
                        exc_info=True)
        raise HTTPException(status_code=500, detail="Algo order processing failed")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
