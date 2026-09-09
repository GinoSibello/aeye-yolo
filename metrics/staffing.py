"""Suavizado e histeresis para evitar incidentes por fluctuaciones breves."""

import statistics
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class StaffingObservation:
    """Resultado auditable de procesar un conteo o una ausencia de datos."""

    data_status: str
    raw_count: object
    smoothed_count: object
    staffing_status: str
    rule_state: str
    transition: object = None
    alert: object = None
    seconds_to_alert: object = None


class CountSmoother:
    """Calcula la mediana de los conteos observados dentro de una ventana."""

    def __init__(self, window_seconds=10):
        self.window_seconds = max(0.0, float(window_seconds))
        self.values = deque()

    def reset(self):
        """Descarta valores anteriores cuando se pierde continuidad de datos."""
        self.values.clear()

    def add(self, count, at=None):
        """Agrega un conteo y devuelve una mediana entera redondeada hacia arriba."""
        now = time.monotonic() if at is None else float(at)
        self.values.append((now, int(count)))
        cutoff = now - self.window_seconds
        while len(self.values) > 1 and self.values[0][0] < cutoff:
            self.values.popleft()
        median = statistics.median(value for _, value in self.values)
        return int(median + 0.5)


class StaffingStateMachine:
    """Confirma cambios de dotacion y controla el temporizador de alerta."""

    def __init__(self, camera_cfg, system_cfg):
        self.camera = camera_cfg
        self.minimum = int(camera_cfg.get("min_people", 0))
        self.maximum = int(camera_cfg.get("max_people", 9999))
        self.enabled = bool(camera_cfg.get("monitor_staffing", False))
        self.confirm_seconds = float(system_cfg.get("incident_confirmation_seconds", 30))
        self.recovery_seconds = float(system_cfg.get("recovery_confirmation_seconds", 15))
        self.alert_after = float(system_cfg.get("alert_after_seconds", 900))
        self.smoother = CountSmoother(system_cfg.get("smoothing_window_seconds", 10))
        self.confirmed_status = "unknown"
        self.candidate_status = None
        self.candidate_since = None
        self.abnormal_since = None
        self.alert_sent = False
        self.monitoring_active = True

    def _status(self, count):
        if count < self.minimum:
            return "missing"
        if count > self.maximum:
            return "extra"
        return "ok"

    def no_data(self):
        """Rompe la continuidad y deja la regla en estado desconocido."""
        transition = None
        if self.confirmed_status in {"missing", "extra"}:
            transition = {"type": "closed", "reason": "no_data"}
        self.smoother.reset()
        self.confirmed_status = "unknown"
        self.candidate_status = None
        self.candidate_since = None
        self.abnormal_since = None
        self.alert_sent = False
        return StaffingObservation("no_data", None, None, "unknown", "no_data", transition)

    def evaluate(self, raw_count, at=None, monitoring=True):
        """Suaviza el conteo y confirma cambios solo tras suficiente estabilidad."""
        now = time.monotonic() if at is None else float(at)
        monitoring = bool(monitoring)
        transition = None
        if monitoring != self.monitoring_active:
            if not monitoring and self.confirmed_status in {"missing", "extra"}:
                transition = {"type": "closed", "reason": "outside_schedule"}
            self.smoother.reset()
            self.confirmed_status = "unknown"
            self.candidate_status = None
            self.candidate_since = None
            self.abnormal_since = None
            self.alert_sent = False
            self.monitoring_active = monitoring
        smoothed = self.smoother.add(raw_count, now)
        target = self._status(smoothed)

        if not self.enabled:
            return StaffingObservation("valid", raw_count, smoothed, target, "disabled")
        if not monitoring:
            return StaffingObservation(
                "valid", raw_count, smoothed, "not_scheduled",
                "outside_schedule", transition,
            )

        if self.confirmed_status == "unknown" and target == "ok":
            self.confirmed_status = "ok"

        if target == self.confirmed_status:
            self.candidate_status = None
            self.candidate_since = None
        else:
            if self.candidate_status != target:
                self.candidate_status = target
                self.candidate_since = now
            required = (
                self.recovery_seconds
                if target == "ok" and self.confirmed_status in {"missing", "extra"}
                else self.confirm_seconds
            )
            if now - self.candidate_since >= required:
                previous = self.confirmed_status
                self.confirmed_status = target
                self.candidate_status = None
                self.candidate_since = None
                if target in {"missing", "extra"}:
                    self.abnormal_since = now
                    self.alert_sent = False
                    transition = {"type": "opened", "kind": target, "previous": previous}
                else:
                    self.abnormal_since = None
                    self.alert_sent = False
                    transition = {"type": "closed", "reason": "recovered", "previous": previous}

        alert = None
        remaining = None
        if self.confirmed_status in {"missing", "extra"}:
            elapsed = now - self.abnormal_since
            remaining = max(0.0, self.alert_after - elapsed)
            if elapsed >= self.alert_after and not self.alert_sent:
                self.alert_sent = True
                alert = {
                    "type": "staffing_alert",
                    "camera_id": self.camera["id"],
                    "camera_name": self.camera["name"],
                    "zone": self.camera.get("zone", ""),
                    "reason": "faltantes" if self.confirmed_status == "missing" else "sobrantes",
                    "people": smoothed,
                    "raw_people": raw_count,
                    "expected_min": self.minimum,
                    "expected_max": self.maximum,
                    "outside_range_seconds": round(elapsed, 1),
                }

        if alert:
            rule_state = "alert"
        elif self.candidate_status == "ok":
            rule_state = "recovering"
        elif self.candidate_status in {"missing", "extra"}:
            rule_state = "confirming"
        elif self.confirmed_status in {"missing", "extra"}:
            rule_state = "countdown"
        else:
            rule_state = self.confirmed_status

        return StaffingObservation(
            "valid", raw_count, smoothed, self.confirmed_status, rule_state,
            transition, alert, remaining,
        )
