FROM python:3.13-slim AS base

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential tree curl git ca-certificates && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY poetry.lock pyproject.toml ./

RUN pip install poetry==2.4.1
RUN poetry config virtualenvs.create false && poetry install --no-root
RUN python -m playwright install --with-deps chromium

FROM base AS proj

COPY /backend ./backend

# GigaChat uses the Russian Trusted CA chain. Install the pinned certificates
# into Debian's trust store so TLS verification remains enabled.
COPY /backend/certs/russian_trusted_root_ca.pem \
    /usr/local/share/ca-certificates/russian_trusted_root_ca.crt
COPY /backend/certs/russian_trusted_sub_ca.pem \
    /usr/local/share/ca-certificates/russian_trusted_sub_ca.crt
RUN update-ca-certificates

CMD ["sh", "backend/entrypoint.sh"]
