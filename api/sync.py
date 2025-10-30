import os, io, re, uuid, json, time, traceback
from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
from pypdf import PdfReader
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.service_account import Credentials
from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec

app = FastAPI()

@app.get("/api/ping")
@app.get("/")
def ping():
    return PlainTextResponse("ok")

# ENV 점검(비밀값은 노출하지 않음)
@app.get("/api/env")
def env_check():
    keys = ["OPENAI_API_KEY","PINECONE_API_KEY","DRIVE_FOLDER_ID","INDEX_NAME","GOOGLE_SERVICE_ACCOUNT_JSON"]
    return {k: bool(os.getenv(k)) for k in keys}

try:
    OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
    PINECONE_API_KEY = os.environ["PINECONE_API_KEY"]
    FOLDER_ID = os.environ["DRIVE_FOLDER_ID"]
    INDEX_NAME = os.getenv("INDEX_NAME","shipping-rag")
    SA_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
except KeyError as e:
    raise RuntimeError(f"Missing env: {e}")

client = OpenAI(api_key=OPENAI_API_KEY)
pc = Pinecone(api_key=PINECONE_API_KEY)
if INDEX_NAME not in [i.name for i in pc.list_indexes()]:
    pc.create_index(INDEX_NAME, dimension=3072, metric="cosine",
                    spec=ServerlessSpec(cloud="aws", region="us-east-1"))
    time.sleep(8)
index = pc.Index(INDEX_NAME)

def _creds():
    info = json.loads(SA_JSON)
    return Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )

def list_files(folder_id, drive):
    q = f"'{folder_id}' in parents and (mimeType='application/pdf' or mimeType='text/plain') and trashed=false"
    token = None
    while True:
        resp = drive.files().list(q=q, fields="nextPageToken, files(id,name,mimeType,modifiedTime)",
                                  pageToken=token).execute()
        for f in resp.get("files", []):
            yield f
        token = resp.get("nextPageToken")
        if not token: break

def download_text(file_id, mime, drive):
    buf = io.BytesIO()
    req = drive.files().get_media(fileId=file_id)
    downloader = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    if mime == "text/plain":
        return buf.read().decode("utf-8", errors="ignore")
    if mime == "application/pdf":
        try:
            reader = PdfReader(buf)
            return "\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception:
            return ""
    return ""

def chunk_text(t, size=1200, overlap=200):
    t = re.sub(r"\s+\n", "\n", t)
    out, i, n = [], 0, len(t)
    while i < n:
        j = min(n, i+size)
        c = t[i:j].strip()
        if c: out.append(c)
        i = max(0, j-overlap)
    return out

def embed(texts):
    r = client.embeddings.create(model="text-embedding-3-large", input=texts)
    return [d.embedding for d in r.data]

@app.get("/api/sync")
@app.get("/")
def sync():
    try:
        drive = build("drive", "v3", credentials=_creds())
        files = list(list_files(FOLDER_ID, drive))
        if not files:
            return {"status":"no_files"}
        total_chunks = 0
        for f in files:
            text = download_text(f["id"], f["mimeType"], drive)
            if not text.strip(): 
                continue
            chunks = chunk_text(text)
            for k in range(0, len(chunks), 64):
                part = chunks[k:k+64]
                vecs = embed(part)
                index.upsert([{
                    "id": str(uuid.uuid4()),
                    "values": v,
                    "metadata": {
                        "text": t,
                        "source": f"drive://{f['name']}#{k+i}",
                        "file_id": f["id"],
                        "mtime": f["modifiedTime"]
                    }
                } for i,(v,t) in enumerate(zip(vecs, part))])
                total_chunks += len(part)
        return {"status":"ok","files":len(files),"chunks":total_chunks}
    except Exception as e:
        tb = traceback.format_exc(limit=3)
        return JSONResponse(status_code=500, content={"error": str(e), "trace": tb})
