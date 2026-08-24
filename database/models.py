"""Modelos inmutables usados por identidad y sesiones."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class IdentityBinding:
    """Relacion temporal entre un track local y un empleado verificado."""
    camera_id: str
    track_id: str
    employee_id: str
    confidence: float
    source: str
    identified_at: datetime
    last_seen: datetime
    expires_at: datetime


@dataclass(frozen=True)
class ZoneSession:
    """Periodo durante el cual un empleado identificado estuvo en una zona."""
    employee_id: str
    zone: str
    camera_id: str
    entered_at: datetime
    exited_at: Optional[datetime] = None
