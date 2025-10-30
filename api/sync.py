# (파일 맨 위)
# Vercel 캐시 무효화를 위한 임시 주석 추가 (2025.10.30)
# The RSA warning is harmless and related to Google library's internal key parsing.

import json
import os
import io
import time
from datetime import datetime, timezone
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from fastapi import FastAPI, UploadFile, File, HTTPException
from starlette.responses import JSONResponse

# --- Environment Configuration ---
# GCS_BUCKET_NAME 환경 변수가 설정되어 있어야 합니다.
BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "your-gcs-bucket-name-here")
# GOOGLE_CREDENTIALS 환경 변수에 JSON 서비스 계정 키 내용이 설정되어 있어야 합니다.
CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS")
STORAGE_SCOPES = ['https://www.googleapis.com/auth/devstorage.full_control']

if not CREDENTIALS_JSON:
    raise ValueError("GOOGLE_CREDENTIALS environment variable is not set.")

# --- Initialization and Service Setup ---

def get_gcs_service():
    """
    Service Account JSON을 사용하여 GCS API 서비스 객체를 생성합니다.
    """
    try:
        credentials_info = json.loads(CREDENTIALS_JSON)
        credentials = service_account.Credentials.from_service_account_info(
            credentials_info,
            scopes=STORAGE_SCOPES
        )
        # GCS API 이름은 'storage', 버전은 'v1'입니다.
        storage_service = build('storage', 'v1', credentials=credentials)
        return storage_service
    except Exception as e:
        print(f"Error initializing GCS service: {e}")
        # 오류가 발생해도 바로 종료하지 않고, FastAPI가 에러를 처리하도록 합니다.
        return None

# GCS 서비스 초기화 (FastAPI가 시작될 때 한 번만 수행)
storage_service = get_gcs_service()

app = FastAPI()

# --- Core GCS Functions ---

def create_and_upload_object(storage_service, file_stream, filename, mime_type, bucket_name):
    """
    스트림 데이터를 GCS에 업로드하고 객체에 공개 권한을 부여합니다.
    """
    if not storage_service:
        raise HTTPException(status_code=500, detail="GCS Service Not Initialized.")

    # GCS 객체의 최종 경로 (user-uploads/파일명)
    object_name = f"user-uploads/{filename}"

    # 파일을 바이트 스트림으로 변환
    media = MediaIoBaseUpload(file_stream, mimetype=mime_type, chunksize=1024*1024, resumable=True)

    try:
        # 1. 파일 업로드 요청
        request = storage_service.objects().insert(
            bucket=bucket_name,
            name=object_name,
            media_body=media,
            # publicAccessPrevention이 'uniform'이면 ACL은 무시되지만,
            # IAM 설정을 통해 이미 allUsers:Storage Object Viewer 권한을 부여했으므로 업로드 자체는 성공합니다.
            predefinedAcl='publicRead'
        )
        response = request.execute()

        # 공개 URL 생성 (버킷이 이미 allUsers에 공개되어 있으므로 이 형식으로 접근 가능)
        public_url = f"https://storage.googleapis.com/{bucket_name}/{object_name}"

        return {
            "name": response.get('name'),
            "mimeType": response.get('contentType'),
            "size": int(response.get('size', 0)),
            "url": public_url
        }
    except Exception as e:
        print(f"GCS Upload Error: {e}")
        raise HTTPException(status_code=500, detail=f"GCS 업로드 실패: {e}")

def list_objects_in_gcs(storage_service, bucket_name):
    """
    GCS 버킷의 'user-uploads/' 경로에 있는 객체 목록을 조회합니다.
    """
    if not storage_service:
        return []

    try:
        # user-uploads/ prefix를 사용하여 해당 폴더 내의 객체만 조회
        request = storage_service.objects().list(bucket=bucket_name, prefix='user-uploads/')
        
        items = []
        while request is not None:
            response = request.execute()
            for item in response.get('items', []):
                # 'user-uploads/' 자체는 제외
                if item['name'].endswith('/'):
                    continue

                # UTC 시간을 KST로 변환 (옵션)
                # KST = UTC + 9
                updated_utc = datetime.strptime(item.get('updated').split('.')[0], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
                
                # 파일 이름을 경로 없이 추출
                file_name_only = item['name'].replace('user-uploads/', '', 1)

                items.append({
                    "name": file_name_only,
                    "size_bytes": int(item.get('size', 0)),
                    "mime_type": item.get('contentType'),
                    "updated_kst": updated_utc.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S KST'),
                    "public_url": f"https://storage.googleapis.com/{bucket_name}/{item['name']}"
                })
            request = storage_service.objects().list_next(request, response)
        
        return items
    except Exception as e:
        print(f"GCS List Error: {e}")
        raise HTTPException(status_code=500, detail=f"GCS 목록 조회 실패: {e}")


# --- FastAPI Endpoints ---

@app.post("/upload")
async def upload_file_to_gcs(file: UploadFile = File(...)):
    """
    HTTP POST 요청으로 전송된 파일을 GCS에 업로드하고 공개 URL을 반환합니다.
    """
    try:
        # 파일 내용을 메모리 스트림으로 읽음
        file_content = await file.read()
        file_stream = io.BytesIO(file_content)

        # GCS 업로드 실행
        result = create_and_upload_object(
            storage_service=storage_service,
            file_stream=file_stream,
            filename=file.filename,
            mime_type=file.content_type,
            bucket_name=BUCKET_NAME
        )
        
        return JSONResponse(status_code=200, content={
            "status": "Success",
            "message": f"File '{file.filename}' successfully uploaded and publicly accessible.",
            "file_info": result
        })

    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content={"status": "Error", "message": e.detail})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "Error", "message": f"알 수 없는 서버 오류: {e}"})

@app.get("/list")
async def list_files():
    """
    GCS 버킷에 저장된 파일 목록을 반환합니다.
    """
    try:
        files = list_objects_in_gcs(storage_service, BUCKET_NAME)
        return JSONResponse(status_code=200, content={
            "status": "Success",
            "bucket_name": BUCKET_NAME,
            "total_files": len(files),
            "files": files
        })
    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content={"status": "Error", "message": e.detail})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "Error", "message": f"알 수 없는 서버 오류: {e}"})

@app.get("/")
def home():
    """
    기본 엔드포인트 응답입니다.
    """
    return {"message": "GCS Sync API is running. Use /api/sync/upload to upload files or /api/sync/list to view files."}
