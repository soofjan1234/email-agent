FROM python:3.12.13-slim-bookworm
WORKDIR /app
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml alembic.ini ./
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY evals/ ./evals/
COPY tests/ ./tests/
RUN pip install --no-cache-dir --no-deps .
CMD ["uvicorn", "main:app", "--app-dir", "src", "--loop", "asyncio:SelectorEventLoop", "--host", "0.0.0.0", "--port", "8000"]
