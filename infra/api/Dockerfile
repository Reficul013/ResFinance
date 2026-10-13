FROM python:3.13.2-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements-api.txt /app/requirements-api.txt
RUN pip install --no-cache-dir --requirement /app/requirements-api.txt

COPY server /app/server
CMD ["uvicorn", "server.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
