FROM python:3.10-slim

# FFmpeg ইনস্টল
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# রিকোয়ারমেন্টস এবং yt-dlp এর লেটেস্ট ভার্সন ইনস্টল
RUN pip install --no-cache-dir -r requirements.txt && pip install --upgrade yt-dlp

COPY . .
CMD gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 120
