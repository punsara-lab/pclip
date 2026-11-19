FROM python:3.12-slim

# ffmpeg is required for merging video/audio and MP3 conversion
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

ENV HOST=0.0.0.0
ENV PORT=8080
ENV PCLIP_AUTO_OPEN=0
EXPOSE 8080

# Single worker: download jobs are tracked in memory, so status polling
# must hit the same process. Threads give concurrency for requests.
CMD gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 600 app:app
