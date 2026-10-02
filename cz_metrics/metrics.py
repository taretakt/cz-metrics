"""M1-M5 derived metrics.

Determinism: all durations are integer seconds; aggregate means and p95 are
computed in fixed operation order. Identical input -> identical output.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from .engine import availability, minute_index, unavailable_intervals
from .models import EventType, Feed, RosterRow

# --------------------------------------------------------------------------
# M1 - code_zero_event (public name: "Code Zero")
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CodeZeroRun:
    start_epoch: int
    end_epoch_exclusive: int
    duration_min: int


@dataclass(frozen=True)
class CodeZeroReport:
    count: int
    total_min: int
    max_run_min: int
    zones: int
    runs: tuple[CodeZeroRun, ...] = ()


def code_zero(feed: Feed) -> CodeZeroReport:
    """Runs of A(t)=0: count, total minutes, longest run, distinct zones."""
    avail = availability(feed)
    if not avail:
        return CodeZeroReport(0, 0, 0, 0)
    lo, hi = min(avail), max(avail)
    runs: list[CodeZeroRun] = []
    start: int | None = None
    for m in range(lo, hi + 1):
        if avail.get(m, 0) == 0 and start is None:
            start = m
        elif avail.get(m, 0) > 0 and start is not None:
            runs.append(CodeZeroRun(start, m, m - start))
            start = None
    if start is not None:
        runs.append(CodeZeroRun(start, hi + 1, hi + 1 - start))
    if not runs:
        return CodeZeroReport(0, 0, 0, 0)
    # zones = distinct hospitals with AT_HOSPITAL events inside a zero run
    zone_ids: set[str] = set()
    for ch in _hospital_events(feed):
        if any(r.start_epoch <= ch[0] < r.end_epoch_exclusive for r in runs):
            zone_ids.add(ch[1])
    return CodeZeroReport(
        count=len(runs),
        total_min=sum(r.duration_min for r in runs),
        max_run_min=max(r.duration_min for r in runs),
        zones=len(zone_ids),
        runs=tuple(runs),
    )


def _hospital_events(feed: Feed) -> list[tuple[int, str]]:
    return [
        (minute_index(ev.ts), ev.hospital_id)
        for ev in feed.events
        if ev.type == EventType.AT_HOSPITAL and ev.hospital_id
    ]


# --------------------------------------------------------------------------
# M2 - offload_delays (handover_wait / unit_hold, per hospital)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class OffloadStats:
    count: int
    handover_wait_mean_min: float
    handover_wait_p95_min: float
    unit_hold_mean_min: float
    unit_hold_p95_min: float


def _p95(values: list[int]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return float(s[math.ceil(0.95 * len(s)) - 1])


def offload_delays(feed: Feed) -> dict[str, OffloadStats]:
    """Per hospital, per call:
    handover_wait = HANDOFF - AT_HOSPITAL (what hospitals care about)
    unit_hold     = UNIT_CLEARED - AT_HOSPITAL (what crews care about)
    Both are CAD timestamps; "offload" is only this pair's public alias.
    """
    per_call: dict[str, dict] = {}
    for ev in feed.events:
        if ev.type in (EventType.AT_HOSPITAL, EventType.HANDOFF, EventType.UNIT_CLEARED):
            per_call.setdefault(ev.call_id, {})[ev.type] = (
                ev.ts, ev.hospital_id,
            )
    by_hospital: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for rec in per_call.values():
        if EventType.AT_HOSPITAL not in rec or EventType.HANDOFF not in rec:
            continue
        if EventType.UNIT_CLEARED not in rec:
            continue
        at_h, hid = rec[EventType.AT_HOSPITAL]
        hw = int((rec[EventType.HANDOFF][0] - at_h).total_seconds())
        uh = int((rec[EventType.UNIT_CLEARED][0] - at_h).total_seconds())
        if hid is not None:
            by_hospital[hid].append((hw, uh))
    out: dict[str, OffloadStats] = {}
    for hid, pairs in by_hospital.items():
        hw = [p[0] for p in pairs]
        uh = [p[1] for p in pairs]
        out[hid] = OffloadStats(
            count=len(pairs),
            handover_wait_mean_min=round(sum(hw) / len(hw) / 60, 4),
            handover_wait_p95_min=round(_p95(hw) / 60, 4),
            unit_hold_mean_min=round(sum(uh) / len(uh) / 60, 4),
            unit_hold_p95_min=round(_p95(uh) / 60, 4),
        )
    return out


# --------------------------------------------------------------------------
# M3 - response_times (dispatch -> on-scene, by priority)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ResponseStats:
    count: int
    mean_min: float


def response_times(feed: Feed) -> dict[int, ResponseStats]:
    """Response time = ONSCENE - DISPATCHED per call, floored to whole
    minutes; mean per priority is the floor of the mean of floored values."""
    dispatch: dict[str, object] = {}
    for ev in feed.events:
        if ev.type == EventType.DISPATCHED and ev.call_id:
            dispatch.setdefault(ev.call_id, ev.ts)
    priority: dict[str, int] = {c.id: c.priority for c in feed.calls}
    per_priority: dict[int, list[int]] = defaultdict(list)
    for ev in feed.events:
        if ev.type == EventType.ONSCENE and ev.call_id and ev.call_id in dispatch:
            p = priority.get(ev.call_id)
            if p is None:
                continue
            secs = int((ev.ts - dispatch[ev.call_id]).total_seconds())
            per_priority[p].append(secs // 60)
    out: dict[int, ResponseStats] = {}
    for p in sorted(per_priority):
        vals = per_priority[p]
        out[p] = ResponseStats(count=len(vals), mean_min=float(sum(vals) // len(vals)))
    return out


# --------------------------------------------------------------------------
# M4 - offload_share (the shield metric)
# --------------------------------------------------------------------------


def offload_share(feed: Feed) -> float:
    """unit_hold seconds / total unavailable unit-seconds.

    Share of all lost capacity absorbed at the hospital door. 4dp, rounded.
    """
    hold = sum(
        s.unit_hold_mean_min * s.count for s in offload_delays(feed).values()
    ) * 60
    unavail = sum((e - s) * 60 for _, s, e in unavailable_intervals(feed))
    if unavail <= 0:
        return 0.0
    return round(hold / unavail, 4)


# --------------------------------------------------------------------------
# M5 - coverage (actual available / scheduled crewed, per UTC hour)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Coverage:
    scheduled_min: int
    actual_min: int
    ratio: float


def coverage(feed: Feed, roster: list[RosterRow]) -> dict[int, Coverage]:
    """Per UTC hour-of-day (0-23) bucket: crewed unit-minutes scheduled vs actually
    dispatchable. Roster is agency data; everything else is CAD."""
    by_unit: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for uid, s, e in unavailable_intervals(feed):
        by_unit[uid].append((s, e))
    unit_ids = {r.unit_id for r in roster}
    scheduled: dict[int, int] = defaultdict(int)
    for row in roster:
        s, e = minute_index(row.start), minute_index(row.end)
        for m in range(s, e):
            scheduled[(m // 60) % 24] += 1
    actual: dict[int, int] = defaultdict(int)
    for row in roster:
        s, e = minute_index(row.start), minute_index(row.end)
        for m in range(s, e):
            if not any(s0 <= m < e0 for s0, e0 in by_unit.get(row.unit_id, ())):
                actual[(m // 60) % 24] += 1
    out: dict[int, Coverage] = {}
    for hour in sorted(set(scheduled) | set(actual)):
        sch, act = scheduled[hour], actual[hour]
        out[hour] = Coverage(
            scheduled_min=sch,
            actual_min=act,
            ratio=round(act / sch, 4) if sch else 0.0,
        )
    return out
