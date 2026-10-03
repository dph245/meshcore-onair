FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ONAIR_DB_PATH=/data/onair.sqlite3

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 onair \
    && useradd --uid 10001 --gid onair --no-create-home onair \
    && mkdir /data \
    && chown onair:onair /data

COPY onair_*.py ./
COPY static/ ./static/

USER onair:onair
EXPOSE 8083
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8083/', timeout=3).close()"

CMD ["python", "-m", "uvicorn", "onair_web:app", "--host", "0.0.0.0", "--port", "8083", "--workers", "1"]
