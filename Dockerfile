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
#   docker run -v ranking_data:/data ...
ENV DB_PATH=/data/rankbot.db \
    DATA_FILE=/data/data.json
VOLUME ["/data"]

RUN useradd --create-home --uid 10001 rankbot \
    && mkdir -p /data \
    && chown -R rankbot:rankbot /app /data
USER rankbot

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import sqlite3,os; sqlite3.connect(os.environ['DB_PATH']).execute('select 1')" || exit 1

CMD ["python", "bot.py"]
