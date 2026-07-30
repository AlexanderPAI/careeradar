FROM python:3.13-slim AS base

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY poetry.lock pyproject.toml ./

RUN pip install poetry==2.4.1
RUN poetry config virtualenvs.create false && poetry install --no-root
RUN python -m playwright install --with-deps chromium

FROM base AS proj

COPY /backend ./backend
COPY /shared ./shared

CMD ["sh", "backend/entrypoint.sh"]
