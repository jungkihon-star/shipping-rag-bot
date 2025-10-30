from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

app = FastAPI()

@app.api_route("/", methods=["GET", "HEAD"])
def ping():
    return PlainTextResponse("ok")
