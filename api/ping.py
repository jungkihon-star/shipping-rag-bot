# api/ping.py 파일 내용
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
app = FastAPI()
@app.get("/") # Vercel의 Rewrites를 통해 이 경로로 요청이 전달될 것임
def ping():
    return PlainTextResponse("ok")
