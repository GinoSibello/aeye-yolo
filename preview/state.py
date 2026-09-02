"""Construye el estado publico que consume el visor en vivo."""


PUBLIC_FIELDS = (
    "name",
    "zone",
    "role",
    "expected_people",
    "configuration_status",
    "connected",
    "data_status",
    "people",
    "raw_people",
    "rule_state",
    "last_update",
)


def build_preview_payload(state, enabled, refresh_ms=1000):
    """Copia solamente campos operativos y excluye IPs y errores internos."""
    cameras = {
        camera_id: {
            field: camera_state.get(field) for field in PUBLIC_FIELDS
        }
        for camera_id, camera_state in state.items()
    }
    return {
        "preview_enabled": bool(enabled),
        "refresh_ms": int(refresh_ms),
        "cameras": cameras,
    }

