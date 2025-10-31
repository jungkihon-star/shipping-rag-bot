
import os
import traceback
from typing import List, Dict, Any

from fastapi import FastAPI, Body
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from openai import OpenAI
from pinecone import Pinecone

# ---------- FastAPI app ----------
app = FastAPI()

# ---------- Health check ----------
@app.get("/")
def ping() -> PlainTextResponse:
    # Vercel 경로: GET https://<domain>/api/apk
    return PlainTextResponse("ok")

# ---------- ENV & clients ----------
REQUIRED = ["OPENAI_API_KEY", "PINECONE_API_KEY"]
missing = [k for k in REQUIRED if not os.getenv(k)]
if missing:
    raise RuntimeError(f"Missing env: {missing}")

INDEX_NAME = os.getenv("PINECONE_INDEX") or os.getenv("INDEX_NAME") or "shipping-rag"

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
index = pc.Index(INDEX_NAME)

# ---------- Schemas ----------
class Q(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(8, ge=1, le=50)
    max_tokens: int = Field(600, ge=64, le=2000)

# ---------- Helpers ----------
def embed_one(text: str) -> List[float]:
    r = client.embeddings.create(model="text-embedding-3-large", input=[text])
    return r.data[0].embedding

def build_prompt(question: str, matches: List[Dict[str, Any]]) -> str:
    ctx_blocks: List[str] = []
    for i, m in enumerate(matches, start=1):
        md = m.get("metadata", {}) or {}
        src = md.get("source", "") or md.get("file", "") or md.get("id", "")
        txt = md.get("text", "") or ""
        ctx_blocks.append(f"[{i}] {src}\n{txt}")
    header = (
        "당신은 해운 시황 분석 보조원이다. 제공된 컨텍스트 범위에서만 한국어로 답하라. "
        "단정할 수 없으면 '자료 없음'이라 답하라. 각 주장 뒤에 [번호]로 출처를 표기하라.\n\n"
    )
    return header + f"질문:\n{question}\n\n컨텍스트:\n" + "\n\n---\n\n".join(ctx_blocks)

# ---------- Q&A endpoint ----------
@app.post("/")
def ask(body: Q = Body(...)) -> JSONResponse:
    """
    Vercel 경로: POST https://<domain>/api/apk
    """
    try:
        # 1) Embed
        qv = embed_one(body.query)

        # 2) Vector search
        # Pinecone v5: dict 응답에 'matches' 리스트 포함
        res = index.query(vector=qv, top_k=body.top_k, include_metadata=True)
        matches: List[Dict[str, Any]] = res.get("matches", []) if isinstance(res, dict) else []

        if not matches:
            return JSONResponse({"answer": "관련 자료 없음", "sources": []})

        # 3) Prompt
        prompt = build_prompt(body.query, matches)

        # 4) LLM call
        chat = client.chat.completions.create(
            model="gpt-5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=body.max_tokens,
        )
        answer = chat.choices[0].message.content

        # 5) Sources payload
        sources = []
        for m in matches:
            md = m.get("metadata", {}) or {}
            sources.append({
                "score": m.get("score", 0.0),
                "id": m.get("id"),
                "source": md.get("source") or md.get("file") or md.get("id"),
                "page": md.get("page"),
                "text": md.get("text"),
            })

        return JSONResponse({"answer": answer, "sources": sources})

    except Exception as e:
        tb = traceback.format_exc(limit=3)
        return JSONResponse(status_code=500, content={"error": str(e), "trace": tb})
