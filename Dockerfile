FROM python:3.11-slim
WORKDIR /app

# 의존성
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스
COPY . .

# api 모듈 경로 인식
ENV PYTHONPATH="/app:/app/shipping-rag-bot"

# FastAPI 엔트리
CMD ["/usr/local/bin/python", "-m", "uvicorn", "api.ask:app", "--host", "0.0.0.0", "--port", "8080"]
