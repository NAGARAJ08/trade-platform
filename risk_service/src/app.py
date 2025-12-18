import logging
import json
import uuid
import asyncio
from datetime import datetime
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
            "service": "risk_service",
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
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - risk_service - %(message)s'))

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
    title="Risk Assessment Service",
    description="Performs risk analysis on trade orders",
    version="1.0.0"
)

# In-memory storage for risk assessments
risk_assessments: Dict[str, Dict[str, Any]] = {}


class OrderType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RiskAssessmentRequest(BaseModel):
    order_id: str
    symbol: str = Field(..., example="AAPL")
    quantity: int = Field(...)
    price: float = Field(..., gt=0)
    pnl: float
    order_type: OrderType


class RiskAssessmentResponse(BaseModel):
    order_id: str
    risk_level: RiskLevel
    approved: bool
    risk_score: float
    risk_factors: Dict[str, Any]
    recommendation: str
    timestamp: str


def get_trace_id(x_trace_id: Optional[str] = Header(None)) -> str:
    """Generate or use existing trace ID"""
    return x_trace_id or str(uuid.uuid4())


def calculate_risk_score(
    symbol: str,
    quantity: int,
    price: float,
    pnl: float,
    order_type: OrderType
) -> tuple[float, Dict[str, Any]]:
    """
    Calculate risk score based on multiple factors
    Returns: (risk_score, risk_factors)
    Risk score ranges from 0-100, where higher is riskier
    """
    risk_score = 0
    risk_factors = {}
    
    # Factor 1: Position size risk (0-30 points)
    # Large positions are riskier
    position_value = quantity * price
    if position_value > 100000:
        position_risk = 30
    elif position_value > 50000:
        position_risk = 20
    elif position_value > 10000:
        position_risk = 10
    else:
        position_risk = 5
    
    risk_score += position_risk
    risk_factors["position_size_risk"] = position_risk
    risk_factors["position_value"] = position_value
    
    # Factor 2: PnL risk (0-30 points)
    # Negative PnL or large PnL values are riskier
    if pnl < -5000:
        pnl_risk = 30
    elif pnl < -1000:
        pnl_risk = 20
    elif pnl < 0:
        pnl_risk = 10
    elif pnl > 10000:
        pnl_risk = 15  # Very high gains also carry risk
    else:
        pnl_risk = 5
    
    risk_score += pnl_risk
    risk_factors["pnl_risk"] = pnl_risk
    risk_factors["estimated_pnl"] = pnl
    
    # Factor 3: Quantity risk (0-20 points)
    # Very large quantities are riskier
    if quantity > 500:
        quantity_risk = 20
    elif quantity > 200:
        quantity_risk = 15
    elif quantity > 100:
        quantity_risk = 10
    else:
        quantity_risk = 5
    
    risk_score += quantity_risk
    risk_factors["quantity_risk"] = quantity_risk
    risk_factors["quantity"] = quantity
    
    # Factor 4: Symbol volatility risk (0-20 points)
    # Some symbols are considered more volatile
    volatile_symbols = {"TSLA": 20, "NVDA": 15, "META": 10}
    volatility_risk = volatile_symbols.get(symbol, 5)
    
    risk_score += volatility_risk
    risk_factors["volatility_risk"] = volatility_risk
    risk_factors["symbol"] = symbol
    
    return risk_score, risk_factors


def determine_risk_level(risk_score: float) -> RiskLevel:
    """Determine risk level based on score"""
    if risk_score >= 70:
        return RiskLevel.HIGH
    elif risk_score >= 40:
        return RiskLevel.MEDIUM
    else:
        return RiskLevel.LOW


def get_recommendation(risk_level: RiskLevel, risk_score: float) -> str:
    """Get recommendation based on risk level"""
    if risk_level == RiskLevel.HIGH:
        return f"HIGH RISK (score: {risk_score:.1f}) - Consider reducing position size or rejecting trade"
    elif risk_level == RiskLevel.MEDIUM:
        return f"MEDIUM RISK (score: {risk_score:.1f}) - Proceed with caution, monitor closely"
    else:
        return f"LOW RISK (score: {risk_score:.1f}) - Trade approved with normal monitoring"


@app.get("/")
def root():
    """Root endpoint"""
    return {"message": "Risk Assessment Service", "docs": "/docs"}


@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "risk_service"}


@app.post("/risk/assess", response_model=RiskAssessmentResponse)
async def assess_risk(request_data: RiskAssessmentRequest, request: Request):
    """
    Perform comprehensive risk assessment on a trade order
    Evaluates multiple risk factors and provides approval/rejection recommendation
    """
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    
    # Create trace-specific log file
    get_trace_logger(trace_id)
    
    logger.info("[assess_risk] Risk assessment request received", extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'function': 'assess_risk'})
    logger.info(f"[assess_risk] Assessing risk for - Symbol: {request_data.symbol}, Quantity: {request_data.quantity}, Price: ${request_data.price}, PnL: ${request_data.pnl}, Type: {request_data.order_type}", extra={
        "trace_id": trace_id,
        "order_id": request_data.order_id,
        "function": "assess_risk",
        "symbol": request_data.symbol,
        "quantity": request_data.quantity,
        "price": request_data.price
    })
    
    try:
        # Calculate risk score
        logger.info("[assess_risk] calculate_risk_score processing...", extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'function': 'calculate_risk_score'})
        
        # Simulate slow processing for high-value orders
        position_value = abs(request_data.quantity * request_data.price)
        if position_value > 500000:
            logger.info(f"[assess_risk] High-value order detected (${position_value:.2f}), performing extended risk analysis...", extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'function': 'assess_risk'})
            await asyncio.sleep(6)  # Takes too long, will timeout
        
        # PnL integrity check - detect if PnL calculation seems wrong
        pnl_ratio = abs(request_data.pnl) / position_value if position_value > 0 else 0
        
        # Additional check: For SELL orders, verify PnL makes sense
        if request_data.order_type == "SELL" and request_data.pnl < 0:
            loss_percentage = abs(request_data.pnl) / position_value * 100
            if loss_percentage > 15:
                logger.error(f"[assess_risk] Detected upstream calculation error - SELL order showing {loss_percentage:.1f}% loss", extra={
                    'trace_id': trace_id,
                    'order_id': request_data.order_id,
                    'function': 'assess_risk',
                    'extra_data': {
                        'detection_service': 'risk_service',
                        'suspected_source': 'pricing_service_pnl_calculation',
                        'order_type': 'SELL',
                        'quantity': request_data.quantity,
                        'sell_price': request_data.price,
                        'received_pnl': request_data.pnl,
                        'position_value': position_value,
                        'loss_percentage': loss_percentage,
                        'issue': 'SELL orders should profit when current price > cost basis, but showing large loss',
                        'recommendation': 'Check pricing service calculate_pnl() function for SELL order logic'
                    }
                })
                raise HTTPException(
                    status_code=422,
                    detail=f"Risk service blocked execution: Received invalid PnL data from pricing service. SELL order (qty={request_data.quantity}, price=${request_data.price}) shows unrealistic loss of ${request_data.pnl} ({loss_percentage:.1f}%). SELL orders should profit when sell price exceeds cost basis. Upstream pricing calculation error suspected."
                )
        
        if pnl_ratio > 0.15:  # PnL shouldn't exceed 15% of position value in normal cases
            logger.error(f"[assess_risk] PnL integrity check failed - PnL (${request_data.pnl}) is {pnl_ratio*100:.1f}% of position value (${position_value})", extra={
                'trace_id': trace_id,
                'order_id': request_data.order_id,
                'function': 'assess_risk',
                'extra_data': {
                    'pnl': request_data.pnl,
                    'position_value': position_value,
                    'pnl_ratio': pnl_ratio,
                    'threshold': 0.15,
                    'check_failed': 'pnl_integrity'
                }
            })
            raise HTTPException(
                status_code=422,
                detail=f"Risk assessment failed: PnL calculation integrity check failed. Estimated PnL (${request_data.pnl}) appears inconsistent with position value (${position_value}). Please verify pricing calculations."
            )
        
        risk_score, risk_factors = calculate_risk_score(
            request_data.symbol,
            request_data.quantity,
            request_data.price,
            request_data.pnl,
            request_data.order_type
        )
        
        logger.info(f"[calculate_risk_score] Risk factors breakdown:", extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'function': 'calculate_risk_score', 'extra_data': risk_factors})
        logger.info(f"[calculate_risk_score]   - Position size risk: {risk_factors.get('position_size_risk')} points (Position value: ${risk_factors.get('position_value'):.2f})", extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'function': 'calculate_risk_score'})
        logger.info(f"[calculate_risk_score]   - PnL risk: {risk_factors.get('pnl_risk')} points (Estimated PnL: ${risk_factors.get('estimated_pnl'):.2f})", extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'function': 'calculate_risk_score'})
        logger.info(f"[calculate_risk_score]   - Quantity risk: {risk_factors.get('quantity_risk')} points (Quantity: {risk_factors.get('quantity')})", extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'function': 'calculate_risk_score'})
        logger.info(f"[calculate_risk_score]   - Volatility risk: {risk_factors.get('volatility_risk')} points (Symbol: {risk_factors.get('symbol')})", extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'function': 'calculate_risk_score'})
        logger.info(f"[calculate_risk_score] Total risk score calculated: {risk_score:.1f}/100", extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'function': 'calculate_risk_score', 'extra_data': {'risk_score': risk_score}})
        
        # Determine risk level
        risk_level = determine_risk_level(risk_score)
        logger.info(f"[determine_risk_level] Risk level determined: {risk_level.value}", extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'function': 'determine_risk_level', 'extra_data': {'risk_level': risk_level.value}})
        
        # Determine approval
        # HIGH risk trades are rejected, others are approved
        approved = risk_level != RiskLevel.HIGH
        logger.info(f"[assess_risk] Approval decision: {'APPROVED' if approved else 'REJECTED'} (Risk level: {risk_level.value})", 
                   extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'function': 'assess_risk', 'extra_data': {'approved': approved, 'risk_level': risk_level.value}})
        
        # Get recommendation
        recommendation = get_recommendation(risk_level, risk_score)
        logger.info(f"[get_recommendation] Risk recommendation: {recommendation}", extra={'trace_id': trace_id, 'order_id': request_data.order_id, 'function': 'get_recommendation'})
        
        timestamp = datetime.now().isoformat()
        
        # Store risk assessment
        risk_assessments[request_data.order_id] = {
            "order_id": request_data.order_id,
            "risk_level": risk_level.value,
            "approved": approved,
            "risk_score": risk_score,
            "risk_factors": risk_factors,
            "recommendation": recommendation,
            "timestamp": timestamp
        }
        
        logger.info("[assess_risk] Risk assessment completed", extra={
            "trace_id": trace_id,
            "order_id": request_data.order_id,
            "function": "assess_risk",
            'extra_data': {
                'risk_level': risk_level.value,
                'risk_score': risk_score,
                'approved': approved,
                'recommendation': recommendation
            }
        })
        
        return RiskAssessmentResponse(
            order_id=request_data.order_id,
            risk_level=risk_level,
            approved=approved,
            risk_score=risk_score,
            risk_factors=risk_factors,
            recommendation=recommendation,
            timestamp=timestamp
        )
        
    except Exception as e:
        logger.error("[assess_risk] Unexpected error in risk assessment", extra={
            "trace_id": trace_id,
            "order_id": request_data.order_id,
            "function": "assess_risk",
            "error": str(e)
        })
        raise HTTPException(status_code=500, detail=f"Risk assessment failed: {str(e)}")


@app.get("/risk/{order_id}")
async def get_risk_assessment(order_id: str, request: Request):
    """Get risk assessment for a specific order"""
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    
    logger.info("[get_risk_assessment] Fetching risk assessment", extra={
        "trace_id": trace_id,
        "order_id": order_id,
        "function": "get_risk_assessment"
    })
    
    assessment = risk_assessments.get(order_id)
    if not assessment:
        logger.warning("[get_risk_assessment] Risk assessment not found", extra={
            "trace_id": trace_id,
            "order_id": order_id,
            "function": "get_risk_assessment"
        })
        raise HTTPException(status_code=404, detail="Risk assessment not found")
    
    return assessment


@app.get("/risk/assessments/all")
async def list_risk_assessments(request: Request):
    """List all risk assessments"""
    trace_id = get_trace_id(request.headers.get("X-Trace-Id"))
    
    logger.info("[list_risk_assessments] Listing all risk assessments", extra={
        "trace_id": trace_id,
        "count": len(risk_assessments),
        "function": "list_risk_assessments"
    })
    
    return {
        "assessments": list(risk_assessments.values()),
        "count": len(risk_assessments)
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003)