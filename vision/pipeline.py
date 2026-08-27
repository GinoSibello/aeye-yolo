"""Configuracion validada de copias y conversiones del pipeline de vision."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineSettings:
    """Selecciona rutas equivalentes que pueden compararse en benchmarks A/B."""

    copy_latest_frame: bool = True
    result_transfer: str = "split"


def frame_snapshot(frame, copy_frame):
    """Copia un frame o crea una vista compartida que no admite escritura."""
    if frame is None or copy_frame:
        return None if frame is None else frame.copy()
    snapshot = frame.view()
    snapshot.setflags(write=False)
    return snapshot


def parse_pipeline_settings(system_cfg):
    """Normaliza optimizaciones conservando el comportamiento historico."""
    values = dict(system_cfg.get("pipeline", {}) or {})
    result_transfer = str(values.get("result_transfer", "split")).lower()
    if result_transfer not in {"split", "packed"}:
        raise ValueError("pipeline.result_transfer debe ser split o packed")
    return PipelineSettings(
        copy_latest_frame=bool(values.get("copy_latest_frame", True)),
        result_transfer=result_transfer,
    )
