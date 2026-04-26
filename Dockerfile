FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_COMPILE=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        binutils \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY scripts /build/scripts

RUN python -m venv /venv \
    && /venv/bin/pip install --upgrade pip \
    && /venv/bin/pip install --no-compile "/build/scripts[snowflake,databricks,llm]"

RUN find /venv -depth -type d -name "__pycache__" -exec rm -rf {} + \
    && find /venv -type f -name "*.pyc" -delete \
    && find /venv -type d -name "tests" -prune -exec rm -rf {} + \
    && find /venv -type d -name "test" -prune -exec rm -rf {} + \
    && find /venv -type d -name "examples" -prune -exec rm -rf {} + \
    && find /venv -type f \( -name "*.so" -o -name "*.so.*" \) -exec strip --strip-unneeded {} + 2>/dev/null || true \
    && rm -rf /venv/share/man /venv/share/doc


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/venv/bin:${PATH}" \
    EINBLICK_SAMPLE_DATA_DIR=/opt/einblick/sample_data \
    EINBLICK_PROMPTS_DIR=/opt/einblick/skills/einblick-analysis/references

RUN groupadd --system einblick \
    && useradd --system --gid einblick --create-home --home-dir /home/einblick einblick

COPY --from=builder /venv /venv
COPY sample_data /opt/einblick/sample_data
COPY skills /opt/einblick/skills

WORKDIR /workspace
RUN chown -R einblick:einblick /workspace /home/einblick

USER einblick

ENTRYPOINT ["einblick"]
CMD ["--help"]
