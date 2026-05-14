from dataclasses import dataclass, asdict, field
from typing import List, Dict, Optional


@dataclass
class Levels:
    entry: float
    stop: float
    target1: float
    target2: float
    risk_reward: float
    better_entry: float
    invalidation: float


@dataclass
class Signal:
    symbol: str
    price: float
    decision: str
    status: str
    lifecycle: str
    action_text: str
    opportunity_score: int
    entry_score: int
    confidence_label: str
    chase_risk: str
    tradeability: str
    catalyst_quality: str
    levels: Levels
    day_change_pct: float
    vwap_distance_pct: float
    ema9_distance_pct: float
    volume_ratio: float
    dollar_volume: float
    atr_pct: float
    spread_pct_est: float
    data_source: str
    data_age_minutes: Optional[float]
    outcome_stats: Dict = field(default_factory=dict)
    advanced_breakdown: Dict = field(default_factory=dict)
    sector_context: Dict = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    previous_status: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)
