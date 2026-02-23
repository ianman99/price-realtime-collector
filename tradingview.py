import websocket
import json
import ssl
import uuid
import re
import time
import socketio
import os
from dotenv import load_dotenv
import threading
import signal
import sys

# .env 파일 로드
load_dotenv()

print(os.getenv('SERVER_URL'))

# 지수 리스트
index_list = ["KRX:KOSPI", "KRX:KOSDAQ", "KRX:KOSPI200", "KRX:KOSDAQ150", "SP:SPX", "TVC:IXIC", "DJ:DJI", "TVC:NI225", "HSI:HSI"]
# 채권 리스트
bond_list = ["TVC:KR03Y" ,"TVC:KR10Y", "TVC:KR30Y","TVC:US02Y" ,"TVC:US10Y", "TVC:US30Y","TVC:JP02Y" ,"TVC:JP10Y", "TVC:JP30Y"]
# 통화 리스트
currency_list = ["FX_IDC:USDKRW", "FX_IDC:JPYKRW", "FX_IDC:CNYKRW", "ICEUS:DXY"]
# 지수 선물 리스트
index_future_list = ["CME_MINI:ES1!", "CME_MINI:NQ1!"]
# 원자재 선물 리스트
commodity_future_list = ["NYMEX:CL1!", "NYMEX:BZ1!", "NYMEX:NG1!", "COMEX:GC1!", "COMEX:SI1!", "COMEX:HG1!", "CBOT:ZC1!", "CBOT:ZW1!", "CBOT:ZS1!"]
# 암호화폐 리스트
crypto_list = ["UPBIT:BTCKRW", "UPBIT:ETHKRW", "UPBIT:XRPKRW"]

LOCAL_SERVER_URL = os.getenv('SERVER_URL')

sio = socketio.Client()

# 중복 재연결 방지용 Lock 객체 생성
db_reconnect_lock = threading.Lock()
tv_reconnect_lock = threading.Lock()

# 재연결 설정
MAX_RECONNECT_ATTEMPTS = 5  # 최대 재연결 시도 횟수
RECONNECT_DELAY = [1, 2, 5, 10, 30]  # 재연결 시도 간격 (초)
reconnect_attempts = 0
is_reconnecting = False
should_stop = False  # 프로그램 종료 플래그

# 데이터 수신 감시 설정
DATA_TIMEOUT = 30  # 30초 동안 데이터가 없으면 재연결
last_data_received_time = time.time()

@sio.event
def connect():
    print("로컬 웹소켓 서버 연결 성공")

@sio.event
def disconnect():
    print("로컬 웹소켓 서버 연결 해제")

# WebSocket URLs
tv_ws_url = "wss://data.tradingview.com/socket.io/websocket"
local_ws_url = LOCAL_SERVER_URL

# Headers from the request
headers = {
    "Origin": "https://www.tradingview.com",
    "User-Agent": "Mozilla/5.0",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache"
}

# 구독 세션 ID 생성 함수
def generate_session_id():
    return f"qs_{str(uuid.uuid4())}"

# 구독 세션 ID 생성
quote_session_id = generate_session_id()

# 최초 연결 여부를 확인하는 플래그
is_first_connection = True

# 로컬 웹소켓 연결
def connect_local_websocket():
    time.sleep(1)
    while True:
        try:
            if sio.connected:
                break
            sio.connect(local_ws_url, namespaces=['/host'])  # 네임스페이스 지정
            print("로컬 웹소켓 서버 연결 성공")
            break
        except Exception as e:
            print(f"로컬 웹소켓 서버 연결 실패: {e}")
            try:
                sio.disconnect()
            except Exception:
                pass
            time.sleep(2)

# 메시지 전송 함수
def send_message(ws, message):
    formatted_message = f"~m~{len(json.dumps(message))}~m~{json.dumps(message)}"
    print(f"전송 메시지: {formatted_message}")
    ws.send(formatted_message)

# Callback functions
def on_open(ws):
    global is_first_connection, last_data_received_time
    print("TradingView WebSocket connection opened")
    
    # 연결 성공 시 데이터 수신 시간 초기화
    last_data_received_time = time.time()
    
    # 연결 성공 시 재연결 카운터 리셋
    reset_reconnect_counter()
    
    # 로컬 웹소켓 서버 연결
    connect_local_websocket()
    
    # 최초 연결 시에만 구독 요청
    if is_first_connection:
        # 1. quote_create_session 메시지 전송
        session_msg = {
            "m": "quote_create_session",
            "p": [quote_session_id]
        }
        send_message(ws, session_msg)
        # 2. quote_set_fields 메시지 전송
        set_fields_msg = {
            "m": "quote_set_fields",
            "p": [quote_session_id, "lp", "low_price", "high_price", "open_price", "prev_close", "ch", "chp", "lp_time", "volume"]
        }
        send_message(ws, set_fields_msg)

        # 3. quote_add_symbols 메시지 전송
        symbols_msg = {
            "m": "quote_add_symbols",
            "p": [quote_session_id, *index_list, *bond_list, *currency_list, *index_future_list, *commodity_future_list, *crypto_list]
        }
        send_message(ws, symbols_msg)
        
        is_first_connection = False

def on_message(ws, message):
    global last_data_received_time

    # 하트비트 메시지 처리
    if "~h~" in message:
        try:
            ws.send(message)  # 하트비트 응답
            print("하트비트 응답 전송됨")
        except Exception as e:
            print(f"하트비트 응답 전송 실패: {e}")
        return
    
    # 메세지를 파싱해서 변수로 추출
    if "session_id" not in message:
        messages = re.findall(r"~m~\d+~m~({.*?})(?=(~m~|$))", message)
        
        # 상품별 데이터를 저장할 딕셔너리
        composite_data = {}
        
        # qsd 메시지에서 v 값 추출
        for msg, _ in messages:  # 튜플 언패킹
            try:
                data = json.loads(msg)
                
                # critical_error 메시지 체크
                if data.get('m') == 'critical_error':
                    error_info = data.get('p', [])
                    print(f"Critical Error 발생: {error_info}")
                    
                    # invalid_method qsd 또는 quote_completed 에러인 경우 재연결 시도
                    if len(error_info) >= 3 and error_info[1] == 'invalid_method' and error_info[2] in ['qsd', 'quote_completed']:
                        print(f"Critical Error ({error_info[2]}) 감지 - TradingView WebSocket 재연결 시작")
                        threading.Thread(target=reconnect_tradingview_websocket).start()
                    continue
                
                # qsd 메시지 처리
                if (data.get('m') == 'qsd' and 
                    len(data.get('p', [])) > 1 and 
                    isinstance(data['p'][1], dict) and 
                    data['p'][1].get('s') == 'ok'):
                    
                    # 유효한 데이터 수신 시 시간 갱신
                    last_data_received_time = time.time()
                    
                    symbol = data['p'][1].get('n')  # 상품 심볼
                    v_data = data['p'][1].get('v', {})  # v 값 추출
                    
                    if symbol and v_data:
                        # 심볼 이름 변경
                        new_symbol = symbol.split(':')[1]
                        
                        # 새로운 심볼로 데이터 저장
                        if new_symbol not in composite_data:
                            composite_data[new_symbol] = {}
                        
                        # 기존 데이터에 새로운 데이터 업데이트
                        composite_data[new_symbol].update(v_data)
                        
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
                print(f"메시지 파싱 오류: {e}, 메시지: {msg}")
                continue
        
        print(message)
        # print(composite_data)
        
        # 로컬 웹소켓 서버로 데이터 전송
        if composite_data:
            try:
                sio.emit('compositeData', composite_data, namespace='/host')
            except Exception as e:
                print(f"로컬 서버로 데이터 전송 실패: {e}")
                reconnect_local_websocket()
        
    else:
        print("session_id 메세지")

def on_error(ws, error):
    global should_stop
    print(f"Error: {error}")
    
    # 심각한 에러인 경우 자동 재연결 시도
    if not should_stop and not is_reconnecting:
        print("에러 발생으로 인한 자동 재연결 시작")
        threading.Thread(target=auto_reconnect_tradingview).start()

# 데이터 수신 상태 모니터링 함수
def monitor_data_stream():
    global last_data_received_time, ws, should_stop

    print("데이터 수신 모니터링 스레드 시작")

    while not should_stop:
        time.sleep(5)  # 5초마다 체크

        if should_stop:
            break

        try:
            elapsed_time = time.time() - last_data_received_time

            # 타임아웃 초과 시 재연결 트리거
            if elapsed_time > DATA_TIMEOUT:
                print(f"\n[Watchdog] {DATA_TIMEOUT}초 동안 데이터 미수신 (경과: {elapsed_time:.1f}초)")
                print("[Watchdog] 하트비트만 수신되고 실제 데이터가 없음 - 강제 재연결을 시도합니다.")

                # 강제로 시간 초기화 (연속 트리거 방지)
                last_data_received_time = time.time()

                # 명시적으로 재연결 함수 호출 (새 세션 생성)
                threading.Thread(target=reconnect_tradingview_websocket).start()

                # 재연결이 시작될 때까지 잠시 대기
                time.sleep(10)

        except Exception as e:
            print(f"[Watchdog] 모니터링 중 오류: {e}")

def on_close(ws, close_status_code, close_msg):
    global should_stop
    print(f"Connection closed: {close_status_code} - {close_msg}")
    
    # 프로그램 종료가 아닌 경우에만 재연결 시도
    if not should_stop:
        print("예상치 못한 연결 종료 - 자동 재연결 시작")
        threading.Thread(target=auto_reconnect_tradingview).start()

def reconnect_local_websocket():
    if db_reconnect_lock.locked():
        # 이미 재연결 시도 중이면 리턴
        return
    with db_reconnect_lock:
        try:
            if sio.connected:
                return
            print("로컬 웹소켓 재연결 시도 중...")
            sio.disconnect()
        except Exception as e:
            print(f"로컬 웹소켓 연결 해제 중 오류: {e}")
        connect_local_websocket()

# TradingView WebSocket 재연결 함수 추가
def reconnect_tradingview_websocket():
    global ws, is_first_connection, quote_session_id
    print("TradingView WebSocket 재연결 시도 중...")
    try:
        if ws:
            ws.close()
    except Exception:
        pass
    
    # 새로운 세션 ID 생성
    quote_session_id = generate_session_id()
    print(f"새로운 세션 ID 생성: {quote_session_id}")
    
    # 세션 재설정
    is_first_connection = True
    
    # 새 WebSocket 연결 생성
    ws = websocket.WebSocketApp(
        tv_ws_url,
        header=headers,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    
    # 재연결 시도
    threading.Thread(target=lambda: ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})).start()

# 자동 재연결 함수 (백오프 전략 포함)
def auto_reconnect_tradingview():
    global ws, is_first_connection, quote_session_id, reconnect_attempts, is_reconnecting, should_stop
    
    # 이미 재연결 시도 중이거나 프로그램이 종료 중이면 리턴
    if tv_reconnect_lock.locked() or should_stop:
        return
        
    with tv_reconnect_lock:
        is_reconnecting = True
        
        while reconnect_attempts < MAX_RECONNECT_ATTEMPTS and not should_stop:
            try:
                # 재연결 시도 간격 계산 (백오프 전략)
                delay = RECONNECT_DELAY[min(reconnect_attempts, len(RECONNECT_DELAY) - 1)]
                print(f"TradingView WebSocket 재연결 시도 {reconnect_attempts + 1}/{MAX_RECONNECT_ATTEMPTS} (대기 시간: {delay}초)")
                
                time.sleep(delay)
                
                if should_stop:
                    break
                
                # 기존 연결 정리
                try:
                    if ws:
                        ws.close()
                except Exception:
                    pass
                
                # 새로운 세션 ID 생성
                quote_session_id = generate_session_id()
                print(f"새로운 세션 ID 생성: {quote_session_id}")
                
                # 세션 재설정
                is_first_connection = True
                
                # 새 WebSocket 연결 생성
                ws = websocket.WebSocketApp(
                    tv_ws_url,
                    header=headers,
                    on_open=on_open,
                    on_message=on_message,
                    on_error=on_error,
                    on_close=on_close
                )
                
                # 재연결 시도
                print("TradingView WebSocket 재연결 시작...")
                ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
                
                # 여기에 도달하면 연결이 성공적으로 종료된 것
                if not should_stop:
                    reconnect_attempts += 1
                    print(f"연결이 종료되었습니다. 재시도 횟수: {reconnect_attempts}")
                else:
                    break
                    
            except Exception as e:
                reconnect_attempts += 1
                print(f"재연결 시도 실패 ({reconnect_attempts}/{MAX_RECONNECT_ATTEMPTS}): {e}")
                
                if reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
                    print("최대 재연결 시도 횟수에 도달했습니다. 재연결을 중단합니다.")
                    break
        
        is_reconnecting = False
        
        # 모든 재연결 시도가 실패한 경우
        if reconnect_attempts >= MAX_RECONNECT_ATTEMPTS and not should_stop:
            print("모든 재연결 시도가 실패했습니다. 프로그램을 종료합니다.")
            should_stop = True

# 연결 성공 시 재연결 카운터 리셋
def reset_reconnect_counter():
    global reconnect_attempts
    reconnect_attempts = 0
    print("연결 성공 - 재연결 카운터 리셋")

# 프로그램 종료 시그널 핸들러 추가

def signal_handler(sig, frame):
    global should_stop
    print("\n프로그램 종료 신호 감지 - 안전하게 종료 중...")
    should_stop = True
    try:
        if ws:
            ws.close()
    except Exception:
        pass
    try:
        if sio.connected:
            sio.disconnect()
    except Exception:
        pass
    sys.exit(0)

# 시그널 핸들러 등록
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# 메인 실행 함수
def main():
    global ws
    
    print("TradingView 실시간 데이터 수집 시작...")

    # 데이터 모니터링 스레드 시작 (데몬 스레드로 실행하여 메인 종료 시 함께 종료)
    monitor_thread = threading.Thread(target=monitor_data_stream)
    monitor_thread.daemon = True
    monitor_thread.start()
    
    try:
        # Create WebSocket connection
        ws = websocket.WebSocketApp(
            tv_ws_url,
            header=headers,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        
        # Run WebSocket (with SSL handling)
        ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
        
    except KeyboardInterrupt:
        print("\n사용자에 의해 프로그램이 중단되었습니다.")
        should_stop = True
    except Exception as e:
        print(f"메인 실행 중 오류 발생: {e}")
        if not should_stop:
            print("자동 재연결 시작...")
            auto_reconnect_tradingview()

if __name__ == "__main__":
    main()
