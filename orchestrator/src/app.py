import logging
import json
import uuid
import asyncio
from datetime import datetime, time
from typing import Optional, Dict, Any
from enum import Enum

from fastapi import FastAPI, HTTPException, Header, Request
from pydantic import BaseModel, Field
import httpx
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
        return json.dumps(log_data)

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# File handler with JSON format
file_handler = logging.FileHandler('../logs/orchestrator.log')
file_handler.setFormatter(JsonFormatter())

# Console handler with readable format
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - orchestrator - %(message)s'))

logger.addHandler(file_handler)
logger.addHandler(console_handler)

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
    details: Optional[Dict[str, Any]] = None


def get_trace_id(x_trace_id: Optional[str] = Header(None)) -> str:
    """Generate or use existing trace ID"""
    return x_trace_id or str(uuid.uuid4())


def is_market_open(current_time: datetime) -> bool:
    """
    Check if market is open (dummy implementation)
    Market hours: 9:30 AM - 4:00 PM EST (simulated as 9-16 in local time)
    """
    market_open = time(9, 30)
    market_close = time(16, 0)
    current = current_time.time()
    return market_open <= current <= market_close


async def call_service(url: str, method: str, trace_id: str, json_data: dict = None, timeout: float = 5.0):
    """Helper function to call microservices"""
    headers = {"X-Trace-Id": trace_id}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "POST":
                response = await client.post(url, json=json_data, headers=headers)
            elif method == "GET":
                response = await client.get(url, headers=headers)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            response.raise_for_status()
            return response.json()
    except httpx.TimeoutException as e:
        logger.error(f"Timeout calling {url}", extra={'trace_id': trace_id})
        raise HTTPException(status_code=504, detail=f"Service timeout: {url}")
    except httpx.HTTPStatusError as e:
        # Extract detailed error message from service response
        try:
            error_detail = e.response.json().get('detail', f"Service error: {url}")
        except:
            error_detail = f"Service error: {url}"
        logger.error(f"HTTP error calling {url} - status {e.response.status_code}: {error_detail}", 
                    extra={'trace_id': trace_id, 'extra_data': {'status_code': e.response.status_code, 'error_detail': error_detail}})
        raise HTTPException(status_code=e.response.status_code, detail=error_detail)
    except Exception as e:
        logger.error(f"Error calling {url} - {str(e)}", extra={'trace_id': trace_id})
        raise HTTPException(status_code=500, detail=f"Service call failed: {url}")


@app.get("/")
def root():
    """Root endpoint"""
    return {"message": "Trade Orchestrator Service", "docs": "/docs"}


@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "orchestrator"}


@app.post("/orders", response_model=OrderResponse)
async def place_order(order: OrderRequest, request: Request):
    """
    Place a new order - orchestrates the entire trade flow
    
    Example payload:
    {
        "symbol": "AAPL",
        "quantity": 50,
        "order_type": "BUY"
    }
    """
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    order_id = str(uuid.uuid4())
    
    logger.info(f"========== ORDER PLACEMENT INITIATED ==========", extra={'trace_id': trace_id, 'order_id': order_id})
    logger.info(f"Order Details - Symbol: {order.symbol}, Quantity: {order.quantity}, Type: {order.order_type}", 
                extra={'trace_id': trace_id, 'order_id': order_id, 'extra_data': {'symbol': order.symbol, 'quantity': order.quantity, 'order_type': order.order_type.value}})
    
    try:
        # Step 1: Validate trade with Trade Service
        logger.info("STEP 1: Starting trade validation with Trade Service", extra={'trace_id': trace_id, 'order_id': order_id})
        trade_data = {
            "order_id": order_id,
            "symbol": order.symbol,
            "quantity": order.quantity,
            "order_type": order.order_type.value
        }
        logger.info(f"Sending validation request to {TRADE_SERVICE_URL}/trades/validate", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'extra_data': trade_data})
        trade_result = await call_service(
            f"{TRADE_SERVICE_URL}/trades/validate",
            "POST",
            trace_id,
            trade_data
        )
        
        logger.info(f"Trade Service response received - Valid: {trade_result.get('valid')}", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'extra_data': trade_result})
        
        if not trade_result.get("valid"):
            logger.warning(f"VALIDATION FAILED - Reason: {trade_result.get('reason')}", 
                         extra={'trace_id': trace_id, 'order_id': order_id, 'extra_data': {'reason': trade_result.get('reason')}})
            return OrderResponse(
                order_id=order_id,
                status="REJECTED",
                message=trade_result.get("reason", "Trade validation failed"),
                trace_id=trace_id,
                details=trade_result
            )
        
        # Use normalized quantity from validation
        actual_quantity = trade_result.get("normalized_quantity", order.quantity)
        if actual_quantity != order.quantity:
            logger.info(f"Using normalized quantity: {actual_quantity} (original: {order.quantity})", 
                       extra={'trace_id': trace_id, 'order_id': order_id, 'extra_data': {'original': order.quantity, 'normalized': actual_quantity}})
        
        # Step 2: Get pricing and PnL from Pricing-PnL Service
        logger.info("STEP 2: Starting pricing and PnL calculation with Pricing-PnL Service", extra={'trace_id': trace_id, 'order_id': order_id})
        pricing_data = {
            "order_id": order_id,
            "symbol": order.symbol,
            "quantity": actual_quantity,
            "order_type": order.order_type.value
        }
        logger.info(f"Sending pricing request to {PRICING_PNL_SERVICE_URL}/pricing/calculate", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'extra_data': pricing_data})
        
        pricing_result = await call_service(
            f"{PRICING_PNL_SERVICE_URL}/pricing/calculate",
            "POST",
            trace_id,
            pricing_data
        )
        
        logger.info(f"Pricing Service response - Price: ${pricing_result.get('price')}, Total Cost: ${pricing_result.get('total_cost')}, Est. PnL: ${pricing_result.get('estimated_pnl')}", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'extra_data': pricing_result})
        
        # Step 3: Assess risk with Risk Service
        logger.info("STEP 3: Starting risk assessment with Risk Service", extra={'trace_id': trace_id, 'order_id': order_id})
        risk_data = {
            "order_id": order_id,
            "symbol": order.symbol,
            "quantity": actual_quantity,
            "price": pricing_result.get("price"),
            "pnl": pricing_result.get("estimated_pnl"),
            "order_type": order.order_type.value
        }
        logger.info(f"Sending risk assessment request to {RISK_SERVICE_URL}/risk/assess", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'extra_data': risk_data})
        
        try:
            risk_result = await asyncio.wait_for(
                call_service(
                    f"{RISK_SERVICE_URL}/risk/assess",
                    "POST",
                    trace_id,
                    risk_data
                ),
                timeout=5.0
            )
        except asyncio.TimeoutError:
            logger.error("Risk service timeout - request exceeded 5 second limit", 
                        extra={'trace_id': trace_id, 'order_id': order_id, 'extra_data': {'service': 'risk_service', 'timeout_seconds': 5}})
            return OrderResponse(
                order_id=order_id,
                status="FAILED",
                message="Risk assessment service timeout",
                trace_id=trace_id,
                details={"error": "Risk service did not respond within timeout period"}
            )
        
        logger.info(f"Risk Service response - Level: {risk_result.get('risk_level')}, Score: {risk_result.get('risk_score')}, Approved: {risk_result.get('approved')}", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'extra_data': risk_result})
        logger.info(f"Risk Recommendation: {risk_result.get('recommendation')}", 
                   extra={'trace_id': trace_id, 'order_id': order_id})
        
        # Check if risk is acceptable
        if risk_result.get("risk_level") == "HIGH" and risk_result.get("approved") is False:
            logger.warning("ORDER REJECTED - High risk assessment failed approval", 
                         extra={'trace_id': trace_id, 'order_id': order_id, 'extra_data': {'risk_level': 'HIGH', 'risk_score': risk_result.get('risk_score')}})
            return OrderResponse(
                order_id=order_id,
                status="REJECTED",
                message="Order rejected due to high risk",
                trace_id=trace_id,
                details={
                    "trade": trade_result,
                    "pricing": pricing_result,
                    "risk": risk_result
                }
            )
        
        # Step 4: Execute the trade
        logger.info("STEP 4: Proceeding with trade execution at Trade Service", extra={'trace_id': trace_id, 'order_id': order_id})
        execution_data = {
            "order_id": order_id,
            "symbol": order.symbol,
            "quantity": actual_quantity,
            "price": pricing_result.get("price"),
            "order_type": order.order_type.value
        }
        logger.info(f"Sending execution request to {TRADE_SERVICE_URL}/trades/execute", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'extra_data': execution_data})
        
        execution_result = await call_service(
            f"{TRADE_SERVICE_URL}/trades/execute",
            "POST",
            trace_id,
            execution_data
        )
        
        logger.info(f"Trade execution completed - Status: {execution_result.get('status')}, Time: {execution_result.get('execution_time')}", 
                   extra={'trace_id': trace_id, 'order_id': order_id, 'extra_data': execution_result})
        logger.info("========== ORDER EXECUTED SUCCESSFULLY ==========", extra={
            'trace_id': trace_id,
            'order_id': order_id,
            'extra_data': {
                'final_status': 'EXECUTED',
                'symbol': order.symbol,
                'quantity': order.quantity,
                'price': pricing_result.get('price'),
                'total_cost': pricing_result.get('total_cost'),
                'estimated_pnl': pricing_result.get('estimated_pnl'),
                'risk_level': risk_result.get('risk_level'),
                'risk_score': risk_result.get('risk_score')
            }
        })
        
        return OrderResponse(
            order_id=order_id,
            status="EXECUTED",
            message="Order executed successfully",
            trace_id=trace_id,
            details={
                "execution": execution_result,
                "pricing": pricing_result,
                "risk": risk_result
            }
        )
        
    except HTTPException as e:
        logger.error(f"Order placement failed - {str(e.detail)}", extra={'trace_id': trace_id, 'order_id': order_id})
        raise
    except Exception as e:
        logger.error(f"Order placement failed - {str(e)}", extra={'trace_id': trace_id, 'order_id': order_id})
        raise HTTPException(status_code=500, detail=f"Order placement failed: {str(e)}")





@app.get("/orders/{order_id}")
async def get_order_status(order_id: str, request: Request):
    """Get the status of a specific order"""
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    
    logger.info("Fetching order status", extra={'trace_id': trace_id, 'order_id': order_id})
    
    try:
        # Query all services for order information
        trade_info = await call_service(f"{TRADE_SERVICE_URL}/trades/{order_id}", "GET", trace_id)
        
        return {
            "order_id": order_id,
            "trace_id": trace_id,
            "trade_info": trade_info
        }
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(status_code=404, detail="Order not found")
        raise


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
