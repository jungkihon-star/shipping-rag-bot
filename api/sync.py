import os
import json
from google.oauth2 import service_account

# ----------------------------------------------------
# 1. 환경 변수에서 JSON 문자열을 로드하여 인증 정보로 사용
# ----------------------------------------------------
# 환경 변수 이름이 GOOGLE_CREDENTIALS 라고 가정합니다.
if 'GOOGLE_CREDENTIALS' not in os.environ:
    # 환경 변수가 없을 경우에 대한 예외 처리 로직 (필수)
    raise ValueError("GOOGLE_CREDENTIALS environment variable not set.")

# 환경 변수에서 JSON 문자열을 가져와 딕셔너리로 변환
creds_json = os.environ.get('GOOGLE_CREDENTIALS')
creds_info = json.loads(creds_json)

# 서비스 계정 자격 증명 생성
# from_service_account_info를 사용하면 파일 I/O를 건너뛸 수 있습니다.
credentials = service_account.Credentials.from_service_account_info(
    creds_info, 
    scopes=['https://www.googleapis.com/auth/drive.readonly']
)
# ----------------------------------------------------
