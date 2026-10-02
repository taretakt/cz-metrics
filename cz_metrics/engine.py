"""Deterministic unit state machine and 1-minute availability epochs.

Canonical rules (czf):
- Every epoch is one UTC minute, aligned to the minute boundary.
- A unit is dispatchable in epoch m iff its state at the start of epoch m is
  AVAILABLE or STAGING. STAGING counts as available; DOWN does not.
- Effect timing: a DISPATCHED/DOWN event takes the unit out starting at the
  minute containing the event; a UNIT_CLEARED/UP/STAGING event returns it at
  the NEXT minute boundary. Same feed in -> identical A(t) out, anywhere.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from .models import EventType, Feed, UnitState

UTC = timezone.utc


class FeedError(ValueError):
    """A feed that violates the czf contract (bad transition, missing field, ...)."""


_TRANSITIONS: dict[UnitState, dict[EventType, UnitState]] = {
    UnitState.AVAILABLE: {
        EventType.DISPATCHED: UnitState.ENROUTE,
        EventType.STAGING: UnitState.STAGING,
        EventType.DOWN: UnitState.DOWN,
    },
    UnitState.STAGING: {
        EventType.DISPATCHED: UnitState.ENROUTE,
        EventType.DOWN: UnitState.DOWN,
    },
    UnitState.ENROUTE: {
        EventType.ONSCENE: UnitState.ONSCENE,
        EventType.DOWN: UnitState.DOWN,
    },
    UnitState.ONSCENE: {
        EventType.DEPART_SCENE: UnitState.TRANSPORTING,
        EventType.UNIT_CLEARED: UnitState.AVAILABLE,  # cleared on scene, no transport
        EventType.DOWN: UnitState.DOWN,
    },
    UnitState.TRANSPORTING: {
        EventType.AT_HOSPITAL: UnitState.AT_HOSPITAL,
        EventType.DOWN: UnitState.DOWN,
    },
    UnitState.AT_HOSPITAL: {
        EventType.HANDOFF: UnitState.HANDOFF,
        EventType.DOWN: UnitState.DOWN,
    },
    UnitState.HANDOFF: {
        EventType.UNIT_CLEARED: UnitState.AVAILABLE,
        EventType.DOWN: UnitState.DOWN,
    },
    UnitState.DOWN: {
        EventType.UP: UnitState.AVAILABLE,
    },
}


def minute_index(ts: datetime) -> int:
    """UTC-aligned epoch: minutes since 1970-01-01T00:00Z."""
    if ts.tzinfo is None:
        raise FeedError(f"naive timestamp in feed: {ts} (czf requires UTC)")
    return int(ts.astimezone(timezone.utc).timestamp() // 60)


def _order(ev) -> int:
    # Deterministic tie-break between events sharing (ts, unit_id).
    return list(EventType).index(ev.type)


def _sorted_events(feed: Feed) -> list:
    return sorted(feed.events, key=lambda e: (minute_index(e.ts), e.unit_id, _order(e)))


def apply_feed(feed: Feed) -> dict[str, UnitState]:
    """Validate and replay a feed; return the final state of every unit.

    Requires per-unit events in non-decreasing timestamp order and every
    transition legal. Raises FeedError otherwise.
    """
    events = _sorted_events(feed)
    state: dict[str, UnitState] = {}
    last_ts: dict[str, int] = {}
    for ev in events:
        m = minute_index(ev.ts)
        unit = ev.unit_id
        if m < last_ts.get(unit, -(10**18)):
            raise FeedError(f"out-of-order event for unit {unit}: {ev.ts}")
        last_ts[unit] = m
        cur = state.get(unit, UnitState.AVAILABLE)
        try:
            nxt = _TRANSITIONS[cur][ev.type]
        except KeyError:
            raise FeedError(
                f"illegal transition {cur} --{ev.type}--> ? (unit {unit}, {ev.ts})"
            ) from None
        if ev.type in (EventType.DISPATCHED, EventType.ONSCENE, EventType.DEPART_SCENE) and not ev.call_id:
            raise FeedError(f"{ev.type} without call_id (unit {unit}, {ev.ts})")
        if ev.type in (EventType.AT_HOSPITAL, EventType.HANDOFF) and not (ev.call_id and ev.hospital_id):
            raise FeedError(f"{ev.type} requires call_id and hospital_id (unit {unit}, {ev.ts})")
        state[unit] = nxt
    return state


def unavailable_intervals(feed: Feed) -> list[tuple[str, int, int]]:
    """Per unit, half-open intervals [start_epoch, end_epoch) of unavailability.

    start = minute containing DISPATCHED/DOWN; end = minute of the returning
    event (UNIT_CLEARED/UP/STAGING) + 1.
    """
    events = _sorted_events(feed)
    take_out = {EventType.DISPATCHED, EventType.DOWN}
    bring_back = {EventType.UNIT_CLEARED, EventType.UP, EventType.STAGING}
    out_start: dict[str, int] = {}
    intervals: list[tuple[str, int, int]] = []
    for ev in events:
        m = minute_index(ev.ts)
        if ev.type in take_out and ev.unit_id not in out_start:
            out_start[ev.unit_id] = m
        elif ev.type in bring_back and ev.unit_id in out_start:
            intervals.append((ev.unit_id, out_start.pop(ev.unit_id), m + 1))
    # anyone still out at the end of the feed stays out (span ends at last event)
    return intervals


def availability(feed: Feed) -> dict[int, int]:
    """A(t): dispatchable units per 1-minute epoch, UTC-aligned.

    Span: first event epoch through the epoch after the last event. A unit is
    counted in epoch m iff no unavailability interval covers m.
    """
    intervals = unavailable_intervals(feed)
    if not feed.events:
        return {}
    lo = min(minute_index(e.ts) for e in feed.events)
    hi = max(minute_index(e.ts) for e in feed.events)
    unit_ids = {u.id for u in feed.units} | {e.unit_id for e in feed.events}
    by_unit: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for uid, s, e in intervals:
        by_unit[uid].append((s, e))
    avail: dict[int, int] = {}
    for m in range(lo, hi + 2):
        avail[m] = sum(
            1 for uid in unit_ids if not any(s <= m < e for s, e in by_unit.get(uid, []))
        )
    return avail
