import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute  # <<< APIRoute 임포트 추가
from io import BytesIO

# Vercel이 찾을 수 있도록 FastAPI 앱을 정의합니다.
app = FastAPI()

# ----------------------------------------------------
# 1. 환경 변수에서 JSON 문자열을 로드하여 인증 정보로 사용
# ----------------------------------------------------

# 파일 업로드(쓰기) 권한을 포함하도록 SCOPES 업데이트
SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/drive.file' # Drive에 파일 생성/업데이트 권한
]

if 'GOOGLE_CREDENTIALS' not in os.environ:
    raise ValueError("GOOGLE_CREDENTIALS environment variable not set.")

try:
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    creds_info = json.loads(creds_json)
except json.JSONDecodeError:
    raise ValueError("GOOGLE_CREDENTIALS environment variable is not valid JSON.")

try:
    # 업데이트된 SCOPES를 사용하여 credentials 객체 생성
    credentials = service_account.Credentials.from_service_account_info(
        creds_info, 
        scopes=SCOPES
    )
except Exception as e:
    raise RuntimeError(f"Failed to create Google credentials: {e}")
# ----------------------------------------------------


def create_and_upload_file(drive_service, file_name, mime_type, content):
    """
    메모리에 생성된 파일 데이터를 Google Drive에 업로드합니다.
    """
    try:
        # 1. 파일 메타데이터 정의
        file_metadata = {'name': file_name}
        
        # 2. 파일 데이터를 BytesIO 스트림으로 변환
        # 파일 내용을 메모리에 저장
        content_bytes = content.encode('utf-8') if 'text' in mime_type else content
        media = MediaIoBaseUpload(
            BytesIO(content_bytes),
            mimetype=mime_type,
            chunksize=1024*1024, # 1MB 청크 사이즈
            resumable=True
        )

        # 3. Drive API를 사용하여 파일 업로드 실행
        file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webContentLink' # 업로드된 파일 ID와 링크만 요청
        ).execute()

        print(f"File uploaded: {file_name} (ID: {file.get('id')})")
        return {
            "name": file_name,
            "id": file.get('id'),
            "link": file.get('webContentLink')
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
    
    # 2. 가상의 파일 데이터 생성
    
    # a. 텍스트 파일
    text_content = "이것은 Vercel Python Function에서 업로드한 테스트 텍스트 파일입니다."
    text_result = create_and_upload_file(
        drive_service, 
        "Vercel_Sync_Test.txt", 
        "text/plain", 
        text_content
    )
    uploaded_files.append(text_result)

    # b. PDF 파일 (간단한 텍스트 기반 PDF 생성)
    # PDF는 복잡하여 실제 Python에서 생성하기 어려우므로, 
    # 여기서는 간단한 텍스트 파일 업로드를 대체하고 MIME 타입만 PDF로 설정하여 테스트합니다.
    # **실제 PDF 파일을 업로드하려면 외부 라이브러리(예: reportlab)를 사용해야 합니다.**
    pdf_content = "%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>\nendobj\n4 0 obj\n<< /Length 32 >>\nstream\nBT /F1 24 Tf 50 700 Td (PDF Test) ET\nendstream\nendobj\nxref\n0 5\n0000000000 65535 f\n0000000010 00000 n\n0000000059 00000 n\n0000000115 00000 n\n0000000194 00000 n\ntrailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n240\n%%EOF"
    pdf_result = create_and_upload_file(
        drive_service, 
        "Vercel_Sync_Test.pdf", 
        "application/pdf", 
        pdf_content
    )
    uploaded_files.append(pdf_result)
    
    # c. 엑셀 파일 (.xlsx)
    # 엑셀 파일은 복잡하여 실제 Python에서 생성하기 어려우므로, 
    # 여기서는 Google Sheets MIME 타입으로 업로드하여 Google Sheets 파일로 변환되도록 테스트합니다.
    # 실제 Excel(.xlsx) 파일을 업로드하려면 openpyxl과 같은 라이브러리로 바이너리 데이터를 생성해야 합니다.
    excel_content = "Column A,Column B\nData 1,Data 2\n" # CSV 형식의 간단한 데이터
    excel_result = create_and_upload_file(
        drive_service, 
        "Vercel_Sync_Test_Spreadsheet.csv", # CSV를 업로드하여 Sheets로 변환 가능
        "application/vnd.google-apps.spreadsheet", # Sheets 파일로 변환하도록 요청
        excel_content
    )
    uploaded_files.append(excel_result)

    # 3. 최종 결과 반환
    return JSONResponse(
        {
            "status": "Upload complete",
            "message": "Files successfully created in your Google Drive (check the links below).",
            "uploaded_files": uploaded_files
        }
    )

# FastAPI 앱의 메인 라우팅 설정 (Vercel 환경을 위해 필요)
app.router.routes.insert(0, APIRoute("/", handle_sync_request, methods=["GET", "POST"]))
