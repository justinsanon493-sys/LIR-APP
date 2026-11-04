FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    DONNEES_DIR=/data

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r requirements.txt \
    && mkdir -p /data \
    && chown 10001:10001 /data

COPY app.py wsgi.py ./
COPY modules ./modules
COPY static ./static
USER 10001:10001
EXPOSE 8000

CMD ["python", "wsgi.py"]
