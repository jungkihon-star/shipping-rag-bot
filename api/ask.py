# api/ask.py
import os
import traceback
from typing import List, Dict, Any

from fastapi import FastAPI, Body, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from openai import OpenAI
from pinecone import Pinecone, PineconeException

app = FastAPI()

# ---------- Health ----------
@app.get("/")
def ping() -> PlainTextResponse:
    return PlainTextResponse("ok")

# ---------- Env keys ----------
REQ_ENV = ["OPENAI_API_KEY", "PINECONE_API_KEY", "PINECONE_INDEX_NAME", "PINECONE_HOST"]

# 지연 초기화 캐시
_client: OpenAI | None = None
_index = None  # Pinecone Index 핸들

def get_services() -> tuple[OpenAI, Any]:
    """요청 시점에만 외부 클라이언트 생성."""
    missing = [k for k in REQ_ENV if not os.getenv(k)]
    if missing:
        # 헬스체크는 통과시키되 기능 경로만 503
        raise HTTPException(status_code=503, detail=f"Missing env: {missing}")

    global _client, _index
    if _client is None:
        _client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    if _index is None:
        pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
        name = os.environ["PINECONE_INDEX_NAME"]
        host = os.environ["PINECONE_HOST"]  # Pinecone 콘솔의 Index host 전체 URL
        try:
            _index = pc.Index(name, host=host)
        except PineconeException as e:
            # 인증/호스트 오류 시 부팅은 유지, 요청만 실패
            raise HTTPException(status_code=503, detail=f"Pinecone error: {type(e).__name__}")
    return _client, _index

# ---------- Schemas ----------
class Q(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(8, ge=1, le=50)
    max_tokens: int = Field(600, ge=64, le=2000)

# ---------- Helpers ----------
def embed_one(client: OpenAI, text: str) -> List[float]:
    r = client.embeddings.create(model="text-embedding-3-large", input=text)
    return r.data[0].embedding

def build_prompt(question: str, matches: List[Dict[str, Any]]) -> str:
    ctx_blocks: List[str] = []
    for i, m in enumerate(matches, start=1):
        md = m.get("metadata", {}) or {}
        src = md.get("source") or md.get("file") or md.get("id") or ""
        txt = md.get("text") or ""
        ctx_blocks.append(f"[{i}] {src}\n{txt}")
    header = (
        "당신은 해운 시황 분석 보조원이다. 제공된 컨텍스트 범위에서만 한국어로 답하라. "
        "단정할 수 없으면 '자료 없음'이라 답하라. 각 주장 뒤에 [번호]로 출처를 표기하라.\n\n"
    )
    return header + f"질문:\n{question}\n\n컨텍스트:\n" + "\n\n---\n\n".join(ctx_blocks)

# ---------- Q&A endpoint ----------
@app.post("/api/ask")
def ask(body: Q = Body(...)) -> JSONResponse:
    try:
        client, index = get_services()

        # 1) Embed
        qv = embed_one(client, body.query)

        # 2) Vector search
        res = index.query(vector=qv, top_k=body.top_k, include_metadata=True)
        # pinecone SDK 버전에 따라 dict/object 모두 허용
        if hasattr(res, "matches"):
            matches = res.matches or []
        else:
            matches = res.get("matches", []) if isinstance(res, dict) else []

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

    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc(limit=3)
        return JSONResponse(status_code=500, content={"error": str(e), "trace": tb})
