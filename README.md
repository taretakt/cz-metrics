# cz-metrics

Reference implementation of the **Code Zero Feed (czf)** — a byte-deterministic,
open standard for ambulance system-status telemetry. Same feed in, identical
numbers out, anywhere.

Serves as the analysis engine for Vanberkel-style EMS operations research and
powers **Siding** (product name): dispatch is the main line, the ramp is a
siding, a waiting unit is a car holding for block, and A(t)=0 is a full block.
The rail frame is a frame — EMS vocabulary stays canonical in the schema.

## Why

"Code Zero" means different things in every jurisdiction (BC: zero ambulances
available; Ontario: ED gridlock; elsewhere: ramping). The standard maps every
local vocabulary to one metric family, M1–M5. The one real flaw in earlier
drafts was the word "offload" — two meanings depending on whose clock you use.
It is gone from the schema, replaced by three unambiguous CAD events.

## Canonical events (all timestamps are CAD timestamps, UTC)

| Event           | Meaning                                                              |
|-----------------|----------------------------------------------------------------------|
| `AT_HOSPITAL`   | Unit arrives at ED; patient transfer begins                          |
| `HANDOFF`       | ED staff accept clinical responsibility                              |
| `UNIT_CLEARED`  | Crew released; unit dispatchable in CAD                             |

**Offload** survives only as a public alias for the two derived delays:
`handover_wait` = HANDOFF − AT_HOSPITAL (what hospitals care about),
`unit_hold` = UNIT_CLEARED − AT_HOSPITAL (what crews care about).

## Metrics

| ID | Name            | Definition                                                          |
|----|-----------------|---------------------------------------------------------------------|
| M1 | `code_zero_event` | Runs of A(t)=0: count, total min, longest run, zones. Public name: **Code Zero** |
| M2 | `offload_delays`  | handover_wait / unit_hold per hospital (mean, p95)                  |
| M3 | `response_times`  | Dispatch→on-scene minutes by priority                               |
| M4 | `offload_share`   | unit_hold seconds ÷ total unavailable unit-seconds (the shield metric) |
| M5 | `coverage`        | actual available unit-minutes ÷ scheduled crewed unit-minutes, per hour |

## Determinism rules

- Epochs are 1-minute, aligned to UTC minute boundaries.
- A unit is dispatchable in epoch *m* iff it is in `AVAILABLE` or `STAGING`
  (STAGING counts; DOWN does not).
- A `DISPATCHED`/`DOWN` event takes the unit out at the minute containing the
  event; `UNIT_CLEARED`/`UP`/`STAGING` returns it at the next minute boundary.
- All durations are integer seconds; means/p95 in fixed order → identical
  output for identical input on any platform.

## Usage

```python
from cz_metrics import code_zero, response_times
from cz_metrics.models import Feed

feed = Feed.model_validate_json(open("feed.json").read())
cz = code_zero(feed)          # M1
pri = response_times(feed)    # M3
```

## Tests

```bash
uv venv .venv --python 3.13
uv pip install --python .venv/bin/python pydantic
.venv/bin/python tests/run_tests.py
```
