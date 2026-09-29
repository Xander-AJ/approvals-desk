FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never UV_PYTHON=/usr/local/bin/python UV_LINK_MODE=copy
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ .
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONPATH=/app
RUN useradd -m app && chown -R app /app
USER app
CMD ["sh", "scripts/serve.sh"]
