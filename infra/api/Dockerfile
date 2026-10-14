FROM resfinance/resilientdb:4de5cb4-m1 AS resilientdb

FROM python:3.13.2-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements-api.txt /app/requirements-api.txt
COPY requirements-portfolio.txt /app/requirements-portfolio.txt
RUN pip install --no-cache-dir \
  --requirement /app/requirements-api.txt \
  --requirement /app/requirements-portfolio.txt

COPY --from=resilientdb \
  /app/bazel-bin/service/tools/kv/api_tools/kv_service_tools \
  /usr/local/bin/kv_service_tools
COPY --from=resilientdb \
  /app/bazel-bin/service/tools/contract/api_tools/contract_tools \
  /usr/local/bin/contract_tools
COPY infra/resilientdb/client.config /config/client.config
COPY infra/rescontract/client.config /config/rescontract-client.config
COPY blockchain /app/blockchain
COPY ml /app/ml
COPY server /app/server
ENV RESFINANCE_RESDB_TOOL=/usr/local/bin/kv_service_tools \
    RESFINANCE_RESDB_CONFIG=/config/client.config \
    RESFINANCE_EVENT_KEY_FILE=/certs/finance-event.key \
    RESFINANCE_RESCONTRACT_TOOL=/usr/local/bin/contract_tools \
    RESFINANCE_RESCONTRACT_CONFIG=/config/rescontract-client.config \
    RESFINANCE_RESCONTRACT_REGISTRY=/deployment/registry.json \
    RESFINANCE_SECURE_COOKIE=false
CMD ["uvicorn", "server.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
