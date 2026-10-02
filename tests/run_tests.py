"""czf reference implementation tests. Run: .venv/bin/python tests/run_tests.py

Worked examples (deterministic by construction):
  M1: two units go out 08:00, clear 08:18:59 / 08:19:30 -> A(t)=0 for
      08:00..08:18 = 19 minutes. count=1, total=19, max=19, zones=1.
  M3: P1 calls dispatch 08:09 / on-scene 08:15 (6 min) and 08:11:30 /
      08:24 (12.5 -> floored 12) -> mean 9.0. P2: 08:10 / 08:20 -> 10.0.
  M4: unit_hold 239+210 = 449 s / unavailable 39 unit-min = 2340 s -> 0.1919.
  M5: roster 3 units 08:00-09:00 (180 min), outages 8+15+11=34 -> 146/180
      = 0.8111.
  Engine timing: DISPATCHED/DOWN take a unit out in the containing minute;
  UNIT_CLEARED/UP/STAGING return it at the NEXT minute boundary.
"""

import sys
from datetime import datetime, timezone

sys.path.insert(0, "")

from cz_metrics import (
    code_zero, coverage, offload_delays, offload_share, response_times,
)
from cz_metrics.engine import FeedError, apply_feed, availability
from cz_metrics.models import Agency, Call, Event, EventType, Feed, Hospital, RosterRow, Unit

UTC = timezone.utc
T = lambda s: datetime.fromisoformat(s).astimezone(UTC)  # noqa: E731


def minute_of(feed: Feed, hhmm: str) -> int:
    """Epoch index for 'HH:MM' (UTC) on the feed's date."""
    base = min(e.ts for e in feed.events)
    hh, mm = map(int, hhmm.split(":"))
    t = base.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return int(t.astimezone(UTC).timestamp() // 60)

PASS = 0


def ok(label: str, cond: bool):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  PASS  {label}")


# ---------------------------------------------------------------- fixture 1
# U1, U2: full hospital run producing a 19-minute code-zero window at H1.
f1 = Feed(
    agency=Agency(id="AGT1"),
    units=[Unit(id="U1", agency_id="AGT1"), Unit(id="U2", agency_id="AGT1")],
    hospitals=[Hospital(id="H1")],
    calls=[
        Call(id="C1", priority=1, agency_id="AGT1"),
        Call(id="C2", priority=1, agency_id="AGT1"),
    ],
    events=[
        Event(ts=T("2026-10-02T08:00:00+00:00"), unit_id="U1", type=EventType.DISPATCHED, call_id="C1"),
        Event(ts=T("2026-10-02T08:00:00+00:00"), unit_id="U2", type=EventType.DISPATCHED, call_id="C2"),
        Event(ts=T("2026-10-02T08:05:00+00:00"), unit_id="U1", type=EventType.ONSCENE, call_id="C1"),
        Event(ts=T("2026-10-02T08:08:00+00:00"), unit_id="U2", type=EventType.ONSCENE, call_id="C2"),
        Event(ts=T("2026-10-02T08:10:00+00:00"), unit_id="U1", type=EventType.DEPART_SCENE, call_id="C1"),
        Event(ts=T("2026-10-02T08:12:00+00:00"), unit_id="U2", type=EventType.DEPART_SCENE, call_id="C2"),
        Event(ts=T("2026-10-02T08:15:00+00:00"), unit_id="U1", type=EventType.AT_HOSPITAL, call_id="C1", hospital_id="H1"),
        Event(ts=T("2026-10-02T08:16:00+00:00"), unit_id="U2", type=EventType.AT_HOSPITAL, call_id="C2", hospital_id="H1"),
        Event(ts=T("2026-10-02T08:18:00+00:00"), unit_id="U1", type=EventType.HANDOFF, call_id="C1", hospital_id="H1"),
        Event(ts=T("2026-10-02T08:18:59+00:00"), unit_id="U1", type=EventType.UNIT_CLEARED, call_id="C1", hospital_id="H1"),
        Event(ts=T("2026-10-02T08:19:00+00:00"), unit_id="U2", type=EventType.HANDOFF, call_id="C2", hospital_id="H1"),
        Event(ts=T("2026-10-02T08:19:30+00:00"), unit_id="U2", type=EventType.UNIT_CLEARED, call_id="C2", hospital_id="H1"),
    ],
)

# ---------------------------------------------------------------- fixture 2
# U3-U5: response-time and coverage scenario (no-transport calls).
f2 = Feed(
    agency=Agency(id="AGT1"),
    units=[
        Unit(id="U3", agency_id="AGT1"), Unit(id="U4", agency_id="AGT1"),
        Unit(id="U5", agency_id="AGT1"),
    ],
    calls=[
        Call(id="C3", priority=1, agency_id="AGT1"),
        Call(id="C4", priority=1, agency_id="AGT1"),
        Call(id="C5", priority=2, agency_id="AGT1"),
    ],
    events=[
        Event(ts=T("2026-10-02T08:09:00+00:00"), unit_id="U3", type=EventType.DISPATCHED, call_id="C3"),
        Event(ts=T("2026-10-02T08:11:30+00:00"), unit_id="U4", type=EventType.DISPATCHED, call_id="C4"),
        Event(ts=T("2026-10-02T08:10:00+00:00"), unit_id="U5", type=EventType.DISPATCHED, call_id="C5"),
        Event(ts=T("2026-10-02T08:15:00+00:00"), unit_id="U3", type=EventType.ONSCENE, call_id="C3"),
        Event(ts=T("2026-10-02T08:24:00+00:00"), unit_id="U4", type=EventType.ONSCENE, call_id="C4"),
        Event(ts=T("2026-10-02T08:20:00+00:00"), unit_id="U5", type=EventType.ONSCENE, call_id="C5"),
        Event(ts=T("2026-10-02T08:16:00+00:00"), unit_id="U3", type=EventType.UNIT_CLEARED, call_id="C3"),
        Event(ts=T("2026-10-02T08:25:00+00:00"), unit_id="U4", type=EventType.UNIT_CLEARED, call_id="C4"),
        Event(ts=T("2026-10-02T08:20:30+00:00"), unit_id="U5", type=EventType.UNIT_CLEARED, call_id="C5"),
    ],
)
roster = [
    RosterRow(unit_id="U3", start=T("2026-10-02T08:00:00+00:00"), end=T("2026-10-02T09:00:00+00:00")),
    RosterRow(unit_id="U4", start=T("2026-10-02T08:00:00+00:00"), end=T("2026-10-02T09:00:00+00:00")),
    RosterRow(unit_id="U5", start=T("2026-10-02T08:00:00+00:00"), end=T("2026-10-02T09:00:00+00:00")),
]

print("== engine: state machine + availability ==")
ok("final states U1/U2 back AVAILABLE", apply_feed(f1) == {"U1": "AVAILABLE", "U2": "AVAILABLE"})
av = availability(f1)
ok("A(t)=0 for 19 consecutive minutes (08:00..08:18)", sum(1 for v in av.values() if v == 0) == 19)
ok("A(t)=0 run starts at epoch 08:00", av[minute_of(f1, "08:00")] == 0)

# exact epoch checks
av480 = availability(f1)
ok("epoch 08:18 has A=0 (both out)", av480[minute_of(f1, "08:18")] == 0)
ok("epoch 08:19 has A=1 (U1 back, U2 out)", av480[minute_of(f1, "08:19")] == 1)
ok("epoch 08:20 has A=2 (both back)", av480[minute_of(f1, "08:20")] == 2)

# STAGING counts, DOWN does not
f3 = Feed(
    agency=Agency(id="A"),
    units=[Unit(id="S1", agency_id="A"), Unit(id="D1", agency_id="A")],
    events=[
        Event(ts=T("2026-10-02T08:00:00+00:00"), unit_id="S1", type=EventType.STAGING),
        Event(ts=T("2026-10-02T08:00:00+00:00"), unit_id="D1", type=EventType.DOWN),
        Event(ts=T("2026-10-02T08:02:00+00:00"), unit_id="D1", type=EventType.UP),
    ],
)
av3 = availability(f3)
ok("STAGING counts as available, DOWN does not (A=1 at 08:00)", av3[minute_of(f3, "08:00")] == 1)
ok("DOWN persists through 08:02 (out until next boundary)", av3[minute_of(f3, "08:02")] == 1)
ok("DOWN unit returns on UP at 08:03 (next boundary)", av3[minute_of(f3, "08:03")] == 2)

# illegal transition
bad = Feed(
    agency=Agency(id="A"),
    units=[Unit(id="X1", agency_id="A")],
    events=[Event(ts=T("2026-10-02T08:00:00+00:00"), unit_id="X1", type=EventType.AT_HOSPITAL, call_id="C9", hospital_id="H1")],
)
try:
    apply_feed(bad)
    ok("illegal transition raises FeedError", False)
except FeedError:
    ok("illegal transition raises FeedError", True)

print("== M1 code_zero ==")
cz1 = code_zero(f1)
cz1b = code_zero(f1)
ok("M1 count = 1", cz1.count == 1)
ok("M1 total = 19 minutes", cz1.total_min == 19)
ok("M1 max run = 19 minutes", cz1.max_run_min == 19)
ok("M1 zones = 1 (H1)", cz1.zones == 1)
ok("M1 byte-deterministic (identical on rerun)", cz1 == cz1b)
ok("M1 empty feed -> zeros", code_zero(Feed(agency=Agency(id="AGT1"))).total_min == 0)

print("== M2 offload_delays ==")
o2 = offload_delays(f1)
ok("M2 H1 count = 2", o2["H1"].count == 2)
ok("M2 H1 handover_wait mean = 3.0 min", o2["H1"].handover_wait_mean_min == 3.0)
ok("M2 H1 unit_hold mean = 3.7417 min", o2["H1"].unit_hold_mean_min == 3.7417)
ok("M2 H1 unit_hold p95 = 3.9833 min (239s)", o2["H1"].unit_hold_p95_min == 3.9833)

print("== M3 response_times ==")
r3 = response_times(f2)
ok("M3 P1 mean = 9.0 min ((6+12)/2)", r3[1].mean_min == 9.0)
ok("M3 P2 mean = 10.0 min", r3[2].mean_min == 10.0)
ok("M3 P1 count = 2", r3[1].count == 2)

print("== M4 offload_share ==")
ok("M4 shield = 0.1919 (449s / 2340s)", offload_share(f1) == 0.1919)

print("== M5 coverage ==")
c5 = coverage(f2, roster)
ok("M5 hour 08 scheduled = 180 crewed min", c5[8].scheduled_min == 180)
ok("M5 hour 08 actual = 146 min", c5[8].actual_min == 146)
ok("M5 hour 08 ratio = 0.8111", c5[8].ratio == 0.8111)


print("== corpus: jurisdiction mappings ==")
import os as _os, json as _json
corpus_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "corpus")

def load_feed(name):
    """Load a corpus feed as canonical JSON and validate against the schema."""
    with open(_os.path.join(corpus_dir, name + ".feed.json")) as _f:
        data = _json.load(_f)
    _roster = [RosterRow(**r) for r in data.pop("roster", [])]
    return Feed(**data), _roster

# BC "Level Zero": zero units available -> M1 code_zero
bc, _ = load_feed("bc_level_zero")
cz_bc = code_zero(bc)
ok("corpus BC: Level Zero -> M1 count = 1", cz_bc.count == 1)
ok("corpus BC: M1 run = 17 minutes", cz_bc.total_min == 17 and cz_bc.max_run_min == 17)
ok("corpus BC: M1 zones = 2 (H1, H2)", cz_bc.zones == 2)
ok("corpus BC: M3 P1 mean = 3.0 min", response_times(bc)[1].mean_min == 3.0)

# Ontario "offload delay" / ramping: ED gridlock -> M2/M4, and it zeroes the fleet
on, _ = load_feed("ontario_offload_delay")
od_on = offload_delays(on)["H1"]
ok("corpus ON: offload delay -> M2 count = 3", od_on.count == 3)
ok("corpus ON: M2 handover_wait mean = 12.5 min", od_on.handover_wait_mean_min == 12.5)
ok("corpus ON: M2 handover_wait p95 = 13.0 min", od_on.handover_wait_p95_min == 13.0)
ok("corpus ON: M2 unit_hold mean = 14.1667 min", round(od_on.unit_hold_mean_min, 4) == 14.1667)
ok("corpus ON: M4 shield = 0.5667 (2550s hold / 4500s lost)", round(offload_share(on), 4) == 0.5667)
ok("corpus ON: gridlock also zeroes the fleet (M1 = 20 min)", code_zero(on).total_min == 20)

# Rural system status management: thin coverage -> M5 / M3
ssm, roster_ssm = load_feed("ssm_sparse_coverage")
c_ssm = coverage(ssm, roster_ssm)
ok("corpus SSM: M3 P1 = 18 min (08:10 -> 08:28)", response_times(ssm)[1].mean_min == 18.0)
ok("corpus SSM: M5 h8 scheduled = 120 crewed min", c_ssm[8].scheduled_min == 120)
ok("corpus SSM: M5 h8 actual = 62 min", c_ssm[8].actual_min == 62)
ok("corpus SSM: M5 h8 ratio = 0.5167", round(c_ssm[8].ratio, 4) == 0.5167)
ok("corpus SSM: M5 h9 ratio = 0.975", round(c_ssm[9].ratio, 4) == 0.975)

print(f"\n{'-'*40}\nALL {PASS} CHECKS PASSED")
