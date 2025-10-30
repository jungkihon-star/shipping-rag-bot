# api/sync.py
# Vercel cold start 캐시 무효화를 위한 주석 (2025-10-30)

import os
import io
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# -------------------------
# 환경 변수 표준화
# -------------------------
BUCKET_NAME = os.getenv("GCS_BUCKET") or os.getenv("GCS_BUCKET_NAME")
CREDS_JSON_STR = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON") or os.getenv("GOOGLE_CREDENTIALS")
STORAGE_SCOPES = ["https://www.googleapis.com/auth/devstorage.full_control"]

if not BUCKET_NAME:
    raise RuntimeError("Missing env: GCS_BUCKET or GCS_BUCKET_NAME")
if not CREDS_JSON_STR:
    raise RuntimeError("Missing env: GOOGLE_APPLICATION_CREDENTIALS_JSON or GOOGLE_CREDENTIALS")

# -------------------------
# GCS 서비스 지연 초기화
# -------------------------
_storage_service = None  # type: Optional[Any]

def get_storage_service():
    """Service Account JSON으로 GCS JSON API 클라이언트 생성. 모듈 전역에 캐시."""
    global _storage_service
    if _storage_service is not None:
        return _storage_service
    try:
        creds_info = json.loads(CREDS_JSON_STR)
        credentials = service_account.Credentials.from_service_account_info(
            creds_info, scopes=STORAGE_SCOPES
        )
        _storage_service = build("storage", "v1", credentials=credentials, cache_discovery=False)
        return _storage_service
    except Exception as e:
        # 초기화 실패 시 이후 요청에서 500 처리
        raise RuntimeError(f"GCS service init failed: {e}") from e

# -------------------------
# FastAPI 앱
# -------------------------
app = FastAPI()

# -------------------------
# 유틸
# -------------------------
def _to_iso_utc(ts_str: str) -> str:
    """GCS updated 예: '2025-10-30T12:34:56.123Z' → ISO 8601 UTC"""
    # 마이크로초가 없을 수도 있어 split('.')[0] 같은 보정 없이 fromisoformat 사용 불가.
    # 간단 처리: 'Z' 제거 후 fromisoformat, 남은 소수점은 자동 파싱.
    s = ts_str.rstrip("Z")
    # python 3.11: fromisoformat은 'YYYY-MM-DDTHH:MM:SS[.ffffff]' 지원
    dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def _to_sgt(ts_str: str) -> str:
    """GCS updated → SGT(+08:00) ISO 8601"""
    s = ts_str.rstrip("Z")
    dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    sgt = dt.astimezone(timezone(timedelta(hours=8)))
    return sgt.isoformat()

def _public_url(bucket: str, object_name: str) -> str:
    return f"https://storage.googleapis.com/{bucket}/{object_name}"

# -------------------------
# GCS 업로드
# -------------------------
def create_and_upload_object(
    file_stream: io.BytesIO,
    filename: str,
    mime_type: Optional[str],
) -> Dict[str, Any]:
    svc = get_storage_service()
    object_name = f"user-uploads/{filename}"
    media = MediaIoBaseUpload(file_stream, mimetype=mime_type or "application/octet-stream",
                              chunksize=1024 * 1024, resumable=True)

    # 1차: publicRead 시도
    try:
        req = svc.objects().insert(
            bucket=BUCKET_NAME,
            name=object_name,
            media_body=media,
            predefinedAcl="publicRead",
        )
        resp = req.execute()
    except Exception as e1:
        # PAP(enforced) 또는 권한 정책으로 403/400 가능. publicRead 제거 후 재시도.
        try:
            req = svc.objects().insert(
                bucket=BUCKET_NAME,
                name=object_name,
                media_body=media,
            )
            resp = req.execute()
        except Exception as e2:
            raise HTTPException(status_code=500, detail=f"GCS 업로드 실패: {e2}") from e1

    return {
        "name": resp.get("name"),
        "mimeType": resp.get("contentType"),
        "size": int(resp.get("size", 0)),
        "updated": _to_iso_utc(resp.get("updated")) if resp.get("updated") else None,
        "url": _public_url(BUCKET_NAME, object_name),
    }

# -------------------------
# GCS 목록
# -------------------------
def list_objects_in_gcs() -> List[Dict[str, Any]]:
    svc = get_storage_service()
    req = svc.objects().list(bucket=BUCKET_NAME, prefix="user-uploads/")
    items: List[Dict[str, Any]] = []

    while req is not None:
        resp = req.execute()
        for it in resp.get("items", []):
            name = it.get("name", "")
            if not name or name.endswith("/"):
                continue
            updated = it.get("updated")
            items.append({
                "name": name.replace("user-uploads/", "", 1),
                "size_bytes": int(it.get("size", 0)),
                "mime_type": it.get("contentType"),
                "updated_utc": _to_iso_utc(updated) if updated else None,
                "updated_sgt": _to_sgt(updated) if updated else None,
                "public_url": _public_url(BUCKET_NAME, name),
            })
        req = svc.objects().list_next(req, resp)

    return items

# -------------------------
# 엔드포인트
# -------------------------

@app.get("/")
def home():
    """헬스체크 및 사용 안내. Vercel 경로: GET /api/sync"""
    return {
        "message": "GCS Sync API ready.",
        "endpoints": {
            "upload": "POST /api/sync/upload (multipart/form-data, field name: file)",
            "list": "GET  /api/sync/list",
        },
        "bucket": BUCKET_NAME,
    }

@app.post("/upload")
async def upload_file_to_gcs(file: UploadFile = File(...)):
    """단일 파일 업로드. 공개 URL은 버킷 정책에 따라 접근 제한 가능."""
    try:
        content = await file.read()
        info = create_and_upload_object(
            file_stream=io.BytesIO(content),
            filename=file.filename,
            mime_type=file.content_type,
        )
        return JSONResponse(status_code=200, content={
            "status": "Success",
            "message": f"Uploaded: {file.filename}",
            "file": info,
        })
    except HTTPException as he:
        return JSONResponse(status_code=he.status_code,
                            content={"status": "Error", "message": he.detail})
    except Exception as e:
        return JSONResponse(status_code=500,
                            content={"status": "Error", "message": f"서버 오류: {e}"})

@app.get("/list")
def list_files():
    """user-uploads/ 프리픽스 하의 객체 목록."""
    try:
        files = list_objects_in_gcs()
        return JSONResponse(status_code=200, content={
            "status": "Success",
            "bucket": BUCKET_NAME,
            "total": len(files),
            "files": files,
        })
    except HTTPException as he:
        return JSONResponse(status_code=he.status_code,
                            content={"status": "Error", "message": he.detail})
    except Exception as e:
        return JSONResponse(status_code=500,
                            content={"status": "Error", "message": f"서버 오류: {e}"})
