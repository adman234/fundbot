FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.source="https://github.com/adman234/fundbot"
LABEL org.opencontainers.image.description="Discord fundraising tracker with a public status sheet"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py webserver.py ./
COPY web ./web

ENV DB_PATH=/data/fundraiser.db \
    STATIC_DIR=/app/web \
    WEB_PORT=8099 \
    PYTHONUNBUFFERED=1

VOLUME /data
EXPOSE 8099

HEALTHCHECK --interval=60s --timeout=5s --start-period=15s \
  CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:'+os.environ['WEB_PORT']+'/healthz').read()" || exit 1

CMD ["python", "-u", "bot.py"]
