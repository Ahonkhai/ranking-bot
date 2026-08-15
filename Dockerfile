FROM python:3.13-slim

# Unbuffered stdout. Without this Python block-buffers when stdout is a pipe
# rather than a TTY, so log lines sit in a 4KB buffer and are lost when the
# container is killed — exactly the diagnostics you need for a crash.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# The slim image ships no fonts, and the cards need real TrueType faces or PIL
# silently falls back to a tiny bitmap font.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Scores live outside the image so redeploys don't wipe the board.
#
# Deliberately no `VOLUME ["/data"]`: Railway's Metal builder rejects the
# instruction outright ("VOLUME is not supported, use Railway Volumes") and
# fails the build, so the platform kept serving the last image that did build.
# Nothing is lost by dropping it — VOLUME only declares an anonymous volume,
# and an explicit mount works with or without it:
#   Railway: attach a Volume with mount path /data
#   Docker:  docker run -v ranking_data:/data ...
ENV DB_PATH=/data/rankbot.db \
    DATA_FILE=/data/data.json

RUN useradd --create-home --uid 10001 rankbot \
    && mkdir -p /data \
    && chown -R rankbot:rankbot /app /data

# No `USER` here on purpose. The container starts as root so the entrypoint can
# take ownership of a runtime-mounted volume, then drops to `rankbot` itself.
# Setting USER at build time instead locks the process out of any volume that
# already existed — see docker-entrypoint.sh.
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import sqlite3,os; sqlite3.connect(os.environ.get('DB_PATH','/data/rankbot.db')).execute('select 1')" || exit 1

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "bot.py"]
