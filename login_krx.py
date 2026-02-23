import requests
import json
import os
import dotenv

dotenv.load_dotenv()

# KRX 로그인 정보
KRX_ID = os.getenv('KRX_ID')
KRX_PW = os.getenv('KRX_PW')

def get_krx_session():
    # 1. 세션 객체 생성 (이 객체가 쿠키를 자동으로 관리합니다)
    session = requests.Session()

    # 2. 공통 헤더 설정
    headers = {
        'accept': 'application/json, text/javascript, */*; q=0.01',
        'accept-language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'origin': 'https://data.krx.co.kr',
        'referer': 'https://data.krx.co.kr/contents/MDC/COMS/client/view/login.jsp?site=mdc',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
        'x-requested-with': 'XMLHttpRequest'
    }

    # 3. 로그인 시도
    login_url = 'https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd'
    login_data = {
        'mbrId': KRX_ID,
        'pw': KRX_PW
    }

    print("--- 세션 초기화 및 로그인 시도 ---")
    # 메인 페이지 방문하여 기본 세션 쿠키 획득
    session.get('https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0101', headers=headers)
    
    # 실제 로그인 POST 요청
    login_response = session.post(login_url, data=login_data, headers=headers)
    
    JSESSIONID = session.cookies.get_dict()['JSESSIONID']
    
    # 획득한 쿠키에서 JSESSIONID 쿠키 확인
    print(f"JSESSIONID 쿠키: {JSESSIONID}")
    
    return JSESSIONID

if __name__ == "__main__":
    get_krx_session()