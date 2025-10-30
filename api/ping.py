from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

app = FastAPI()

# Vercel이 /api/ping으로 전달할 경우 (가장 확실한 경로)
@app.get("/ping") 
def ping_named():
    return PlainTextResponse("ok")

# Vercel이 루트로 전달할 경우 (이전 시도)
@app.get("/") 
def ping_root():
    return PlainTextResponse("ok")

# 추가: 슬래시(/)를 포함한 경로도 처리
@app.get("/ping/")
def ping_slash():
    return PlainTextResponse("ok")
