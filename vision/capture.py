"""Backends configurables para capturar el frame RTSP mas reciente."""

import re
from dataclasses import dataclass

import cv2
import numpy as np


class CaptureError(RuntimeError):
    """Indica que un backend no pudo abrir o leer el stream."""


class CaptureBackendUnavailable(CaptureError):
    """Indica que faltan dependencias o plugins del backend solicitado."""


@dataclass(frozen=True)
class CaptureSettings:
    """Configuracion validada del lector RTSP."""

    backend: str = "ffmpeg"
    fallback_to_ffmpeg: bool = True
    codec: str = "h265"
    rtsp_latency_ms: int = 200
    read_timeout_ms: int = 15000


def parse_capture_settings(config):
    """Valida opciones sin aceptar backends de inferencia o codecs implicitos."""
    values = dict(config or {})
    backend = str(values.get("backend", "ffmpeg")).lower()
    aliases = {"nvdec": "gstreamer_nvdec", "gstreamer": "gstreamer_nvdec"}
    backend = aliases.get(backend, backend)
    if backend not in {"ffmpeg", "gstreamer_nvdec"}:
        raise ValueError(f"Backend de captura no soportado: {backend}")

    codec = str(values.get("codec", "h265")).lower()
    codec = {"hevc": "h265", "avc": "h264"}.get(codec, codec)
    if codec not in {"h264", "h265"}:
        raise ValueError(f"Codec NVDEC no soportado: {codec}")

    latency = int(values.get("rtsp_latency_ms", 200))
    timeout = int(values.get("read_timeout_ms", 15000))
    if latency < 0:
        raise ValueError("rtsp_latency_ms no puede ser negativo")
    if timeout < 1000:
        raise ValueError("read_timeout_ms debe ser al menos 1000")

    return CaptureSettings(
        backend=backend,
        fallback_to_ffmpeg=bool(values.get("fallback_to_ffmpeg", True)),
        codec=codec,
        rtsp_latency_ms=latency,
        read_timeout_ms=timeout,
    )


def build_nvdec_pipeline(settings):
    """Construye un pipeline sin incluir la URL ni sus credenciales."""
    elements = {
        "h264": ("rtph264depay", "h264parse"),
        "h265": ("rtph265depay", "h265parse"),
    }
    depayloader, parser = elements[settings.codec]
    return (
        "rtspsrc name=source protocols=tcp "
        f"latency={settings.rtsp_latency_ms} drop-on-latency=true ! "
        f"{depayloader} ! {parser} ! "
        "nvv4l2decoder name=decoder ! "
        "nvvidconv ! video/x-raw,format=BGRx ! "
        "videoconvert ! video/x-raw,format=BGR ! "
        "appsink name=sink emit-signals=false sync=false "
        "max-buffers=1 drop=true wait-on-eos=false"
    )


def _safe_gstreamer_error(message):
    """Oculta credenciales si una biblioteca incluye una URI en su error."""
    return re.sub(r"rtsp://[^@\s]+@", "rtsp://***@", str(message))


class FFmpegCapture:
    """Adaptador del lector OpenCV/FFmpeg existente."""

    backend_name = "ffmpeg"
    hardware_decode = False

    def __init__(self, url):
        self.capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        self.fallback_reason = None

    def is_opened(self):
        """Indica si OpenCV logro abrir el stream."""
        return self.capture.isOpened()

    def read(self):
        """Entrega el siguiente frame decodificado por FFmpeg."""
        return self.capture.read()

    def stream_info(self):
        """Expone metadatos no sensibles reportados por OpenCV."""
        codec_value = int(self.capture.get(cv2.CAP_PROP_FOURCC))
        codec = "".join(
            chr((codec_value >> (8 * index)) & 0xFF) for index in range(4)
        ).strip("\x00") or None
        reported_fps = float(self.capture.get(cv2.CAP_PROP_FPS)) or None
        return {
            "width": int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH)) or None,
            "height": int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) or None,
            "reported_fps": round(reported_fps, 3) if reported_fps else None,
            "codec": codec,
            "capture_backend": self.backend_name,
            "hardware_decode": self.hardware_decode,
            "fallback_reason": self.fallback_reason,
        }

    def release(self):
        """Libera la captura OpenCV."""
        self.capture.release()


_GSTREAMER_MODULES = None


def _load_gstreamer():
    """Carga GStreamer de forma perezosa para conservar el fallback FFmpeg."""
    global _GSTREAMER_MODULES
    if _GSTREAMER_MODULES is not None:
        return _GSTREAMER_MODULES

    try:
        import gi

        gi.require_version("Gst", "1.0")
        gi.require_version("GstVideo", "1.0")
        from gi.repository import Gst, GstVideo
    except (ImportError, ValueError) as error:
        raise CaptureBackendUnavailable(
            "No estan disponibles los bindings Python de GStreamer"
        ) from error

    Gst.init(None)
    required = (
        "rtspsrc",
        "rtph264depay",
        "rtph265depay",
        "h264parse",
        "h265parse",
        "nvv4l2decoder",
        "nvvidconv",
        "videoconvert",
        "appsink",
    )
    missing = [name for name in required if Gst.ElementFactory.find(name) is None]
    if missing:
        raise CaptureBackendUnavailable(
            "Faltan plugins GStreamer requeridos: " + ", ".join(missing)
        )
    _GSTREAMER_MODULES = Gst, GstVideo
    return _GSTREAMER_MODULES


class GStreamerNvdecCapture:
    """Lee RTSP con nvv4l2decoder y entrega frames BGR mediante appsink."""

    backend_name = "gstreamer_nvdec"
    hardware_decode = True

    def __init__(self, url, settings):
        self.settings = settings
        self.fallback_reason = None
        self.width = None
        self.height = None
        self.reported_fps = None
        self.Gst, self.GstVideo = _load_gstreamer()
        try:
            self.pipeline = self.Gst.parse_launch(build_nvdec_pipeline(settings))
            source = self.pipeline.get_by_name("source")
            self.sink = self.pipeline.get_by_name("sink")
            if source is None or self.sink is None:
                raise CaptureBackendUnavailable(
                    "No se pudieron crear rtspsrc y appsink"
                )
            source.set_property("location", url)
            result = self.pipeline.set_state(self.Gst.State.PLAYING)
            if result == self.Gst.StateChangeReturn.FAILURE:
                raise CaptureError("GStreamer no pudo iniciar el pipeline NVDEC")
        except Exception as error:
            pipeline = getattr(self, "pipeline", None)
            if pipeline is not None:
                pipeline.set_state(self.Gst.State.NULL)
            raise CaptureError(
                _safe_gstreamer_error(error)
            ) from error

    def is_opened(self):
        """Indica si el pipeline fue creado y no entro en estado de fallo."""
        return self.pipeline is not None

    def _pipeline_error(self):
        message = self.pipeline.get_bus().timed_pop_filtered(
            0,
            self.Gst.MessageType.ERROR | self.Gst.MessageType.EOS,
        )
        if message is None:
            return None
        if message.type == self.Gst.MessageType.ERROR:
            error, _ = message.parse_error()
            return _safe_gstreamer_error(error.message)
        return "GStreamer recibio fin de stream"

    def read(self):
        """Extrae un frame BGR copiandolo antes de liberar el buffer Gst."""
        timeout_ns = self.settings.read_timeout_ms * self.Gst.MSECOND
        sample = self.sink.emit("try-pull-sample", timeout_ns)
        if sample is None:
            detail = self._pipeline_error() or "timeout esperando un frame"
            raise CaptureError(f"GStreamer NVDEC: {detail}")

        caps = sample.get_caps()
        structure = caps.get_structure(0)
        self.width = int(structure.get_value("width"))
        self.height = int(structure.get_value("height"))
        success, numerator, denominator = structure.get_fraction("framerate")
        if success and denominator:
            self.reported_fps = round(numerator / denominator, 3)

        video_info = self.GstVideo.VideoInfo.new_from_caps(caps)
        stride = int(video_info.stride[0])
        buffer = sample.get_buffer()
        mapped, map_info = buffer.map(self.Gst.MapFlags.READ)
        if not mapped:
            raise CaptureError("GStreamer no pudo mapear el frame BGR")
        try:
            frame = np.ndarray(
                shape=(self.height, self.width, 3),
                dtype=np.uint8,
                buffer=map_info.data,
                strides=(stride, 3, 1),
            ).copy()
        finally:
            buffer.unmap(map_info)
        return True, frame

    def stream_info(self):
        """Expone metadatos del caps y confirma el backend de captura real."""
        return {
            "width": self.width,
            "height": self.height,
            "reported_fps": self.reported_fps,
            "codec": self.settings.codec,
            "capture_backend": self.backend_name,
            "hardware_decode": self.hardware_decode,
            "fallback_reason": self.fallback_reason,
        }

    def release(self):
        """Detiene el pipeline y libera superficies del decoder."""
        if self.pipeline is not None:
            self.pipeline.set_state(self.Gst.State.NULL)
            self.pipeline = None


def open_capture(url, config, force_ffmpeg=False):
    """Abre el backend solicitado y aplica fallback solo cuando esta habilitado."""
    settings = parse_capture_settings(config)
    if settings.backend == "ffmpeg":
        return FFmpegCapture(url)
    if force_ffmpeg:
        capture = FFmpegCapture(url)
        capture.fallback_reason = (
            "Fallback activado tras un fallo previo de GStreamer NVDEC"
        )
        return capture

    try:
        return GStreamerNvdecCapture(url, settings)
    except Exception as error:
        if not settings.fallback_to_ffmpeg:
            raise
        capture = FFmpegCapture(url)
        capture.fallback_reason = _safe_gstreamer_error(error)
        return capture
