from dataclasses import dataclass
from typing import Optional

@dataclass
class Trade:
    trade_id: str
    symbol: str
    quantity: int
    price: float
    trade_type: str
    timestamp: Optional[str] = None

@dataclass
class PriceData:
    trade_id: str
    symbol: str
    computed_price: float

@dataclass
class PnlData:
    trade_id: str
    pnl_value: float
    symbol: str
    price: float
    quantity: int
    cost: float

@dataclass
class RiskData:
    trade_id: str
    risk_level: str
    pnl_value: float
    quantity: int