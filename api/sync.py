import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute  
from io import BytesIO

# Vercel이 찾을 수 있도록 FastAPI 앱을 정의합니다.
app = FastAPI()

# ----------------------------------------------------
# 1. 환경 변수에서 JSON 문자열을 로드하여 인증 정보로 사용
# ----------------------------------------------------

# 파일 업로드(쓰기) 권한을 포함하도록 SCOPES 업데이트
SCOPES = [
    # Drive에 파일 생성/업데이트 권한을 포함하여 저장소 문제를 우회 시도
    'https://www.googleapis.com/auth/drive.file' 
]

if 'GOOGLE_CREDENTIALS' not in os.environ:
    raise ValueError("GOOGLE_CREDENTIALS environment variable not set.")

# 위임을 위한 사용자 이메일 (업로드할 Drive의 실제 사용자 계정)
USER_EMAIL_FOR_DELEGATION = os.environ.get('USER_EMAIL_FOR_DELEGATION')
if not USER_EMAIL_FOR_DELEGATION:
    # 이 오류를 발생시키지 않으려면 다음 단계에서 환경 변수를 설정해야 합니다.
    raise ValueError("USER_EMAIL_FOR_DELEGATION environment variable not set. This is required for Google Drive Service Account Delegation.")


try:
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    creds_info = json.loads(creds_json)
except json.JSONDecodeError:
    raise ValueError("GOOGLE_CREDENTIALS environment variable is not valid JSON.")

try:
    # UPDATED: subject 매개변수를 사용하여 사용자 계정으로 위임합니다.
    # 이렇게 하면 Service Account가 아닌 사용자 계정의 할당량을 사용합니다.
    credentials = service_account.Credentials.from_service_account_info(
        creds_info, 
        scopes=SCOPES,
        subject=USER_EMAIL_FOR_DELEGATION # <-- 핵심 변경 사항: 사용자 위임
    )
except Exception as e:
    raise RuntimeError(f"Failed to create Google credentials: {e}")

# 옵션: 업로드할 폴더 ID를 환경 변수에서 가져옴
# Vercel에 등록하신 'DRIVE_FOLDER_ID'를 사용하도록 변경합니다.
DRIVE_PARENT_FOLDER_ID = os.environ.get('DRIVE_FOLDER_ID')

# ----------------------------------------------------


def create_and_upload_file(drive_service, file_name, mime_type, content, is_text=True):
    """
    메모리에 생성된 파일 데이터를 Google Drive에 업로드합니다.
    - is_text: 내용(content)이 문자열이면 True, 이미 바이트(바이너리)이면 False.
    """
    try:
        # 1. 파일 메타데이터 정의
        file_metadata = {'name': file_name}
        
        # DRIVE_PARENT_FOLDER_ID가 설정되어 있다면, 해당 폴더에 업로드하도록 설정
        if DRIVE_PARENT_FOLDER_ID:
            # 부모 폴더 ID가 있으면 파일의 소유권은 해당 폴더의 소유자(사용자)에게 넘어갑니다.
            file_metadata['parents'] = [DRIVE_PARENT_FOLDER_ID]
            
        # 2. 파일 데이터를 BytesIO 스트림으로 변환
        if is_text:
            # 텍스트 파일은 utf-8로 인코딩하여 바이트로 변환
            content_bytes = content.encode('utf-8')
        else:
            # 바이너리 파일은 이미 바이트여야 함
            content_bytes = content
            
        media = MediaIoBaseUpload(
            BytesIO(content_bytes),
            mimetype=mime_type,
            chunksize=1024*1024, # 1MB 청크 사이즈
            resumable=True
        )

        # 3. Drive API를 사용하여 파일 업로드 실행
        # supportsAllDrives=True와 enforceSingleParent=True를 추가하여 
        # 공유 폴더에 강제 업로드합니다.
        file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webContentLink, parents', # 업로드된 파일 ID와 링크, 부모 폴더 정보 요청
            supportsAllDrives=True,
            enforceSingleParent=True
        ).execute()

        print(f"File uploaded: {file_name} (ID: {file.get('id')})")
        return {
            "name": file_name,
            "id": file.get('id'),
            "link": file.get('webContentLink'),
            "parent_id": file.get('parents')[0] if file.get('parents') else None
        }
    except Exception as e:
        print(f"Error uploading {file_name}: {e}")
        return {"name": file_name, "status": "Failed", "error": str(e)}


# ----------------------------------------------------
# 2. 유연한 라우팅 엔드포인트 정의 및 동기화 로직 실행
# ----------------------------------------------------
@app.get("/")
@app.post("/") 
@app.get("/{path:path}")
@app.post("/{path:path}") 
def handle_sync_request():
    """
    /api/sync 요청을 받아 Google Drive에 가상의 파일을 업로드하는 동기화 로직을 실행합니다.
    """
    uploaded_files = []
    
    # 1. Drive 서비스 객체 빌드
    try:
        drive_service = build('drive', 'v3', credentials=credentials)
    except Exception as e:
        return JSONResponse(
            {"status": "Failed", "message": f"Failed to build Drive service: {e}"},
            status_code=500
        )
    
    # 2. 가상의 파일 데이터 생성 (이전 오류 해결을 위해 바이트 변환 로직은 유지)
    
    # a. 텍스트 파일 
    text_content = "이것은 Vercel Python Function에서 업로드한 테스트 텍스트 파일입니다."
    text_result = create_and_upload_file(
        drive_service, 
        "Vercel_Sync_Test.txt", 
        "text/plain", 
        text_content
    )
    uploaded_files.append(text_result)

    # b. PDF 파일
    pdf_content = (
        "%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        "3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>\nendobj\n"
        "4 0 obj\n<< /Length 32 >>\nstream\nBT /F1 24 Tf 50 700 Td (PDF Test) ET\nendstream\nendobj\n"
        "xref\n0 5\n0000000000 65535 f\n0000000010 00000 n\n0000000059 00000 n\n0000000115 00000 n\n0000000194 00000 n\ntrailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n240\n%%EOF"
    ).encode('latin-1') 
    
    pdf_result = create_and_upload_file(
        drive_service, 
        "Vercel_Sync_Test.pdf", 
        "application/pdf", 
        pdf_content,
        is_text=False
    )
    uploaded_files.append(pdf_result)
    
    # c. 엑셀 파일 (CSV 파일로 업로드)
    excel_content = "Column A,Column B\nData 1,Data 2\n".encode('utf-8') 
    excel_result = create_and_upload_file(
        drive_service, 
        "Vercel_Sync_Test_Spreadsheet.csv", 
        "text/csv", # <--- MIME 타입을 CSV 원본 타입으로 수정했습니다.
        excel_content,
        is_text=False
    )
    uploaded_files.append(excel_result)

    # 3. 최종 결과 반환
    if DRIVE_PARENT_FOLDER_ID:
        message = f"Files successfully uploaded to your shared folder (ID: {DRIVE_PARENT_FOLDER_ID}). Check your Drive."
    else:
        message = "Files uploaded, but storage quota error may persist. Set the DRIVE_PARENT_FOLDER_ID env variable."

    return JSONResponse(
        {
            "status": "Upload attempt complete",
            "message": message,
            "uploaded_files": uploaded_files
        }
    )

# FastAPI 앱의 메인 라우팅 설정 (Vercel 환경을 위해 필요)
app.router.routes.insert(0, APIRoute("/", handle_sync_request, methods=["GET", "POST"]))
