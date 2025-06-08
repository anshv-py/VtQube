from dataclasses import dataclass
from enum import Enum
from typing import Optional

class MonitoringStatus(Enum):
    STOPPED = "Stopped"
    RUNNING = "Running"
    PAUSED = "Paused"
    ERROR = "Error"

@dataclass
class VolumeData:
    timestamp: str
    symbol: str
    volume: int
    opening_volume: int
    change_percent: float
    price: float
    tbq: Optional[int] = None
    tsq: Optional[int] = None
    tbq_change_percent: Optional[float] = None
    tsq_change_percent: Optional[float] = None
    ratio: Optional[float] = None
    alert_triggered: Optional[bool] = False
    open_price: Optional[float] = None
    high_price: Optional[float] = None
    low_price: Optional[float] = None
    close_price: Optional[float] = None
    is_tbq_baseline: Optional[bool] = False
    is_tsq_baseline: Optional[bool] = False
    instrument_type: Optional[str] = None
    expiry_date: Optional[str] = None
    strike_price: Optional[float] = None
    day_high_tbq: Optional[int] = None
    day_low_tbq: Optional[int] = None
    day_high_tsq: Optional[int] = None 
    day_low_tsq: Optional[int] = None