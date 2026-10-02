"""cz-metrics: Code Zero Feed (czf) reference implementation.

Byte-deterministic ambulance system-status metrics. Same feed in,
identical numbers out, anywhere.
"""

from .models import (
    Agency,
    Call,
    Event,
    EventType,
    Feed,
    Hospital,
    RosterRow,
    Unit,
    UnitState,
)
from .engine import FeedError, apply_feed, availability, minute_index
from .metrics import (
    CodeZeroReport,
    Coverage,
    OffloadStats,
    ResponseStats,
    code_zero,
    coverage,
    offload_delays,
    offload_share,
    response_times,
)

__version__ = "0.1.0"
__all__ = [
    "Agency", "Call", "Event", "EventType", "Feed", "Hospital", "RosterRow",
    "Unit", "UnitState",
    "FeedError", "apply_feed", "availability", "minute_index",
    "CodeZeroReport", "Coverage", "OffloadStats", "ResponseStats",
    "code_zero", "coverage", "offload_delays", "offload_share",
    "response_times",
]
