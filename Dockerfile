FROM nvcr.io/nvidia/pytorch:26.07-py3

WORKDIR /workspace/aeye-yolo

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
