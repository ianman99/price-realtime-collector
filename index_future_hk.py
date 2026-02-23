import socketio
import json
import time
import os
from dotenv import load_dotenv
import threading

# .env 파일 로드
load_dotenv()

LOCAL_SERVER_URL = os.getenv('SERVER_URL')

server_sio = socketio.Client()

# 중복 재연결 방지용 Lock 객체 생성
db_reconnect_lock = threading.Lock()

@server_sio.event
def connect():
    print("로컬 서버 연결 성공")

@server_sio.event
def disconnect():
    print("로컬 서버 연결 해제")

# 로컬 웹소켓 연결
def connect_local_websocket():
    time.sleep(1)
    while True:
        try:
            if server_sio.connected:
                break
            server_sio.connect(LOCAL_SERVER_URL, namespaces=['/host'])
            print("로컬 웹소켓 서버 연결 성공")
            break
        except Exception as e:
            print(f"로컬 웹소켓 서버 연결 실패: {e}")
            try:
                server_sio.disconnect()
            except Exception:
                pass
            time.sleep(2)
    
# 코스피200 소켓 클라이언트 생성
kospi200_sio = socketio.Client()

@kospi200_sio.event
def connect():
    print("코스피200 Socket.IO 연결 성공")
    
@kospi200_sio.event
def disconnect():
    print("코스피200 서버 연결 해제")

@kospi200_sio.event
def connect_error(data):
    print(f"코스피200 연결 오류: {data}")
    
# 코스피200 소켓 연결
def connect_kospi200():
    while True:
        time.sleep(1)
        try:
            if kospi200_sio.connected:
                break
            kospi200_sio.connect(
                'https://markets-ws.hankyung.com/future?type=kospi200',
                transports=['websocket'],
                headers={
                    "Origin": "https://www.markets.hankyung.com",
                    "User-Agent": "Mozilla/5.0",
                    "Accept-Encoding": "gzip, deflate, br, zstd",
                    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache"
                }
            )
            break
        except Exception as e:
            print(f"코스피200 연결 오류: {e}")
            try:
                kospi200_sio.disconnect()
            except Exception:
                pass
            time.sleep(2)

# 코스피200 선물 데이터 수신
@kospi200_sio.on('kospi200-future', namespace='/future')
def handle_kospi200(data):
    print(data)
    try:
        # 로컬 서버로 전송
        server_sio.emit('indexFutureDataKor', data, namespace='/host')
    except Exception as e:
        print("코스피200 선물 데이터 송신 오류")
        reconnect_local_websocket()

# 코스닥150 소켓 클라이언트 생성
kosdaq150_sio = socketio.Client()

@kosdaq150_sio.event
def connect():
    print("코스닥150 Socket.IO 연결 성공")
    
@kosdaq150_sio.event
def disconnect():
    print("코스닥150 서버 연결 해제")

@kosdaq150_sio.event
def connect_error(data):
    print(f"코스닥150 연결 오류: {data}")

# 코스닥150 소켓 연결
def connect_kosdaq150():
    while True:
        time.sleep(1)
        try:
            if kosdaq150_sio.connected:
                break
            kosdaq150_sio.connect(
                'https://markets-ws.hankyung.com/future?type=kosdaq150',
                transports=['websocket'],
                headers={
                    "Origin": "https://www.markets.hankyung.com",
                    "User-Agent": "Mozilla/5.0",
                    "Accept-Encoding": "gzip, deflate, br, zstd",
                    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache"
                }
            )
            break
        except Exception as e:
            print(f"코스닥150 연결 오류: {e}")
            try:
                kosdaq150_sio.disconnect()
            except Exception:
                pass
            time.sleep(2)

# 코스닥150 선물 데이터 수신
@kosdaq150_sio.on('kosdaq150-future', namespace='/future')
def handle_kosdaq150(data):
    print(data)
    try:
        # 로컬 서버로 전송
        server_sio.emit('indexFutureDataKor', data, namespace='/host')
    except Exception as e:
        print("코스닥150 선물 데이터 송신 오류")
        reconnect_local_websocket()

def reconnect_local_websocket():
    if db_reconnect_lock.locked():
        # 이미 재연결 시도 중이면 리턴
        return
    with db_reconnect_lock:
        try:
            if server_sio.connected:
                return
            server_sio.disconnect()
        except Exception:
            pass
        connect_local_websocket()

if __name__ == "__main__":
    while True:
        try:
            # 소켓 연결
            connect_local_websocket()
            connect_kospi200()
            connect_kosdaq150()

            # 연결 유지
            kospi200_sio.wait()
            kosdaq150_sio.wait()
            server_sio.wait()
            
        except Exception as e:
            print(f"오류 발생: {e}")
    



