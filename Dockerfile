FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY prompts /app/prompts

RUN pip install --upgrade pip \
    && pip install ".[providers]"

RUN mkdir -p /app/data/uploads /app/data/evidence /app/data/exports /app/data/backups

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "ai_examiner.main:app", "--host", "0.0.0.0", "--port", "8000"]
