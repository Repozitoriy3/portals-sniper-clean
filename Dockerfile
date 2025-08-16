# фиксируем окружение: Python 3.11, никаких buildpacks
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

ENV PORT=10000
EXPOSE 10000

# было (не подставляет переменные):
# CMD ["gunicorn", "-w", "1", "-k", "gthread", "-t", "120", "-b", "0.0.0.0:${PORT}", "server:app"]

# стало:
CMD sh -c "gunicorn ... -b 0.0.0.0:$PORT server:app

