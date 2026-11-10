"""버스 노선 수집 (국토교통부 TAGO OpenAPI).

흐름: 학교 정류장 → 그 정류장을 지나는 노선 목록 → 노선별 왕복 정류장 목록 → 검증 → 원자적 교체.
- 학교 정류장 ID 는 2026-11-07 TAGO 정류소 검색('폴리텍')으로 직접 확인한 값이다.
  · 폴리텍대학(양방향 2곳)과 폴리텍입구는 학곡리~원창고개~새술막 길(동산면 방향)에 있고,
    PDF 노선안내(2026.09.30)의 '폴리텍입구'와 같은 곳이다.
  · '폴리텍2캠퍼스'(후평동 쪽, 11·14번 등)는 다른 위치라 넣지 않았다. 필요하면 SCHOOL_STOPS 에 추가.
- 실패하거나 결과가 이상하면 저장하지 않는다 → 기존 노선 데이터 유지.
"""

import time

from django.db import transaction
from django.utils import timezone

from .. import tago
from ..models import BusRoute, BusRouteStop, CollectionRun
from .base import ParseError, run_collection

SCHOOL_STOPS = {
    "CCB250001951": "폴리텍대학",   # 시내 → 동산면 방향 (TAGO nodeno 1597)
    "CCB250001952": "폴리텍대학",   # 동산면 → 시내 방향 (nodeno 1598)
    "CCB265000762": "폴리텍입구",   # 동산면 → 시내 방향 (nodeno 1331)
}
MIN_STOPS = 5          # 이보다 정류장이 적은 노선은 응답 이상으로 본다
PAUSE_SEC = 0.3        # 연속 호출 사이 대기


def group_of(route_no) -> str:
    """'901(기점군자리)' → '901', '동산1(동산102)' → '동산1'. 숫자로만 오는 번호(9)도 문자열로."""
    return str(route_no).split("(")[0].strip()


def fetch_bus_data() -> tuple[list[dict], dict[str, list[dict]]]:
    """(노선 목록, 노선ID → 정류장 목록). 네트워크 호출은 여기서만 한다."""
    routes: dict[str, dict] = {}
    for node_id in SCHOOL_STOPS:
        for r in tago.call(tago.STOP_ROUTES, nodeid=node_id, retries=2, timeout=15):
            routes.setdefault(r["routeid"], r)
        time.sleep(PAUSE_SEC)
    stops = {}
    for route_id in routes:
        stops[route_id] = tago.call(tago.ROUTE_STOPS, routeId=route_id, retries=2, timeout=15)
        time.sleep(PAUSE_SEC)
    return list(routes.values()), stops


def validate(routes: list[dict], stops: dict[str, list[dict]]) -> None:
    if not routes:
        raise ParseError("학교 정류장을 지나는 노선이 0개입니다 (응답 이상 가능성).")
    for r in routes:
        rid = r.get("routeid")
        rows = stops.get(rid) or []
        if len(rows) < MIN_STOPS:
            raise ParseError(f"{r.get('routeno')} 정류장 목록이 비정상입니다 ({len(rows)}개).")
        orders = [int(s["nodeord"]) for s in rows]
        if len(set(orders)) != len(orders):
            raise ParseError(f"{r.get('routeno')} 정류장 순번이 중복됩니다.")
        if not any(s.get("nodeid") in SCHOOL_STOPS for s in rows):
            raise ParseError(f"{r.get('routeno')} 노선에 학교 정류장이 없습니다.")


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def save_bus(routes: list[dict], stops: dict[str, list[dict]], collected_at=None) -> tuple[int, str]:
    """검증된 결과로 버스 노선 전체를 한 번에 교체한다(없어진 노선 정리 포함)."""
    collected_at = collected_at or timezone.now()
    with transaction.atomic():
        BusRoute.objects.all().delete()
        stop_count = 0
        for r in routes:
            route = BusRoute.objects.create(
                route_id=r["routeid"], route_no=str(r.get("routeno", "")), group=group_of(r.get("routeno", "")),
                route_type=r.get("routetp", "") or "", start_stop=r.get("startnodenm", "") or "",
                end_stop=r.get("endnodenm", "") or "", collected_at=collected_at,
            )
            rows = sorted(stops[r["routeid"]], key=lambda s: int(s["nodeord"]))
            BusRouteStop.objects.bulk_create([
                BusRouteStop(
                    route=route, order=int(s["nodeord"]), node_id=s.get("nodeid", ""), name=s.get("nodenm", ""),
                    direction=int(s.get("updowncd") or 0), lat=_float(s.get("gpslati")), lng=_float(s.get("gpslong")),
                )
                for s in rows
            ])
            stop_count += len(rows)
    groups = sorted({group_of(r.get("routeno", "")) for r in routes})
    return len(routes), f"노선 {len(routes)}개({', '.join(groups)}), 정류장 {stop_count}개"


def collect_bus(fetcher=fetch_bus_data) -> CollectionRun:
    def job():
        routes, stops = fetcher()
        validate(routes, stops)
        return save_bus(routes, stops)

    return run_collection(CollectionRun.Source.BUS, job)
