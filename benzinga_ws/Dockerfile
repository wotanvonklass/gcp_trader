# Lightweight Python image for Benzinga WebSocket client (~50 MB)
FROM python:3.11-slim-bookworm

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
