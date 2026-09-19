FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Install Echo's locked runtime and test dependencies at build time. The sandbox
# has no network access when tools run, and /workspace is mounted at runtime.
RUN pip install --no-cache-dir uv==0.12.16
WORKDIR /opt/echo-deps
COPY pyproject.toml uv.lock ./
RUN uv export --locked --all-groups --no-emit-project \
        --output-file /tmp/echo-requirements.txt \
    && uv pip install --system --requirement /tmp/echo-requirements.txt \
    && rm /tmp/echo-requirements.txt

COPY src/echo_ai/workspace/sandbox_tools.py /opt/echo_sandbox.py
ENV PYTHONPATH=/workspace/src
WORKDIR /workspace
CMD ["sleep", "infinity"]
