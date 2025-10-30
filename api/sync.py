import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from io import BytesIO

# Vercel이 찾을 수 있도록 FastAPI 앱을 정의합니다.
app = FastAPI()

# ----------------------------------------------------
# 1. 환경 변수에서 JSON 문자열을 로드하여 인증 정보로 사용
# ----------------------------------------------------

# GCS 접근 권한으로 SCOPES 설정
SCOPES = [
    'https://www.googleapis.com/auth/devstorage.full_control' 
]

# 환경 변수 유효성 검사 (Vercel 환경 변수)
if 'GOOGLE_CREDENTIALS' not in os.environ:
    # 안전 장치: 환경 변수가 설정되지 않은 경우 처리
    creds_info = None
    credentials = None
else:
    try:
        creds_json = os.environ.get('GOOGLE_CREDENTIALS')
        creds_info = json.loads(creds_json)
        # Service Account 자격 증명 사용
        credentials = service_account.Credentials.from_service_account_info(
            creds_info, 
            scopes=SCOPES,
        )
    except json.JSONDecodeError:
        # JSON 파싱 오류 처리
        creds_info = None
        credentials = None
    except Exception as e:
        # 기타 자격 증명 생성 오류 처리
        credentials = None

# 업로드할 GCS 버킷 이름 (예: vercel-sync-storage-kr)
GCS_BUCKET_NAME = os.environ.get('GCS_BUCKET_NAME')

# ----------------------------------------------------

# 헬퍼 함수: GCS 업로드
def create_and_upload_object(storage_service, bucket_name, object_name, mime_type, content):
    """
    업로드된 파일 데이터를 Google Cloud Storage (GCS)에 객체로 업로드합니다.
    """
    if not bucket_name:
        return {"name": object_name, "status": "Failed", "error": "GCS_BUCKET_NAME environment variable is not set."}
    
    # Credentials 또는 Service 빌드 실패 시 안전 장치
    if not storage_service:
        return {"name": object_name, "status": "Failed", "error": "Google Cloud Storage service not initialized. Check credentials."}

    try:
        media = MediaIoBaseUpload(
            BytesIO(content),
            mimetype=mime_type
        )
        
        # user-uploads/ 폴더 아래에 객체를 저장합니다.
        gcs_path = f"user-uploads/{object_name}"

        # insert()를 사용하여 GCS에 업로드
        uploaded_object = storage_service.objects().insert(
            bucket=bucket_name,
            name=gcs_path,
            media_body=media
        ).execute()

        # 공개 HTTP URL 형식: https://storage.googleapis.com/[버킷 이름]/[객체 이름]
        public_url = f"https://storage.googleapis.com/{bucket_name}/{gcs_path}"

        print(f"Object uploaded: {object_name} (Bucket: {bucket_name})")
        return {
            "name": object_name,
            "status": "Success",
            "bucket": bucket_name,
            "url": public_url
        }
    except Exception as e:
        print(f"Error uploading {object_name} to GCS: {e}")
        return {"name": object_name, "status": "Failed", "error": str(e)}

# ----------------------------------------------------
# 2. 파일 목록 조회 엔드포인트 추가
# ----------------------------------------------------

@app.get("/list")
def list_files_in_gcs():
    """GCS 버킷의 'user-uploads/' 폴더 내 파일 목록을 반환합니다."""

    if not GCS_BUCKET_NAME or not credentials:
        return JSONResponse(
            {"status": "Failed", "message": "Environment variables or credentials not properly set."},
            status_code=500
        )
        
    try:
        storage_service = build('storage', 'v1', credentials=credentials)
    except Exception as e:
        return JSONResponse(
            {"status": "Failed", "message": f"Failed to build Storage service: {e}"},
            status_code=500
        )

    try:
        # 'user-uploads/' 접두사(Prefix)를 사용하여 해당 폴더 내의 객체만 조회합니다.
        # maxResults는 한 번에 가져올 객체 수를 제한합니다.
        request = storage_service.objects().list(
            bucket=GCS_BUCKET_NAME, 
            prefix='user-uploads/',
            maxResults=100
        )
        response = request.execute()
        
        # 목록을 저장할 리스트
        file_list = []
        
        # response['items']가 존재하는 경우 객체 정보를 추출합니다.
        if 'items' in response:
            for item in response['items']:
                # 객체 이름에서 'user-uploads/' 접두사를 제거하여 사용자에게 깔끔한 이름 제공
                clean_name = item['name'].replace('user-uploads/', '', 1)
                
                # root 경로 자체는 제외 (이름이 'user-uploads/'인 경우)
                if clean_name: 
                    # 공개 URL 생성
                    public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{item['name']}"
                    
                    file_list.append({
                        "name": clean_name,
                        "size_bytes": item.get('size'),
                        "mime_type": item.get('contentType'),
                        "last_modified": item.get('updated'),
                        "url": public_url
                    })

        return JSONResponse(
            {
                "status": "Success",
                "bucket": GCS_BUCKET_NAME,
                "file_count": len(file_list),
                "files": file_list
            }
        )

    except Exception as e:
        print(f"Error listing objects from GCS: {e}")
        return JSONResponse(
            {"status": "Failed", "message": f"Error listing files from GCS: {e}"},
            status_code=500
        )

# ----------------------------------------------------
# 3. 파일 업로드 엔드포인트
# ----------------------------------------------------

@app.post("/upload")
async def upload_file_to_gcs(file: UploadFile = File(...)):
    """외부에서 파일을 받아 GCS에 업로드하는 메인 엔드포인트"""
    
    if not credentials:
         return JSONResponse(
            {"status": "Failed", "message": "Service Account credentials are not valid or initialized."},
            status_code=500
        )
    
    # 1. GCS 서비스 객체 빌드
    try:
        storage_service = build('storage', 'v1', credentials=credentials)
    except Exception as e:
        return JSONResponse(
            {"status": "Failed", "message": f"Failed to build Storage service: {e}"},
            status_code=500
        )
    
    file_name = file.filename
    mime_type = file.content_type
    
    try:
        content_bytes = await file.read()
    except Exception as e:
        return JSONResponse(
            {"status": "Failed", "message": f"Failed to read uploaded file: {e}"},
            status_code=400
        )

    # 3. GCS 업로드 실행
    upload_result = create_and_upload_object(
        storage_service, 
        GCS_BUCKET_NAME,
        file_name, 
        mime_type, 
        content_bytes
    )

    # 4. 최종 결과 반환
    if upload_result["status"] == "Success":
        message = f"File '{file_name}' successfully uploaded and publicly accessible."
        return JSONResponse(
            {
                "status": "Success",
                "message": message,
                "file_info": upload_result
            }
        )
    else:
        return JSONResponse(
            {
                "status": "Failed",
                "message": f"Upload failed for '{file_name}'.",
                "error_details": upload_result["error"]
            },
            status_code=500
        )

# ----------------------------------------------------
# 4. 라우팅 설정
# ----------------------------------------------------

@app.get("/")
def check_status():
    """앱 상태 체크용 엔드포인트"""
    return JSONResponse({"status": "ready", "target_bucket": GCS_BUCKET_NAME or "Not Set"})

# FastAPI 앱의 메인 라우팅 설정 (Vercel 환경을 위해 필요)
app.router.routes.insert(0, APIRoute("/", check_status, methods=["GET"]))
app.router.routes.insert(1, APIRoute("/upload", upload_file_to_gcs, methods=["POST"]))
app.router.routes.insert(2, APIRoute("/list", list_files_in_gcs, methods=["GET"]))
