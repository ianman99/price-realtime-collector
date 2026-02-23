import aiohttp
import asyncio
import json
import pandas as pd
import time
from urllib.parse import quote
import requests
import socketio
from dotenv import load_dotenv
import os
import threading
from datetime import datetime, time as dt_time
from login_krx import get_krx_session

# .env 파일 로드
load_dotenv()

# 환경 변수에서 로컬 서버 URL 가져오기
LOCAL_SERVER_URL = os.getenv('SERVER_URL')

# 웹소켓 클라이언트 생성
server_sio = socketio.Client()

# 재연결 방지용 Lock
reconnect_lock = threading.Lock()

@server_sio.event
def connect():
    print("로컬 서버에 성공적으로 연결되었습니다.")

@server_sio.event
def disconnect():
    print("로컬 서버와의 연결이 끊어졌습니다.")

# 로컬 웹소켓 서버에 연결하는 함수
def connect_local_websocket():
    while not server_sio.connected:
        try:
            print("로컬 서버에 연결을 시도합니다...")
            # '/host' 네임스페이스로 연결
            server_sio.connect(LOCAL_SERVER_URL, namespaces=['/host'])
            break
        except Exception as e:
            print(f"로컬 서버 연결 실패: {e}. 2초 후 재시도합니다.")
            time.sleep(2)

def handle_reconnect():
    if reconnect_lock.locked():
        return
    with reconnect_lock:
        if not server_sio.connected:
            print("로컬 서버 재연결을 시도합니다.")
            try:
                server_sio.disconnect()
            except Exception:
                pass
            connect_local_websocket()

# KRX 세션 쿠키 저장용 전역 변수
krx_jsessionid = None

def refresh_krx_session():
    """
    KRX 세션 쿠키를 갱신하는 함수
    20분마다 실행되도록 설계됨
    """
    global krx_jsessionid
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] KRX 세션 쿠키 갱신 시작...")
    try:
        krx_jsessionid = get_krx_session()
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] KRX 세션 쿠키 갱신 완료")
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] KRX 세션 쿠키 갱신 실패: {e}")

def session_refresh_loop():
    """
    20분마다 세션을 갱신하는 루프 함수 (별도 스레드에서 실행)
    """
    while True:
        # 최초 실행 시 update_stock_list에서 이미 호출되었을 수 있지만,
        # 20분 주기를 유지하기 위해 여기서도 계속 호출합니다.
        time.sleep(20 * 60)  # 20분 대기
        refresh_krx_session()

# KRX에서 상세 종목 정보를 가져와 DataFrame으로 반환하는 함수
def get_krx_stock_info_df():
    """
    KRX에서 전종목 정보를 가져와 DataFrame으로 반환하는 함수 (KONEX 제외)
    - 종목코드, 종목명, 시장구분, 상장일을 포함한다.
    """
    global krx_jsessionid
    
    # 세션 쿠키가 없으면 먼저 가져옴
    if krx_jsessionid is None:
        refresh_krx_session()

    print("KRX에서 상세 종목 정보를 가져오는 중...")
    url = 'http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd'
    headers = {
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        'Connection': 'keep-alive',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Origin': 'http://data.krx.co.kr',
        'Referer': 'http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201050103',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        'X-Requested-With': 'XMLHttpRequest',
        'Cookie': f'JSESSIONID={krx_jsessionid}' if krx_jsessionid else ''
    }
    data_payload = {
        'bld': 'dbms/MDC/STAT/standard/MDCSTAT01901',
        'locale': 'ko_KR',
        'mktId': 'ALL',
        'share': '1',
        'csvxls_isNo': 'false',
    }
    try:
        response = requests.post(url, headers=headers, data=data_payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if 'OutBlock_1' not in data:
            print("오류: KRX 응답에서 'OutBlock_1'을 찾을 수 없습니다.")
            return pd.DataFrame()

        # 필요한 데이터만 추출하고 컬럼 이름 변경
        stock_info = [
            {
                'code': item['ISU_SRT_CD'],  # 종목코드
                'name': item['ISU_ABBRV'],  # 종목명
                'mkt': item['MKT_TP_NM'],   # 시장구분
                'listd': item['LIST_DD']    # 상장일
            }
            for item in data['OutBlock_1'] if item['MKT_TP_NM'] != 'KONEX'
        ]
        
        df = pd.DataFrame(stock_info)
        print(f"총 {len(df)}개의 종목 정보를 가져왔습니다. (KONEX 제외)")
        return df
    except requests.exceptions.RequestException as e:
        print(f"KRX에서 종목 코드를 가져오는 중 오류 발생: {e}")
        return pd.DataFrame()
    except json.JSONDecodeError:
        print("오류: KRX 응답이 올바른 JSON 형식이 아닙니다.")
        return pd.DataFrame()

# 전역 변수로 종목 정보 관리
krx_info_df = pd.DataFrame()
stock_code = []
last_update_date = None

# 종목 리스트를 갱신하는 함수
def update_stock_list():
    """
    KRX에서 종목 리스트를 갱신하는 함수
    매일 오전 9시 21분에 실행되도록 설계됨
    """
    global krx_info_df, stock_code, last_update_date
    
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 종목 리스트 갱신 시작")
    krx_info_df = get_krx_stock_info_df()
    stock_code = krx_info_df['code'].tolist() if not krx_info_df.empty else []
    last_update_date = datetime.now().date()
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 종목 리스트 갱신 완료: 총 {len(stock_code)}개")

# 초기 종목 리스트 로드
update_stock_list()

# 한 번의 API 요청으로 처리할 종목 수 (배치 크기)
BATCH_SIZE = 300

# 비동기적으로 배치 단위로 네이버 금융 API에서 데이터 가져오기
async def fetch_batch(session, codes):
    # 종목 코드를 쉼표로 연결하여 쿼리 생성
    # 예: "SERVICE_ITEM:005930,035420"
    query = f"SERVICE_ITEM:{','.join(codes)}"
    # 쿼리를 URL 인코딩하여 특수 문자 처리
    url = f"https://polling.finance.naver.com/api/realtime?query={quote(query)}"
    # 요청 시작 시간 기록
    start_time = time.time()
    try:
        # 비동기 GET 요청, 타임아웃 5초
        async with session.get(url, timeout=5) as response:
            # 요청 소요 시간 계산
            elapsed = time.time() - start_time
            # 응답 상태 코드가 200(성공)인 경우
            if response.status == 200:
                # 응답 텍스트 가져오기
                text = await response.text()
                # 네이버 API는 JSONP 형식으로 응답하므로 접두어/접미어 제거
                # 예: window.__jindo2_callback._5366({...}) -> {...}
                json_str = text.replace("window.__jindo2_callback._5366(", "").rstrip(")")
                # JSON 문자열을 파싱하여 Python 객체로 변환
                data = json.loads(json_str)
                # 응답 데이터의 'result.areas', 코드, 소요 시간, 에러(None) 반환
                return data["result"]["areas"], codes, elapsed, None
            # HTTP 오류 발생 시 에러 메시지 반환
            return None, codes, elapsed, f"HTTP {response.status}"
    except Exception as e:
        # 예외 발생 시 에러 메시지 반환
        return None, codes, elapsed, str(e)

# API 응답 데이터를 파싱하여 주식 정보 추출
def parse_batch(areas, codes):
    # 응답 데이터가 없거나 비어 있는 경우
    # 모든 종목 코드에 대해 None 값으로 채운 딕셔너리 리스트 반환
    if not areas:
        return [{"cd": code, "nv": None, "ov": None, "hv": None, "lv": None, "aq": None, "sv": None, "aa": None} for code in codes]
    
    # 파싱된 결과를 저장할 리스트
    results = []
    # 응답 데이터의 각 영역(area) 처리
    for area in areas:
        # 'SERVICE_ITEM' 영역만 처리 (주식 데이터 포함)
        if area["name"] == "SERVICE_ITEM":
            # 각 종목 데이터(item)에서 필요한 필드 추출
            for item in area["datas"]:
                results.append({
                    "cd": item["cd"],  # 종목 코드
                    "nv": item["nv"],  # 현재가 (now value)
                    "ov": item["ov"],  # 시가 (open value)
                    "hv": item["hv"],  # 고가 (high value)
                    "lv": item["lv"],  # 저가 (low value)
                    "aq": item["aq"],  # 누적 거래량 (accumulated quantity)
                    "sv": item["sv"],  # 전일 종가
                    "aa": item["aa"],  # 누적 거래대금 (accumulated amount)
                    "tyn": item["tyn"] # 거래정지 여부 (Y: 거래정지, N: 거래정지아님)
                })
    # 파싱된 결과 반환
    return results

# 모든 종목 데이터를 비동기적으로 처리
async def process_all_stocks():
    # 모든 종목 데이터를 저장할 리스트
    all_results = []
    # 전체 종목 수
    total_stocks = len(stock_code)
    # 처리된 종목 수
    processed = 0
    # 전체 작업 시작 시간 기록
    total_start_time = time.time()
    
    # aiohttp 클라이언트 세션 생성 (비동기 HTTP 요청 관리)
    async with aiohttp.ClientSession() as session:
        # 배치 단위로 처리할 태스크 리스트
        tasks = []
        # 종목 코드를 BATCH_SIZE(300) 단위로 분할
        for i in range(0, total_stocks, BATCH_SIZE):
            # 현재 배치의 종목 코드 추출
            batch_codes = stock_code[i:i + BATCH_SIZE]
            # 배치 요청 태스크 추가
            tasks.append(fetch_batch(session, batch_codes))
        
        # 모든 배치 요청을 병렬로 실행하고 결과 수집
        results = await asyncio.gather(*tasks)
        
        # 각 배치 결과 처리
        for areas, codes, elapsed, error in results:
            # 에러가 있는 경우 해당 배치 건너뛰기
            if error:
                continue
                
            # 배치 데이터 파싱
            parsed = parse_batch(areas, codes)
            # 파싱된 결과 전체 결과에 추가
            all_results.extend(parsed)
            # 처리된 종목 수 업데이트
            processed += len(parsed)
    
    # 전체 작업 소요 시간 계산
    total_elapsed = time.time() - total_start_time
    
    # 수집된 데이터가 있는 경우
    if all_results:
        # 1. 네이버에서 받은 실시간 가격 정보로 DataFrame 생성
        price_df = pd.DataFrame(all_results, columns=["cd", "nv", "ov", "hv", "lv", "aq", "sv", "aa", "tyn"])
        
        # 2. KRX 정보 DataFrame과 가격 정보 DataFrame을 종목 코드를 기준으로 합치기
        # (price_df의 'cd'와 krx_info_df의 'code'를 기준으로 merge)
        final_df = pd.merge(price_df, krx_info_df, left_on='cd', right_on='code', how='left')
        
        # 중복되는 'code' 컬럼은 제거
        if 'code' in final_df.columns:
            final_df = final_df.drop('code', axis=1)
            
        final_df["cd"] = "A" + final_df["cd"]

        # 3. 최종 DataFrame을 딕셔너리 리스트로 변환
        stock_data_list = final_df.to_dict('records')

        # 전체 종목 데이터를 리스트에 담아 한 번에 전송
        try:
            if server_sio.connected:
                server_sio.emit('stockData', stock_data_list, namespace='/host')
            else:
                print("서버에 연결되어 있지 않아 데이터를 전송할 수 없습니다.")
                handle_reconnect() # 재연결 시도
                # 재연결 후 다시 시도
                if server_sio.connected:
                    server_sio.emit('stockData', stock_data_list, namespace='/host')
        except Exception as e:
            print(f"데이터 전송 중 오류 발생: {e}")
            handle_reconnect()
        
        # 수집 결과 출력
        print(f"수집대상 종목: {total_stocks}개, 수집 및 전송된 종목: {processed}개, 소요시간: {total_elapsed:.2f}초")
    else:
        # 데이터가 없는 경우 메시지 출력
        print("수집된 데이터가 없습니다.")

# 메인 실행 블록
if __name__ == "__main__":
    # 로컬 웹소켓 서버에 먼저 연결
    connect_local_websocket()

    # KRX 세션 갱신을 위한 별도 스레드 시작
    session_thread = threading.Thread(target=session_refresh_loop, daemon=True)
    session_thread.start()

    # 무한 루프 실행
    while True:
        # 현재 시간 확인
        now = datetime.now()
        current_date = now.date()
        current_time = now.time()
        
        # 오전 9시 21분에 종목 리스트 갱신 (오늘 아직 갱신하지 않은 경우)
        if current_time.hour == 9 and current_time.minute == 21:
            if last_update_date != current_date:
                update_stock_list()
        
        # 비동기 함수 실행
        asyncio.run(process_all_stocks())
        # 5초 대기 후 다음 수집 시작
        print("5초 후 다음 데이터 수집을 시작합니다.")
        time.sleep(5)