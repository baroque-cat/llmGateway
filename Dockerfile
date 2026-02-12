FROM astral/uv:python3.13-trixie-slim AS builder

ENV UV_COMPILE_BYTECODE=1

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev --no-install-project

ENV PATH="/app/.venv/bin:$PATH"

# 5. Копируем исходники
COPY src/ ./src/
COPY main.py .

RUN uv sync --frozen --no-dev

RUN useradd -m -u 1000 appuser && \
  chown -R appuser:appuser /app

USER appuser

CMD ["python", "main.py", "--help"]
