FROM python:3.12.3-slim-bookworm

# --- System tools ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        tesseract-ocr \
        libgl1 \
        libglib2.0-0 \
        git \
        curl \
        jq \
        ca-certificates \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# --- Python media stack + API clients + utilities ---
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# --- Pre-cache Whisper "base" model (for ASR / verifier audio checks) ---
RUN python3 -c "import whisper; whisper.load_model('base', device='cpu')"

# --- OpenClaw CLI ---
# The installer provisions Node.js and the openclaw binary under /opt/openclaw.
# --no-onboard skips the interactive setup wizard (configured at runtime).
RUN curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard
ENV PATH="/opt/openclaw/bin:${PATH}"

# --- Workspace layout (cases are injected via mount, NOT baked in) ---
WORKDIR /workspace
RUN mkdir -p /workspace/task /workspace/materials /workspace/references \
             /workspace/skills /workspace/output /workspace/logs

# --- Entrypoint ---
COPY entrypoint.sh /opt/video-bench/entrypoint.sh
RUN chmod +x /opt/video-bench/entrypoint.sh

ENTRYPOINT ["/opt/video-bench/entrypoint.sh"]
