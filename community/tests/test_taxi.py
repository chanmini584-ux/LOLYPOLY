"""번개 택시방: 규칙(서비스)과 화면(뷰). 설계 docs/superpowers/specs/2026-11-11-taxi-rooms-design.md"""

import threading
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.db import close_old_connections
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Department
from community import services, taxi
from community.models import Block, TaxiMember, TaxiMessage, TaxiReport, TaxiRoom

from .helpers import CommunityTestCase, make_user


def soon(minutes=30):
    return timezone.now() + timedelta(minutes=minutes)


def new_room(user, capacity=3, departs_at=None, **extra):
    return taxi.create_room(user, origin="학교(폴리텍대학)", destination="남춘천역",
                            departs_at=departs_at or soon(), capacity=capacity, note=extra.get("note", ""))


class TaxiServiceTests(CommunityTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cara = make_user("cara_b", cls.dept_b)
        cls.dan = make_user("dan_b", cls.dept_b)

    def test_create_room_makes_host_member_zero(self):
        room = new_room(self.alice)
        host = taxi.active_member(room, self.alice)
        self.assertEqual((host.number, taxi.label(host.number)), (0, "방장"))
        self.assertEqual(taxi.label(2), "익명2")
        self.assertIn(room, taxi.open_rooms(self.bob))

    def test_host_can_have_one_open_room(self):
        new_room(self.alice)
        with self.assertRaises(services.Rejected):
            new_room(self.alice)

    def test_member_of_at_most_two_rooms(self):
        r1, r2, r3 = new_room(self.alice), new_room(self.amy), new_room(self.bob)
        taxi.join(r2, self.cara)
        taxi.join(r3, self.cara)
        with self.assertRaises(services.Rejected):
            taxi.join(r1, self.cara)
        with self.assertRaises(services.Rejected):   # 참여 중 2개면 방장도 못 됨
            new_room(self.cara)

    def test_restricted_user_cannot_create(self):
        self.alice.restricted_until = timezone.now() + timedelta(days=1)
        self.alice.save()
        with self.assertRaises(services.Rejected):
            new_room(self.alice)

    def test_departure_window(self):
        with self.assertRaises(services.Rejected):
            new_room(self.alice, departs_at=timezone.now() - timedelta(minutes=1))
        with self.assertRaises(services.Rejected):
            new_room(self.alice, departs_at=timezone.now() + timedelta(hours=24, minutes=1))

    def test_numbers_rejoin_and_capacity(self):
        room = new_room(self.alice, capacity=3)
        self.assertEqual(taxi.join(room, self.bob).number, 1)
        self.assertEqual(taxi.join(room, self.cara).number, 2)
        with self.assertRaises(services.Rejected):        # 정원 3 = 방장 + 2
            taxi.join(room, self.dan)
        self.assertTrue(TaxiMessage.objects.filter(room=room, kind="system", body__contains="정원").exists())
        taxi.leave(room, self.bob)
        self.assertEqual(taxi.join(room, self.dan).number, 3)
        taxi.leave(room, self.dan)
        self.assertEqual(taxi.join(room, self.bob).number, 1)   # 다시 들어오면 같은 번호

    def test_host_cannot_leave_but_can_pop(self):
        room = new_room(self.alice)
        with self.assertRaises(services.Rejected):
            taxi.leave(room, self.alice)
        with self.assertRaises(services.Rejected):
            taxi.pop(room, self.bob)
        taxi.pop(room, self.alice)
        room.refresh_from_db()
        self.assertEqual((room.status, room.close_reason), (TaxiRoom.CLOSED, "host"))
        self.assertNotIn(room, taxi.open_rooms(self.bob))
        with self.assertRaises(services.Rejected):
            taxi.join(room, self.bob)

    def test_expires_one_hour_after_departure(self):
        room = new_room(self.alice, departs_at=soon(10))
        later = timezone.now() + timedelta(minutes=71)
        self.assertEqual(taxi.close_expired(now=later), 1)
        room.refresh_from_db()
        self.assertEqual((room.status, room.close_reason), (TaxiRoom.CLOSED, "expired"))
        self.assertEqual(list(taxi.open_rooms(self.bob, now=later)), [])

    def test_blocked_host_hidden_and_join_refused(self):
        room = new_room(self.alice)
        Block.objects.create(blocker=self.bob, blocked=self.alice, source_label="택시방")
        self.assertNotIn(room, taxi.open_rooms(self.bob))
        with self.assertRaises(services.Rejected):
            taxi.join(room, self.bob)

    def test_send_requires_member_and_rate_limit(self):
        room = new_room(self.alice)
        with self.assertRaises(services.Rejected):
            taxi.send(room, self.bob, "안녕")
        for i in range(taxi.MESSAGE_LIMIT):
            taxi.send(room, self.alice, f"메시지 {i}")
        with self.assertRaises(services.Rejected):
            taxi.send(room, self.alice, "도배")
        with self.assertRaises(services.Rejected):
            taxi.send(room, self.alice, "   ")

    def test_messages_after(self):
        room = new_room(self.alice)
        first = taxi.send(room, self.alice, "하나")
        taxi.join(room, self.bob)
        taxi.send(room, self.bob, "둘")
        items = taxi.messages_after(room, first.id)
        self.assertEqual([m.body for m in items if m.kind == "text"], ["둘"])

    def test_report_once_and_moderator_hide(self):
        room = new_room(self.alice)
        taxi.join(room, self.bob)
        msg = taxi.send(room, self.alice, "연락처 010...")
        self.assertTrue(taxi.report(self.bob, room, msg, reason="privacy"))
        self.assertFalse(taxi.report(self.bob, room, msg, reason="privacy"))
        self.assertTrue(taxi.report(self.bob, room, reason="spam"))
        taxi.moderate_hide(self.amy, room, "개인정보")
        room.refresh_from_db()
        self.assertEqual((room.status, room.close_reason), (TaxiRoom.HIDDEN, "moderator"))
        self.assertFalse(TaxiReport.objects.filter(room=room, status="open").exists())

    def test_purge_after_seven_days(self):
        old, recent, reported = new_room(self.alice), new_room(self.amy), new_room(self.bob)
        for r in (old, recent, reported):
            taxi.pop(r, r.host)
        now = timezone.now()
        TaxiRoom.objects.filter(pk=old.pk).update(closed_at=now - timedelta(days=8))
        TaxiRoom.objects.filter(pk=recent.pk).update(closed_at=now - timedelta(days=6))
        TaxiRoom.objects.filter(pk=reported.pk).update(closed_at=now - timedelta(days=8))
        TaxiReport.objects.create(reporter=self.alice, room=reported, reason="spam")
        self.assertEqual(taxi.purge_closed(now=now), 1)
        self.assertEqual(set(TaxiRoom.objects.values_list("pk", flat=True)), {recent.pk, reported.pk})


class TaxiConcurrencyTests(TransactionTestCase):
    """마지막 한 자리에 여러 명이 동시에 들어와도 정원을 넘지 않는다(파일 SQLite 필요 → TransactionTestCase)."""

    def test_last_seat_race(self):
        dept = Department.objects.create(name="동시성과", order=99)
        host = make_user("race_host", dept)
        users = [make_user(f"race_{i}", dept) for i in range(5)]
        room = new_room(host, capacity=2)          # 남은 자리 1
        results = []

        def attempt(u):
            try:
                taxi.join(room, u)
                results.append("ok")
            except services.Rejected:
                results.append("full")
            except Exception as exc:              # 잠금 대기 초과 등도 실패로 센다
                results.append(type(exc).__name__)
            finally:
                close_old_connections()

        threads = [threading.Thread(target=attempt, args=(u,)) for u in users]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count("ok"), 1, results)
        self.assertEqual(TaxiMember.objects.filter(room=room, left_at__isnull=True).count(), 2)


class TaxiViewTests(CommunityTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cara = make_user("cara_b", cls.dept_b)

    def form(self, **over):
        now = timezone.localtime() + timedelta(minutes=40)
        data = {"day": "today" if now.date() == timezone.localdate() else "tomorrow", "time": now.strftime("%H:%M"),
                "origin": "학교(폴리텍대학)", "destination": "남춘천역", "capacity": "3", "note": "정문 앞"}
        data.update(over)
        return data

    def test_login_required(self):
        res = self.client.get(reverse("community:taxi_list"))
        self.assertEqual(res.status_code, 302)
        self.assertIn("/accounts/login/", res["Location"])

    def test_create_and_room_page(self):
        self.login(self.alice)
        res = self.client.post(reverse("community:taxi_new"), self.form())
        room = TaxiRoom.objects.get()
        self.assertRedirects(res, reverse("community:taxi_room", args=[room.pk]))
        res = self.client.get(reverse("community:taxi_room", args=[room.pk]))
        self.assertContains(res, "방 터뜨리기")
        self.assertIn("no-store", res["Cache-Control"])
        self.assertNotContains(res, "alice_a")

    def test_create_rejects_past_time(self):
        self.login(self.alice)
        past = (timezone.localtime() - timedelta(minutes=5))
        res = self.client.post(reverse("community:taxi_new"), self.form(
            day="today", time=past.strftime("%H:%M")) if past.date() == timezone.localdate() else self.form(time="99:99"))
        self.assertEqual(res.status_code, 200)
        self.assertFalse(TaxiRoom.objects.exists())

    def test_non_member_sees_join_not_chat(self):
        room = new_room(self.alice)
        taxi.send(room, self.alice, "비밀 약속 장소")
        self.login(self.bob)
        res = self.client.get(reverse("community:taxi_room", args=[room.pk]))
        self.assertContains(res, "참여하기")
        self.assertNotContains(res, "비밀 약속 장소")
        self.assertEqual(self.client.get(reverse("community:taxi_messages", args=[room.pk])).status_code, 403)
        self.client.post(reverse("community:taxi_join", args=[room.pk]))
        data = self.client.get(reverse("community:taxi_messages", args=[room.pk]), {"after": 0}).json()
        self.assertIn("비밀 약속 장소", [m["body"] for m in data["messages"]])
        self.assertEqual(data["me"], "익명1")
        self.client.post(reverse("community:taxi_leave", args=[room.pk]))
        self.assertEqual(self.client.get(reverse("community:taxi_messages", args=[room.pk])).status_code, 403)

    def test_send_and_pop(self):
        room = new_room(self.alice)
        self.login(self.alice)
        self.client.post(reverse("community:taxi_send", args=[room.pk]), {"body": "정문 앞이에요"})
        self.assertTrue(TaxiMessage.objects.filter(body="정문 앞이에요").exists())
        res = self.client.post(reverse("community:taxi_pop", args=[room.pk]))
        self.assertRedirects(res, reverse("community:taxi_list"))
        self.assertEqual(self.client.get(reverse("community:taxi_room", args=[room.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("community:taxi_messages", args=[room.pk])).json()["closed"], True)

    def test_moderator_can_open_closed_room(self):
        room = new_room(self.alice)
        taxi.pop(room, self.alice)
        self.cara.user_permissions.add(Permission.objects.get(codename="moderate"))
        self.login(self.cara)
        self.assertEqual(self.client.get(reverse("community:taxi_manage", args=[room.pk])).status_code, 200)
        self.login(self.bob)
        self.assertEqual(self.client.get(reverse("community:taxi_manage", args=[room.pk])).status_code, 403)

    def test_report_room(self):
        room = new_room(self.alice)
        self.login(self.bob)
        res = self.client.post(reverse("community:taxi_report", args=[room.pk]), {"reason": "spam", "detail": ""})
        self.assertEqual(res.status_code, 302)
        self.assertEqual(TaxiReport.objects.filter(room=room).count(), 1)

    def test_list_and_home_card(self):
        new_room(self.alice)
        self.login(self.bob)
        res = self.client.get(reverse("community:taxi_list"))
        self.assertContains(res, "남춘천역")
        self.assertContains(res, "1/3")
        self.assertContains(self.client.get(reverse("community:home")), reverse("community:taxi_list"))
