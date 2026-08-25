FROM nvcr.io/nvidia/pytorch:26.07-py3

WORKDIR /workspace/aeye-yolo

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    --no-install-recommends \
    gir1.2-gst-plugins-base-1.0 \
    gir1.2-gstreamer-1.0 \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-tools \
    python3-gi \
    && rm -rf /var/lib/apt/lists/*

RUN pip uninstall -y opencv-python opencv-python-headless ultralytics || true

RUN pip install --no-cache-dir \
    ultralytics-opencv-headless \
    "lap>=0.5.12" \
    fastapi \
    "uvicorn[standard]" \
    psutil

ENV YOLO_CONFIG_DIR=/tmp/Ultralytics
ENV AEYE_CONFIG=/workspace/aeye-yolo/cameras.json
ENV AEYE_LOG_DIR=/workspace/aeye-yolo/logs
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility,video

CMD ["python3", "main.py"]
