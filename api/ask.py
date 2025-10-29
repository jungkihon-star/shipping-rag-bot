import os
from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI
from pinecone import Pinecone

app = FastAPI()

# 환경변수
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
PINECONE_API_KEY = os.environ["PINECONE_API_KEY"]
INDEX_NAME = os.getenv("INDEX_NAME", "shipping-rag")

# 클라이언트
client = OpenAI(api_key=OPENAI_API_KEY)
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(INDEX_NAME)

class Q(BaseModel):
    query: str
    top_k: int = 8
    max_tokens: int = 600

def embed_one(text: str):
    r = client.embeddings.create(model="text-embedding-3-large", input=[text])
    return r.data[0].embedding

# Vercel 경로가 /api/ask 이므로, 앱 내부 경로는 "/" 로 둔다.
@app.post("/")
def ask(body: Q):
    qv = embed_one(body.query)
    res = index.query(vector=qv, top_k=body.top_k, include_metadata=True)
    matches = res.get("matches", [])
    if not matches:
        return {"answer": "관련 자료 없음", "sources": []}

    # 컨텍스트 구성
    ctx_blocks = []
    for i, m in enumerate(matches, start=1):
        md = m["metadata"]
        ctx_blocks.append(f"[{i}] {md.get('source','')}\n{md.get('text','')}")
    prompt = (
        "당신은 해운 시황 분석 보조원이다. 컨텍스트에서만 답하라. "
        "단정 불가하면 '자료 없음'이라 말한다. 각 주장 뒤에 [번호]로 출처를 표기하라.\n\n"
        f"질문:\n{body.query}\n\n컨텍스트:\n" + "\n\n---\n\n".join(ctx_blocks)
    )

    chat = client.chat.completions.create(
        model="gpt-5-turbo",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=body.max_tokens
    )
    answer = chat.choices[0].message.content
    sources = [{"score": m.get("score", 0.0), **m["metadata"]} for m in matches]
    return {"answer": answer, "sources": sources}
