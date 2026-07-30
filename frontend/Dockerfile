FROM python:3.13-slim AS base

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY poetry.lock pyproject.toml ./
RUN pip install poetry==2.4.1
RUN poetry config virtualenvs.create false && poetry install --no-root

ENV PYTHONPATH=/app

FROM base AS proj

COPY /frontend ./frontend
COPY /shared ./shared
CMD ["streamlit", "run", "/app/frontend/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
