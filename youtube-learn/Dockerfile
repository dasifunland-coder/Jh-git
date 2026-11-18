# 클립러닝 서버 (앱 화면 + API). ffmpeg는 음성 인식용 오디오 변환에 필요해요.
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt
COPY index.html manifest.webmanifest sw.js ./
COPY icons icons
COPY server/*.py server/
WORKDIR /app/server
ENV HOST=0.0.0.0 PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app:app --host $HOST --port $PORT"]
