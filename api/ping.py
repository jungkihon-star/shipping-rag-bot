from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.routing import APIRoute

# Vercel이 라우팅 정보를 어떻게 전달하든 응답하도록 /와 /ping을 모두 처리
app = FastAPI()

# 1. 가장 기본적인 루트('/') 라우트 유지
@app.get("/")
def ping_root():
    return PlainTextResponse("ok")

# 2. 와일드카드를 사용하여 /ping/a/b/c 와 같은 경로까지 모두 처리
@app.get("/{path:path}")
def ping_wildcard(path: str):
    # 경로가 무엇이든 'ok'를 반환하도록 강제
    return PlainTextResponse("ok")
