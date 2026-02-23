# 금융상품 시세 실시간 데이터 수집기

주식, 지수, 선물, 통화, 원자재, 채권, 암호화폐 등 다양한 금융상품의 실시간 시세 데이터를 수집하여 WebSocket(Socket.IO)으로 전송하는 파이프라인입니다.

## 주요 기능

- **국내 주식 실시간 시세**: 네이버 금융 API를 통한 코스피/코스닥 전 종목 실시간 시세 수집 (5초 주기)
- **국내 지수선물**: 한경 마켓 WebSocket을 통한 코스피200/코스닥150 선물 실시간 데이터
- **해외 지수**: S&P500, NASDAQ, Dow Jones, Nikkei225, HSI 등
- **통화/원자재/채권/암호화폐**: TradingView WebSocket을 통한 실시간 데이터 수집

## 데이터 소스

| 소스 | 수집 대상 | 방식 |
|------|----------|------|
| 네이버 금융 | 코스피/코스닥 전 종목 실시간 시세 | REST API (비동기, 5초 주기) |
| KRX (한국거래소) | 종목 코드/종목명/시장구분 | REST API + 세션 인증 |
| TradingView | 지수, 통화, 원자재선물, 채권, 암호화폐 | WebSocket |
| 한경 마켓 | 코스피200/코스닥150 선물 | Socket.IO |

## 수집 항목 상세

### 네이버 금융 (stock_price.py)
코스피/코스닥 전 종목의 현재가, 시가, 고가, 저가, 전일종가, 거래량, 거래대금

### TradingView (tradingview.py)

| 카테고리 | 종목 |
|----------|------|
| 국내 지수 | KOSPI, KOSDAQ, KOSPI200, KOSDAQ150 |
| 해외 지수 | S&P500, NASDAQ, Dow Jones, Nikkei225, HSI |
| 채권 금리 | 한국 3/10/30년, 미국 2/10/30년, 일본 2/10/30년 |
| 통화 | USDKRW, JPYKRW, CNYKRW, DXY |
| 지수선물 | ES(S&P500), NQ(NASDAQ) |
| 원자재선물 | 원유(CL, BZ), 천연가스(NG), 금(GC), 은(SI), 구리(HG), 옥수수(ZC), 밀(ZW), 대두(ZS) |
| 암호화폐 | BTC, ETH, XRP (KRW) |

### 한경 마켓 (index_future_hk.py)
코스피200 선물, 코스닥150 선물 실시간 데이터

## 프로젝트 구조

```
├── login_krx.py           # KRX 세션 인증 및 쿠키 관리
├── stock_price.py         # 주식 실시간 시세 수집 (네이버 금융)
├── tradingview.py         # 지수/통화/원자재/채권/암호화폐 실시간 수집 (TradingView)
├── index_future_hk.py     # 국내 지수선물 실시간 수집 (한경 마켓)
└── .env                   # 환경 변수 (서버 URL, KRX 로그인 정보)
```

## 데이터 처리 흐름

```
KRX API → login_krx.py (세션 인증, 20분 주기 갱신)
  └─ stock_price.py (종목 리스트 조회)

네이버 금융 API → stock_price.py (5초 주기, 비동기 배치 요청)
  └─ Socket.IO → 로컬 서버 (stockData)

TradingView WebSocket → tradingview.py (실시간 스트리밍)
  └─ Socket.IO → 로컬 서버 (compositeData)

한경 마켓 WebSocket → index_future_hk.py (실시간 스트리밍)
  └─ Socket.IO → 로컬 서버 (indexFutureDataKor)
```

## 설치 및 실행

### 1. 패키지 설치

```bash
pip install requests pandas aiohttp python-socketio[client] websocket-client python-dotenv
```

### 2. 환경 변수 설정

`.env` 파일을 생성하고 아래 항목을 설정합니다.

```env
# WebSocket 서버 주소
SERVER_URL=http://localhost:8080

# KRX Login (한국거래소)
KRX_ID=your_krx_id
KRX_PW=your_krx_password
```

### 3. 실행

각 스크립트를 개별적으로 실행합니다.

```bash
# 주식 실시간 시세 수집
python stock_price.py

# 지수/통화/원자재/채권/암호화폐 실시간 수집
python tradingview.py

# 국내 지수선물 실시간 수집
python index_future_hk.py
```

## 기술 스택

- **Python 3**
- **aiohttp** — 비동기 HTTP 요청 (주식 시세 배치 수집)
- **websocket-client** — TradingView WebSocket 통신
- **python-socketio** — 로컬 서버 및 한경 마켓 Socket.IO 통신
- **pandas** — 데이터 가공
- **requests** — KRX 세션 인증
- **threading** — 멀티스레딩 (세션 갱신, 데이터 모니터링, 재연결)
