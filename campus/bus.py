"""버스 화면 데이터: 노선 줄그림(DB) + 실시간 버스 위치(TAGO, 서버 캐시).

화면 구성
- 탭 = 노선 번호(group). 같은 번호의 변형 노선(routeId 여러 개)을 한 탭에서 함께 보여 준다.
- 칸(panel) 2개 = 학교 정류장 기준 방향
    학교 가는 버스: 시내 → 폴리텍대학(동산면 방향)
    시내 가는 버스: 폴리텍대학·폴리텍입구 → 시내
  각 칸은 학교 정류장 앞 WINDOW_BEFORE 개 정류장 ~ 학교 정류장 다음 1개까지만 그린다(노선 전체는 100개가 넘음).
- 버스 위치: 변형 노선별로 TAGO '노선별 버스 위치'를 불러, 버스가 있는 정류장 순번(nodeord)을
  그 변형의 정류장 목록에서 찾아 칸 안의 위치(pos)로 바꾼다. 칸 밖이면 '더 먼 곳'(far), 학교를 지났으면 뺀다.

실시간 호출 원칙 (docs/DECISIONS.md D-041)
- 화면(HTML)은 DB만 읽는다. 실시간 위치는 별도 JSON 주소에서만, 서버 캐시(기본 30초)를 거쳐 부른다.
- 실패하면 직전 결과(최대 10분)를 '지연' 표시와 함께 보여 주고, 없으면 실패 안내만 한다. 가짜 위치는 만들지 않는다.
- 심야(0~5시)에는 TAGO 를 부르지 않는다(호출 한도 보호).
"""

import re
import time
from dataclasses import dataclass, field

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from . import tago
from .collectors.bus import SCHOOL_STOPS, group_of
from .models import BusRoute

WINDOW_BEFORE = 8
QUIET_HOURS = range(0, 5)        # 0:00~4:59 (Asia/Seoul) 실시간 조회 쉼
LAST_GOOD_SEC = 600              # 실패 시 직전 결과를 보여 줄 최대 시간
LIVE_TIMEOUT_SEC = 4
# TAGO 는 초당 호출 한도가 있다(동시 18개 호출에서 LIMITED_..._PER_SECOND 발생, 2026-11-07). 그래서 차례로 부른다.
CALL_GAP_SEC = 0.2

PANELS = [
    {"key": "to-school", "title": "학교 가는 버스", "sub": "시내 → 폴리텍대학",
     "anchors": ["CCB250001951"]},
    {"key": "to-city", "title": "시내 가는 버스", "sub": "폴리텍대학·폴리텍입구 → 시내",
     "anchors": ["CCB250001952", "CCB265000762"]},
]
assert all(a in SCHOOL_STOPS for p in PANELS for a in p["anchors"])


# ── 노선 줄그림 (DB) ─────────────────────────────────

@dataclass
class Variant:
    route_id: str
    route_no: str
    stops: list[dict]                     # [{"order", "node_id", "name"}] 순번 순
    index_by_order: dict = field(default_factory=dict)

    def __post_init__(self):
        self.index_by_order = {s["order"]: i for i, s in enumerate(self.stops)}

    def anchor_span(self, anchors) -> tuple[int, int] | None:
        """이 변형에서 학교 정류장(anchors)의 첫/마지막 위치. 없으면 None."""
        idx = [i for i, s in enumerate(self.stops) if s["node_id"] in anchors]
        return (idx[0], idx[-1]) if idx else None


def _group_key(group: str):
    """탭 순서: 숫자 노선(시내) 먼저, 그다음 이름순. '동산1' < '동산2' < '동산10'."""
    parts = re.split(r"(\d+)", group)
    return (not group[:1].isdigit(), [int(p) if p.isdigit() else p for p in parts])


def groups() -> list[dict]:
    """[{"key", "type", "count"}] 탭 목록."""
    seen: dict[str, dict] = {}
    for r in BusRoute.objects.all():
        g = seen.setdefault(r.group, {"key": r.group, "type": r.route_type, "count": 0})
        g["count"] += 1
    return sorted(seen.values(), key=lambda g: _group_key(g["key"]))


def variants(group: str) -> list[Variant]:
    result = []
    for r in BusRoute.objects.filter(group=group).prefetch_related("stops"):
        stops = [{"order": s.order, "node_id": s.node_id, "name": s.name} for s in r.stops.all()]
        result.append(Variant(r.route_id, r.route_no, stops))
    return result


def build_panels(group_variants: list[Variant]) -> list[dict]:
    """칸별 줄그림 구간. 학교 정류장 앞 정류장이 가장 많이 보이는 변형을 기준으로 그린다."""
    panels = []
    for spec in PANELS:
        best = None
        for v in group_variants:
            span = v.anchor_span(spec["anchors"])
            if not span:
                continue
            before = min(span[0], WINDOW_BEFORE)
            score = (before, span[1] - span[0], len(v.stops))
            if best is None or score > best[0]:
                best = (score, v, span, before)
        if best is None:
            continue
        _, v, (first, last), before = best
        window = v.stops[first - before:last + 2]
        panels.append({
            **{k: spec[k] for k in ("key", "title", "sub")},
            "stops": [
                {"name": s["name"], "node_id": s["node_id"], "is_school": s["node_id"] in spec["anchors"]}
                for s in window
            ],
            "school_index": before,      # 칸 안에서 첫 학교 정류장 위치
        })
    return panels


# ── 실시간 위치 (TAGO + 캐시) ─────────────────────────

def map_buses(panels: list[dict], group_variants: list[Variant], buses_by_route: dict[str, list[dict]]) -> dict:
    """버스 위치 → 칸별 {"buses": 칸 안 버스, "far": 칸 앞(더 먼 곳)에서 오는 버스}.

    버스 한 대는 한 칸에만 넣는다: 학교 정류장에 먼저 닿는 칸(남은 정류장 수가 가장 작은 칸).
    예) 시내에서 동산면으로 가는 버스는 '학교 가는 버스' 칸에만, 돌아오는 길은 학교를 지난 뒤 '시내 가는 버스'에.
    """
    candidates: dict[str, list[tuple]] = {}   # 버스 → [(정렬 키, 칸, 항목)]
    for panel in panels:
        spec = next(p for p in PANELS if p["key"] == panel["key"])
        window_nodes = [s["node_id"] for s in panel["stops"]]
        for v in group_variants:
            span = v.anchor_span(spec["anchors"])
            if not span:
                continue
            first, last = span
            for n, bus in enumerate(buses_by_route.get(v.route_id, [])):
                idx = _bus_index(v, bus)
                if idx is None or idx > last + 1:
                    continue                          # 위치 불명 또는 학교를 지난 버스
                # 학교 정류장까지 남은 정류장 수: 양수 = 오는 중, 0 = 학교 정류장(폴리텍대학~폴리텍입구), 음수 = 막 지남
                away = first - idx if idx < first else (0 if idx <= last else last - idx)
                stop = v.stops[idx]
                item = {"id": str(bus.get("vehicleno") or f"{v.route_id}-{n}"), "stop": stop["name"],
                        "away": away, "route": v.route_no}
                node = stop["node_id"]
                if node in window_nodes and idx >= first - WINDOW_BEFORE:
                    item["pos"] = window_nodes.index(node)
                elif idx >= first:
                    continue
                candidates.setdefault(item["id"], []).append(((away < 0, abs(away)), panel["key"], item))
    result = {p["key"]: {"buses": [], "far": []} for p in panels}
    for entries in candidates.values():
        _, key, item = min(entries, key=lambda e: e[0])
        result[key]["buses" if "pos" in item else "far"].append(item)
    for box in result.values():
        box["buses"].sort(key=lambda b: (b["pos"], b["id"]))
        box["far"].sort(key=lambda b: b["away"])
    return result


def _bus_index(v: Variant, bus: dict) -> int | None:
    """버스가 있는 정류장의 변형 내 위치. 순번(nodeord) 우선, 그 순번의 정류장 ID 가 응답과 다르면 정류장 ID 로 찾는다."""
    node = bus.get("nodeid")
    try:
        idx = v.index_by_order.get(int(bus.get("nodeord")))
    except (TypeError, ValueError):
        idx = None
    if idx is not None and (not node or v.stops[idx]["node_id"] == node):
        return idx
    if not node:
        return None
    return next((i for i, s in enumerate(v.stops) if s["node_id"] == node), None)


def fetch_locations(route_ids: list[str]) -> dict:
    """노선별 버스 위치를 차례로 부른다(초당 한도 보호). 값은 버스 목록, 실패하면 TagoError. DB 는 건드리지 않는다."""
    results = {}
    for i, rid in enumerate(route_ids):
        if i:
            time.sleep(CALL_GAP_SEC)
        try:
            # 가끔 응답 없이 멈추는 호출이 있어 제한 시간을 짧게 두고 한 번 더 시도한다
            results[rid] = tago.call(tago.BUS_LOCATIONS, routeId=rid, timeout=LIVE_TIMEOUT_SEC, retries=1)
        except tago.TagoError as exc:
            results[rid] = exc
            if isinstance(exc, (tago.TagoQuotaExceeded, tago.TagoRateLimited)):
                break  # 한도에 걸렸으면 나머지도 실패하므로 더 부르지 않는다
    return results


def _error_message(errors) -> tuple[str, str]:
    if any(isinstance(e, tago.TagoQuotaExceeded) for e in errors):
        return "quota", "오늘 실시간 조회 한도를 다 썼어요. 내일 다시 볼 수 있어요."
    if any(isinstance(e, tago.TagoRateLimited) for e in errors):
        return "busy", "요청이 몰려 잠시 쉬고 있어요. 30초 뒤에 다시 불러올게요."
    return "error", "실시간 위치를 불러오지 못했어요."


def live(group: str, now=None) -> dict:
    """탭 하나의 실시간 위치(JSON 으로 내보낼 dict). 캐시·심야·실패를 여기서 처리한다."""
    now = timezone.localtime(now or timezone.now())
    group_variants = variants(group)
    if not group_variants:
        return {"ok": False, "reason": "no_route", "message": "노선 정보가 아직 없어요."}
    if now.hour in QUIET_HOURS:
        return {"ok": True, "quiet": True, "updated": now.strftime("%H:%M"), "panels": {},
                "message": "심야(0~5시)에는 실시간 조회를 쉬어요."}
    if not tago.has_key():
        return {"ok": False, "reason": "no_key", "message": "실시간 위치 설정(API 키)이 아직 안 됐어요."}

    key = f"bus-live:{group}"
    cached = cache.get(key)
    if cached:
        return cached
    route_ids = [v.route_id for v in group_variants]
    results = fetch_locations(route_ids)
    errors = [r for r in results.values() if isinstance(r, Exception)]
    if errors or len(results) < len(route_ids):
        reason, message = _error_message(errors)
        last = cache.get(f"{key}:last")
        if last:
            data = {**last, "delayed": True, "message": f"{message} 직전 위치({last['updated']})를 보여 드려요."}
        else:
            data = {"ok": False, "reason": reason, "message": message}
        cache.set(key, data, settings.LOLYPOLY_BUS_LIVE_CACHE_SEC)  # 실패도 잠깐 묶어 연속 호출 방지
        return data
    buses = {rid: results.get(rid, []) for rid in route_ids}
    panels = build_panels(group_variants)
    data = {"ok": True, "updated": now.strftime("%H:%M:%S"),
            "panels": map_buses(panels, group_variants, buses),
            "count": sum(len(b) for b in buses.values())}
    cache.set(key, data, settings.LOLYPOLY_BUS_LIVE_CACHE_SEC)
    cache.set(f"{key}:last", data, LAST_GOOD_SEC)
    return data


NEAREST_CACHE_SEC = 60
HOME_STOP = "CCB250001951"   # 폴리텍대학 (시내 → 동산면 방향 = 학교 가는 버스가 서는 쪽)


def nearest(now=None) -> dict:
    """홈 '학교 가는 버스' 한 줄: 폴리텍대학 정류장 도착 예정 중 가장 빠른 버스 1대.

    TAGO 정류소별 도착정보 1회 호출(노선 18개 위치를 부르지 않음) + 1분 캐시.
    학교 정류장을 지나는 노선(DB의 노선 번호)만 고른다.
    """
    now = timezone.localtime(now or timezone.now())
    if now.hour in QUIET_HOURS:
        return {"ok": True, "quiet": True, "bus": None, "message": "심야(0~5시)에는 실시간 조회를 쉬어요."}
    if not tago.has_key():
        return {"ok": False, "reason": "no_key", "bus": None, "message": "실시간 위치 설정이 아직 안 됐어요."}
    cached = cache.get("bus-nearest")
    if cached:
        return cached
    try:
        arrivals = tago.call(tago.STOP_ARRIVALS, nodeId=HOME_STOP, timeout=LIVE_TIMEOUT_SEC, retries=1)
    except tago.TagoError as exc:
        reason, message = _error_message([exc])
        data = {"ok": False, "reason": reason, "bus": None, "message": message}
        cache.set("bus-nearest", data, NEAREST_CACHE_SEC)
        return data
    known = {g["key"] for g in groups()}
    best = None
    for a in arrivals:
        group = group_of(a.get("routeno", ""))
        try:
            seconds, away = int(a.get("arrtime")), int(a.get("arrprevstationcnt"))
        except (TypeError, ValueError):
            continue
        if group in known and (best is None or seconds < best["seconds"]):
            best = {"group": group, "route": str(a.get("routeno")), "away": away, "seconds": seconds,
                    "minutes": max(1, round(seconds / 60))}
    data = {"ok": True, "bus": best, "updated": now.strftime("%H:%M"),
            "message": "" if best else "지금 학교 쪽으로 오는 버스가 없어요."}
    cache.set("bus-nearest", data, NEAREST_CACHE_SEC)
    return data
