from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
app = FastAPI()
@app.get("/") # Vercel이 /api/ping/ 으로 라우팅할 것임
def ping():
    return PlainTextResponse("ok")
