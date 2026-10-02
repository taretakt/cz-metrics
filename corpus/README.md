# Jurisdiction corpus

The Code Zero Feed standard exists because "code zero" means different things
in every jurisdiction. Each file here is a small, fully worked example: a
synthetic feed shaped by one jurisdiction's documented operational vocabulary,
with the canonical M1–M5 numbers the reference implementation must produce.

> **Honesty label.** These feeds are illustrative fixtures, not real operational
> data. They are invented to demonstrate how each local vocabulary maps onto the
> canonical metric family. They are not sourced from, endorsed by, or a claim
> about any ambulance service or jurisdiction's actual system status.

| File | Local vocabulary | Load-bearing metric(s) | Story |
|------|------------------|------------------------|-------|
| `bc_level_zero.feed.json` | "Level Zero" — zero units available | M1 | All three units committed by 08:00 → A(t)=0 for 17 minutes, two hospitals in the run |
| `ontario_offload_delay.feed.json` | "Offload delay" / ramping / ED gridlock | M2, M4 | Crews reach the ED fast but the ED can't take handoffs: mean handover wait 12.5 min, 0.567 of all unavailable unit-time is hospital hold |
| `ssm_sparse_coverage.feed.json` | System status management, thin rural fleet | M5, M3 | Two units cover a large area: 18-min P1 response, hour-8 coverage 0.517 vs hour-9 0.975 |

## What each row proves

- **BC → M1.** "Level Zero" is the local name for `A(t)=0`. When every unit is
  committed, the standard produces a code-zero event: count 1, 17 minutes,
  2 zones (two hospitals absorbed transports inside the run).
- **Ontario → M2/M4.** "Offload delay" is what happens at the hospital door:
  `handover_wait` (ED's clock) and `unit_hold` (crew's clock), plus the shield
  metric M4 — the fraction of lost capacity that is hospital hold, 0.567 here.
  Note this feed *also* produces a 20-minute M1 run: gridlock zeros the fleet.
  The corpus shows both faces; the local vocabulary names the mechanism (M2/M4),
  the system effect still shows up in M1.
- **Rural SSM → M5/M3.** "Coverage" is the operative question when the fleet is
  thin: 62 of 120 scheduled crewed minutes actually available in hour 8, and a
  priority-1 response of 18 minutes (08:10 → 08:28) is what that coverage buys.

## Run

The corpus is wired into the main test gate:

```bash
.venv/bin/python tests/run_tests.py
```

Each feed is loaded as JSON, validated by the canonical schema, run through all
five metric families, and checked against the exact numbers in the table above.