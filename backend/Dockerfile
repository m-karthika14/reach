FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
# Cloud Run requires binding 0.0.0.0:$PORT (not 127.0.0.1).
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT}
