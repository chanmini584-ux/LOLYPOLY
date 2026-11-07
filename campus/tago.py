"""국토교통부 TAGO 버스 OpenAPI 클라이언트 (공공데이터포털 apis.data.go.kr).

- 키: 환경변수 TAGO_SERVICE_KEY (공공데이터포털 'Decoding' 키). 코드·Git·로그에 남기지 않는다.
  키는 주소의 serviceKey 값으로 보내므로, 오류 메시지에 요청 주소를 넣지 않는다.
- 응답: _type=json. item 이 0건이면 items == "", 1건이면 dict, 여러 건이면 list 로 온다.
- 오류: 키 오류·호출 한도 초과는 HTTP 403/200 + OpenAPI_ServiceResponse(errMsg) 형태로 온다.
- 2026-11-07 실제 호출로 확인: 춘천 cityCode=32010, 노선 하나(routeId)는 왕복 전체 정류장을
  nodeord 순서로 담고 updowncd(0=가는 방향, 1=돌아오는 방향)로 방향을 구분한다.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

BASE = "https://apis.data.go.kr/1613000"
CITY_CODE = 32010  # 춘천시 (getCtyCodeList 확인 2026-11-07)

ROUTE_STOPS = "BusRouteInfoInqireService/getRouteAcctoThrghSttnList"   # 노선별 경유 정류소
STOP_ROUTES = "BusSttnInfoInqireService/getSttnThrghRouteList"         # 정류소별 경유 노선
BUS_LOCATIONS = "BusLcInfoInqireService/getRouteAcctoBusLcList"        # 노선별 버스 위치
STOP_ARRIVALS = "ArvlInfoInqireService/getSttnAcctoArvlPrearngeInfoList"  # 정류소별 도착 예정


class TagoError(Exception):
    """TAGO 호출 실패 (네트워크·응답 형식·서비스 오류)."""


class TagoKeyMissing(TagoError):
    """TAGO_SERVICE_KEY 가 설정되지 않음."""


class TagoQuotaExceeded(TagoError):
    """일일 호출 한도 초과."""


class TagoRateLimited(TagoError):
    """초당 호출 한도 초과 (잠깐 기다리면 풀림). 2026-11-07 동시 호출 18개에서 실제로 발생."""


def has_key() -> bool:
    return bool(settings.TAGO_SERVICE_KEY)


def items(data: dict) -> list[dict]:
    """응답 JSON → item 목록. 0건('')·1건(dict)·여러 건(list)을 모두 list 로."""
    box = data.get("response", {}).get("body", {}).get("items")
    if not box:
        return []
    item = box.get("item", [])
    return item if isinstance(item, list) else [item]


def _check(data: dict) -> None:
    """서비스 오류 응답이면 예외. 정상(00)·데이터 없음(03)은 통과."""
    service = data.get("OpenAPI_ServiceResponse")
    if service:
        msg = service.get("cmmMsgHeader", {}).get("errMsg", "알 수 없는 오류")
        if "PER_SECOND" in msg:
            raise TagoRateLimited(msg)
        if "LIMITED" in msg:
            raise TagoQuotaExceeded(msg)
        raise TagoError(msg)
    header = data.get("response", {}).get("header", {})
    code = str(header.get("resultCode", "00"))
    if code in ("00", "03"):
        return
    msg = f"{code} {header.get('resultMsg', '')}".strip()
    if code == "22":
        raise TagoQuotaExceeded(msg)
    raise TagoError(msg)


def call(path: str, *, timeout: float | None = None, retries: int = 1, **params) -> list[dict]:
    """TAGO API 한 번 호출 → item 목록. 연결 끊김 등 일시 오류는 retries 번 다시 시도한다."""
    key = settings.TAGO_SERVICE_KEY
    if not key:
        raise TagoKeyMissing("TAGO_SERVICE_KEY 가 설정되지 않았습니다.")
    query = {"serviceKey": key, "_type": "json", "numOfRows": 300, "pageNo": 1, "cityCode": CITY_CODE, **params}
    url = f"{BASE}/{path}?{urllib.parse.urlencode(query)}"
    timeout = timeout or settings.TAGO_TIMEOUT_SEC
    name = path.split("/")[-1]
    last: Exception | None = None
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(0.5 * attempt)
        try:
            with urllib.request.urlopen(url, timeout=timeout) as res:
                raw = res.read()
        except urllib.error.HTTPError as exc:
            try:
                data = json.loads(exc.read())  # 키 오류·한도 초과는 403 본문에 사유가 있다
            except ValueError:
                data = {}
            _check(data)
            raise TagoError(f"{name}: HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last = exc  # 일시 오류 → 다시 시도
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            raise TagoError(f"{name}: JSON 이 아닌 응답") from None
        _check(data)
        return items(data)
    raise TagoError(f"{name}: 연결 실패 ({type(last).__name__})")
