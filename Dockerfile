FROM python:3.10-slim

# FFmpeg এবং Node.js ইনস্টল করা (প্লাগইনের জন্য প্রয়োজন)
RUN apt-get update && apt-get install -y ffmpeg curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# yt-dlp এবং bgutil-ytdlp-pot-provider প্লাগইন ইনস্টল করা
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -U yt-dlp bgutil-ytdlp-pot-provider

COPY . .
CMD gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 120
