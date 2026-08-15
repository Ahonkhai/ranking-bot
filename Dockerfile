FROM python:3.11-slim

# Set working directory
WORKDIR /app

# System fonts — the slim image ships none, and the rank cards need real
# TrueType fonts for the gold typography to render (otherwise PIL falls back
# to a tiny bitmap font).
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies (do this first for docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your app's source code
COPY . .

# Persist scores outside the image so redeploys don't wipe the leaderboard.
# Mount a volume here, e.g.:  docker run -v ranking_data:/data ...
ENV DATA_FILE=/data/data.json
VOLUME ["/data"]

# Run your bot script
CMD ["python", "bot.py"]