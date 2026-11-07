"""버스: TAGO 클라이언트·노선 수집·실시간 위치 계산·화면.

데이터는 2026-11-07 실제 TAGO 응답을 저장한 fixtures/tago/*.json 을 쓴다(네트워크 없이 실행).
"""

import io
import json
import urllib.error
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from campus import bus, tago
from campus.collectors.bus import SCHOOL_STOPS, collect_bus, group_of
from campus.models import BusRoute, BusRouteStop, CollectionRun

from .helpers import FIXTURES

KST = ZoneInfo("Asia/Seoul")
DAYTIME = datetime(2026, 11, 9, 8, 0, tzinfo=KST)    # 월요일 아침
NIGHT = datetime(2026, 11, 9, 2, 0, tzinfo=KST)


def tago_fixture(name):
    return json.loads((FIXTURES / "tago" / f"{name}.json").read_text(encoding="utf-8"))


def real_fetcher():
    """저장된 실제 응답으로 (노선, 정류장) 만들기: 901(기점군자리) + 동산3 두 노선만."""
    routes = {}
    for node in SCHOOL_STOPS:
        for r in tago.items(tago_fixture(f"thrgh_{node}")):
            routes.setdefault(r["routeid"], r)
    keep = ["CCB250090101", "CCB250052900"]
    stops = {rid: tago.items(tago_fixture(f"stops_{rid}")) for rid in keep}
    return [routes[rid] for rid in keep], stops


def seed():
    run = collect_bus(fetcher=real_fetcher)
    assert run.status == CollectionRun.Status.SUCCESS, run.message
    return run


def stop_order(route_id, name, direction):
    return BusRouteStop.objects.get(route__route_id=route_id, name=name, direction=direction).order


class TagoClientTests(TestCase):
    def test_items_handles_zero_one_many(self):
        self.assertEqual(tago.items({"response": {"body": {"items": ""}}}), [])
        self.assertEqual(tago.items({"response": {"body": {"items": {"item": {"a": 1}}}}}), [{"a": 1}])
        self.assertEqual(len(tago.items(tago_fixture("stops_CCB250090101"))), 149)

    @override_settings(TAGO_SERVICE_KEY="")
    def test_missing_key(self):
        with self.assertRaises(tago.TagoKeyMissing):
            tago.call(tago.BUS_LOCATIONS, routeId="X")

    @override_settings(TAGO_SERVICE_KEY="test-key")
    def test_service_errors(self):
        body = json.dumps({"OpenAPI_ServiceResponse": {"cmmMsgHeader": {
            "errMsg": "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR"}}}).encode()
        err = urllib.error.HTTPError("u", 403, "Forbidden", {}, io.BytesIO(body))
        with patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(tago.TagoQuotaExceeded):
                tago.call(tago.BUS_LOCATIONS, routeId="X")
        per_second = urllib.error.HTTPError("u", 403, "Forbidden", {}, io.BytesIO(json.dumps({"OpenAPI_ServiceResponse": {
            "cmmMsgHeader": {"errMsg": "LIMITED_NUMBER_OF_SERVICE_REQUESTS_PER_SECOND_EXCEEDS_ERROR"}}}).encode()))
        with patch("urllib.request.urlopen", side_effect=per_second):
            with self.assertRaises(tago.TagoRateLimited):
                tago.call(tago.BUS_LOCATIONS, routeId="X")
        bad = urllib.error.HTTPError("u", 403, "Forbidden", {}, io.BytesIO(json.dumps({"OpenAPI_ServiceResponse": {
            "cmmMsgHeader": {"errMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR"}}}).encode()))
        with patch("urllib.request.urlopen", side_effect=bad):
            with self.assertRaisesMessage(tago.TagoError, "SERVICE_KEY_IS_NOT_REGISTERED_ERROR"):
                tago.call(tago.BUS_LOCATIONS, routeId="X")

    @override_settings(TAGO_SERVICE_KEY="secret-key-value")
    def test_retry_then_fail_without_leaking_key(self):
        with patch("urllib.request.urlopen", side_effect=ConnectionResetError()) as m, patch("time.sleep"):
            with self.assertRaises(tago.TagoError) as ctx:
                tago.call(tago.BUS_LOCATIONS, routeId="X", retries=2)
        self.assertEqual(m.call_count, 3)
        self.assertNotIn("secret-key-value", str(ctx.exception))


class CollectBusTests(TestCase):
    def test_group_names(self):
        self.assertEqual(group_of("901(기점군자리)"), "901")
        self.assertEqual(group_of("동산1(동산102)"), "동산1")
        self.assertEqual(group_of(9), "9")

    def test_collect_saves_routes_and_stops_without_duplicates(self):
        seed()
        seed()  # 다시 수집해도 중복 없음
        self.assertEqual(BusRoute.objects.count(), 2)
        self.assertEqual(BusRouteStop.objects.filter(route__route_id="CCB250090101").count(), 149)
        r = BusRoute.objects.get(route_id="CCB250090101")
        self.assertEqual((r.group, r.route_no, r.route_type), ("901", "901(기점군자리)", "지선버스"))

    def test_failure_keeps_existing_data(self):
        seed()

        def broken():
            routes, stops = real_fetcher()
            stops["CCB250052900"] = stops["CCB250052900"][:2]  # 비정상: 정류장 2개
            return routes, stops

        run = collect_bus(fetcher=broken)
        self.assertEqual(run.status, CollectionRun.Status.FAILED)
        self.assertEqual(BusRoute.objects.count(), 2)
        self.assertEqual(BusRouteStop.objects.filter(route__route_id="CCB250052900").count(), 133)

    @override_settings(TAGO_SERVICE_KEY="")
    def test_missing_key_is_recorded_as_failure(self):
        run = collect_bus()
        self.assertEqual(run.status, CollectionRun.Status.FAILED)
        self.assertIn("TAGO_SERVICE_KEY", run.message)

    @override_settings(TAGO_SERVICE_KEY="")
    def test_command_if_empty_does_not_fail(self):
        call_command("collect_bus", "--if-empty", stdout=io.StringIO(), stderr=io.StringIO())
        seed()
        out = io.StringIO()
        call_command("collect_bus", "--if-empty", stdout=out)
        self.assertIn("건너뜁니다", out.getvalue())


class BusPanelTests(TestCase):
    def setUp(self):
        seed()
        self.variants = bus.variants("901")
        self.panels = bus.build_panels(self.variants)

    def test_panels_end_at_school_stop(self):
        to_school, to_city = self.panels
        self.assertEqual(to_school["key"], "to-school")
        self.assertEqual(to_school["stops"][to_school["school_index"]]["name"], "폴리텍대학")
        self.assertEqual(to_school["school_index"], bus.WINDOW_BEFORE)
        school = [s["name"] for s in to_city["stops"] if s["is_school"]]
        self.assertEqual(school, ["폴리텍대학", "폴리텍입구"])

    def test_map_buses(self):
        rid = "CCB250090101"
        buses = {rid: [
            {"vehicleno": "A", "nodeord": stop_order(rid, "원창고개", 0)},     # 학교 3정거장 전 (칸 안)
            {"vehicleno": "B", "nodeord": stop_order(rid, "석사A", 0)},         # 칸보다 먼 곳
            {"vehicleno": "C", "nodeord": stop_order(rid, "폴리텍입구", 1)},    # 시내 방향 학교 정류장
            {"vehicleno": "D", "nodeord": stop_order(rid, "굴지리종점", 1)},    # 시내 방향 먼 곳
            {"vehicleno": "E", "nodeord": 999},                                  # 위치 불명 → 무시
        ]}
        result = bus.map_buses(self.panels, self.variants, buses)
        school = result["to-school"]
        self.assertEqual([(b["id"], b["away"]) for b in school["buses"]], [("A", 3)])
        self.assertEqual(self.panels[0]["stops"][school["buses"][0]["pos"]]["name"], "원창고개")
        self.assertEqual([b["id"] for b in school["far"]], ["B"])
        city = result["to-city"]
        self.assertEqual([(b["id"], b["away"]) for b in city["buses"]], [("C", 0)])
        self.assertIn("D", [b["id"] for b in city["far"]])
        # 학교 가는 버스 칸에서 시내 방향 버스(C)는 학교를 지났으므로 빠진다
        self.assertNotIn("C", [b["id"] for b in school["buses"] + school["far"]])
        # 버스 한 대는 학교에 먼저 닿는 칸 하나에만: 시내에서 오는 B 는 '시내 가는 버스' 칸에 없다
        self.assertNotIn("B", [b["id"] for b in city["buses"] + city["far"]])

    def test_node_id_wins_when_order_disagrees(self):
        """2026-11-07 08시 실제 응답 형식: nodeord 는 정수, 좌표는 문자열일 때도 있음."""
        rid = "CCB250090101"
        real = {"gpslati": "37.79857", "gpslong": 127.77751, "nodeid": "CCB250001952", "nodenm": "폴리텍대학",
                "nodeord": 3, "routenm": "901(기점군자리)", "routetp": "지선버스", "vehicleno": "강원70자1099"}
        result = bus.map_buses(self.panels, self.variants, {rid: [real]})
        self.assertEqual([(b["stop"], b["away"]) for b in result["to-city"]["buses"]], [("폴리텍대학", 0)])


@override_settings(TAGO_SERVICE_KEY="test-key", LOLYPOLY_BUS_LIVE_CACHE_SEC=30)
class BusLiveTests(TestCase):
    def setUp(self):
        cache.clear()
        seed()

    def test_live_uses_cache(self):
        rid = "CCB250090101"
        order = stop_order(rid, "원창고개", 0)
        with patch("campus.tago.call", return_value=[{"vehicleno": "A", "nodeord": order}]) as m:
            first = bus.live("901", now=DAYTIME)
            second = bus.live("901", now=DAYTIME)
        self.assertTrue(first["ok"])
        self.assertEqual(first["panels"]["to-school"]["buses"][0]["away"], 3)
        self.assertEqual(first, second)
        self.assertEqual(m.call_count, 1)   # 901 노선(fixture 1개) 1회만 호출

    def test_night_skips_api(self):
        with patch("campus.tago.call") as m:
            data = bus.live("901", now=NIGHT)
        self.assertTrue(data["quiet"])
        m.assert_not_called()

    def test_failure_shows_last_good_or_error(self):
        with patch("campus.tago.call", side_effect=tago.TagoError("x")):
            data = bus.live("901", now=DAYTIME)
        self.assertFalse(data["ok"])
        cache.clear()
        with patch("campus.tago.call", return_value=[]):
            bus.live("901", now=DAYTIME)
        cache.delete("bus-live:901")
        with patch("campus.tago.call", side_effect=tago.TagoQuotaExceeded("limit")):
            data = bus.live("901", now=DAYTIME)
        self.assertTrue(data["ok"])
        self.assertTrue(data["delayed"])
        self.assertIn("한도", data["message"])

    def test_nearest_uses_one_arrival_call(self):
        arrivals = [  # 2026-11-07 실제 도착정보 응답 형식
            {"arrprevstationcnt": 5, "arrtime": 420, "nodeid": "CCB250001951", "nodenm": "폴리텍대학",
             "routeid": "CCB250090101", "routeno": "901(기점군자리)", "routetp": "지선버스", "vehicletp": "일반차량"},
            {"arrprevstationcnt": 2, "arrtime": 150, "nodeid": "CCB250001951", "nodenm": "폴리텍대학",
             "routeid": "CCB250052900", "routeno": "동산3(동산301)", "routetp": "마을버스", "vehicletp": "일반차량"},
            {"arrprevstationcnt": 1, "arrtime": 30, "routeno": 99},   # 학교 노선 목록에 없는 번호 → 제외
        ]
        with patch("campus.tago.call", return_value=arrivals) as m:
            data = bus.nearest(now=DAYTIME)
            bus.nearest(now=DAYTIME)   # 1분 캐시
        self.assertEqual(m.call_count, 1)
        self.assertEqual(m.call_args.args[0], tago.STOP_ARRIVALS)
        self.assertEqual((data["bus"]["group"], data["bus"]["away"], data["bus"]["minutes"]), ("동산3", 2, 2))

    def test_nearest_none_and_errors(self):
        with patch("campus.tago.call", return_value=[]):
            data = bus.nearest(now=DAYTIME)
        self.assertIsNone(data["bus"])
        self.assertIn("없어요", data["message"])
        cache.clear()
        with patch("campus.tago.call", side_effect=tago.TagoRateLimited("PER_SECOND")):
            data = bus.nearest(now=DAYTIME)
        self.assertEqual(data["reason"], "busy")
        self.assertNotIn("오늘", data["message"])   # 초당 한도를 '오늘 한도'로 안내하지 않는다

    def test_live_stops_calling_after_rate_limit(self):
        cache.clear()
        with patch("campus.tago.call", side_effect=tago.TagoRateLimited("PER_SECOND")) as m, patch("time.sleep"):
            data = bus.live("동산3", now=DAYTIME)
        self.assertEqual(data["reason"], "busy")
        self.assertEqual(m.call_count, 1)

    @override_settings(TAGO_SERVICE_KEY="")
    def test_no_key(self):
        data = bus.live("901", now=DAYTIME)
        self.assertEqual(data["reason"], "no_key")


class BusViewTests(TestCase):
    def test_empty_database(self):
        res = self.client.get(reverse("campus:bus"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "버스 노선 정보가 아직 없어요")
        self.assertNotContains(res, "bus.js")

    def test_page_with_routes(self):
        seed()
        res = self.client.get(reverse("campus:bus"))
        self.assertContains(res, "학교 가는 버스")
        self.assertContains(res, "시내 가는 버스")
        self.assertContains(res, "route-stop--school")
        self.assertContains(res, "13:15")            # 901 운행 시각(노선도 기준)
        self.assertContains(res, 'aria-current="true">901<')
        res = self.client.get(reverse("campus:bus") + "?route=동산3")
        self.assertContains(res, 'aria-current="true">동산3<')
        self.assertContains(res, "폴리텍 입구 경유")
        res = self.client.get(reverse("campus:bus") + "?route=없는노선")
        self.assertContains(res, 'aria-current="true">901<')   # 모르는 값 → 첫 노선

    @override_settings(TAGO_SERVICE_KEY="")
    def test_live_endpoint(self):
        seed()
        with patch("campus.bus.timezone.now", return_value=DAYTIME):
            res = self.client.get(reverse("campus:bus_live", args=["901"]))
        self.assertEqual(res.status_code, 200)
        self.assertIn("no-cache", res["Cache-Control"])
        self.assertEqual(res.json()["reason"], "no_key")
        self.assertEqual(self.client.get(reverse("campus:bus_live", args=["없음"])).status_code, 404)

    def test_home_has_bus_shortcut(self):
        res = self.client.get(reverse("campus:home"))
        self.assertContains(res, reverse("campus:bus"))

    @override_settings(TAGO_SERVICE_KEY="")   # 테스트는 실제 TAGO 를 부르지 않는다
    def test_home_bus_card_only_with_routes(self):
        res = self.client.get(reverse("campus:home"))
        self.assertNotContains(res, "data-bus-nearest")
        seed()
        res = self.client.get(reverse("campus:home"))
        self.assertContains(res, 'data-bus-nearest="%s"' % reverse("campus:bus_nearest"))
        self.assertEqual(self.client.get(reverse("campus:bus_nearest")).status_code, 200)
