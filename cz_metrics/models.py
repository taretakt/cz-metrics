"""Canonical Code Zero Feed (czf) schema.

Boring entity names, no nesting, no virtual entities. Hospitals are opaque IDs
in v0.1 (real-world identity is the political layer, not the data layer).
Every timestamp is a CAD timestamp -- the record of a crew action -- in UTC.
No PHI, no addresses, no free text.

The word "offload" never appears in the schema. It survives only as a public
alias for the two delays derived from AT_HOSPITAL / HANDOFF / UNIT_CLEARED.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class UnitState(StrEnum):
    AVAILABLE = "AVAILABLE"
    ENROUTE = "ENROUTE"
    ONSCENE = "ONSCENE"
    TRANSPORTING = "TRANSPORTING"
    AT_HOSPITAL = "AT_HOSPITAL"
    HANDOFF = "HANDOFF"
    UNIT_CLEARED = "UNIT_CLEARED"
    DOWN = "DOWN"
    STAGING = "STAGING"


class EventType(StrEnum):
    DISPATCHED = "DISPATCHED"
    ONSCENE = "ONSCENE"
    DEPART_SCENE = "DEPART_SCENE"
    AT_HOSPITAL = "AT_HOSPITAL"
    HANDOFF = "HANDOFF"
    UNIT_CLEARED = "UNIT_CLEARED"
    STAGING = "STAGING"
    UP = "UP"
    DOWN = "DOWN"


# A unit is dispatchable iff its state is in this set.
DISPATCHABLE_STATES = frozenset({UnitState.AVAILABLE, UnitState.STAGING})


class Agency(BaseModel):
    id: str


class Unit(BaseModel):
    id: str
    agency_id: str


class Hospital(BaseModel):
    id: str  # opaque in v0.1


class Call(BaseModel):
    id: str
    priority: int = Field(ge=1)  # P1 = 1, highest
    agency_id: str


class Event(BaseModel):
    """One CAD timestamp (a crew action), UTC. Never PHI."""

    ts: datetime
    unit_id: str
    type: EventType
    call_id: str | None = None  # required for DISPATCHED/ONSCENE/DEPART_SCENE/AT_HOSPITAL/HANDOFF/UNIT_CLEARED
    hospital_id: str | None = None  # required for AT_HOSPITAL/HANDOFF


class Feed(BaseModel):
    """The full telemetry input for a service area. One feed in -> M1..M5 out."""

    agency: Agency
    units: list[Unit] = []
    hospitals: list[Hospital] = []
    calls: list[Call] = []
    events: list[Event] = []


class RosterRow(BaseModel):
    """Scheduled crewed shift for a unit (agency data, not CAD telemetry).

    Used only by M5 (coverage). Start/end are UTC.
    """

    unit_id: str
    start: datetime
    end: datetime
