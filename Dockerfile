FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytest
COPY src/echo_ai/workspace/sandbox_tools.py /opt/echo_sandbox.py
WORKDIR /workspace
CMD ["sleep", "infinity"]
