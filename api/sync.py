import os
import json
from google.oauth2 import service_account
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

# Vercel이 찾을 수 있도록 FastAPI 앱을 정의합니다.
app = FastAPI()

# ----------------------------------------------------
# 1. 환경 변수에서 JSON 문자열을 로드하여 인증 정보로 사용
# ----------------------------------------------------
if 'GOOGLE_CREDENTIALS' not in os.environ:
    # 환경 변수가 없을 경우에 대한 예외 처리 로직 (필수)
    raise ValueError("GOOGLE_CREDENTIALS environment variable not set.")

# 환경 변수에서 JSON 문자열을 가져와 딕셔너리로 변환
try:
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    creds_info = json.loads(creds_json)
except json.JSONDecodeError:
    # JSON 파싱 오류 발생 시 (공백, 형식 문제 등이 완전히 해결되지 않았을 경우)
    raise ValueError("GOOGLE_CREDENTIALS environment variable is not valid JSON.")

# 서비스 계정 자격 증명 생성
try:
    credentials = service_account.Credentials.from_service_account_info(
        creds_info, 
        scopes=['https://www.googleapis.com/auth/drive.readonly']
    )
except Exception as e:
    # 개인 키 오류 등 인증 관련 문제 발생 시
    raise RuntimeError(f"Failed to create Google credentials: {e}")

# 인증이 성공적으로 완료되었으며, 이제 credentials 객체를 사용할 수 있습니다.
# 예: drive_service = build('drive', 'v3', credentials=credentials)
# ----------------------------------------------------


# ----------------------------------------------------
# 2. 유연한 라우팅 엔드포인트 정의 (Vercel에서 필수)
# ----------------------------------------------------

# Vercel이 /api/sync 경로를 인식하도록 유연한 라우팅을 설정합니다.
# GET 및 POST 요청을 모두 처리하도록 설정하여 테스트 용이성을 높입니다.
@app.get("/")
@app.post("/") 
@app.get("/{path:path}")
@app.post("/{path:path}") 
def handle_sync_request():
    """
    이 엔드포인트는 /api/sync 경로로 들어오는 모든 GET 및 POST 요청을 처리합니다.
    """
    # TODO: 여기에 실제 Google Drive 동기화 로직을 구현해야 합니다.

    # 임시 응답: 인증과 라우팅이 성공했음을 확인합니다.
    # 만약 이 응답을 받지 못하고 500 에러 또는 SIGKILL이 발생하면 메모리 문제가 재발한 것입니다.
    return JSONResponse(
        {
            "status": "Sync endpoint is running and Google authentication succeeded.",
            "message": "Now you can implement the actual drive sync logic here."
        }
    )

# FastAPI 앱의 메인 라우팅 설정 (Vercel 환경을 위해 필요)
app.router.routes.insert(0, APIRoute("/", handle_sync_request, methods=["GET", "POST"]))

# 이 코드는 Vercel 환경에서 사용되지 않으나, 로컬 테스트를 위해 남겨둡니다.
# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)
