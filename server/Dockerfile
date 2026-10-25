FROM python:3.13.17-slim-trixie@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY bootstrap-requirements.txt requirements.txt ./
RUN python -m pip install --no-cache-dir --no-deps --require-hashes -r bootstrap-requirements.txt \
    && python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip check
COPY deploy_api ./deploy_api
COPY verify_trust.py .

USER 10001
RUN python verify_trust.py
EXPOSE 8080
CMD ["uvicorn", "deploy_api.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
