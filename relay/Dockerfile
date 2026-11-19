# Relay en la nube de cassette-fm. Sin claves adentro: INGEST_TOKEN y APP_PASSWORD llegan por el entorno.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --system --no-create-home --uid 10001 relay

COPY cassette_relay ./cassette_relay
COPY web ./web

USER relay
EXPOSE 8080
CMD ["python", "-m", "cassette_relay"]
