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

from .helpers import PASSWORD, CommunityTestCase, make_user


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


class TaxiPurgeCommandTests(CommunityTestCase):
    def test_purge_command_removes_old_rooms(self):
        import io

        from django.core.management import call_command

        room = new_room(self.alice)
        taxi.pop(room, self.alice)
        TaxiRoom.objects.filter(pk=room.pk).update(closed_at=timezone.now() - timedelta(days=8))
        out = io.StringIO()
        call_command("purge_community", stdout=out)
        self.assertIn("택시방 1개", out.getvalue())
        self.assertFalse(TaxiRoom.objects.exists())
        self.assertFalse(TaxiMessage.objects.exists())


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

    def test_time_input_has_accessible_name(self):
        self.login(self.alice)
        self.assertContains(self.client.get(reverse("community:taxi_new")), 'aria-label="출발 시각(시:분)"')

    def test_create_rejects_past_time(self):
        self.login(self.alice)
        past = (timezone.localtime() - timedelta(minutes=5))
        res = self.client.post(reverse("community:taxi_new"), self.form(
            day="today", time=past.strftime("%H:%M")) if past.date() == timezone.localdate() else self.form(time="99:99"))
        self.assertEqual(res.status_code, 400)      # 입력 오류 → 폼 다시 보여 줌
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

    def test_message_poll_does_not_write_when_nothing_expired(self):
        """3초 확인은 닫을 방이 없으면 읽기만 한다(ERR-013). 시간이 지난 방이 있으면 그때만 닫는다."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        room = new_room(self.alice)
        self.login(self.alice)
        with CaptureQueriesContext(connection) as ctx:
            res = self.client.get(reverse("community:taxi_messages", args=[room.pk]), {"after": 0})
        self.assertEqual(res.json()["closed"], False)
        writes = [q["sql"] for q in ctx if q["sql"].lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE"))]
        self.assertEqual(writes, [])
        TaxiRoom.objects.filter(pk=room.pk).update(departs_at=timezone.now() - timedelta(hours=2))
        self.assertEqual(self.client.get(reverse("community:taxi_messages", args=[room.pk])).json(), {"closed": True})
        room.refresh_from_db()
        self.assertEqual((room.status, room.close_reason), (TaxiRoom.CLOSED, "expired"))

    def test_list_and_home_card(self):
        new_room(self.alice)
        self.login(self.bob)
        res = self.client.get(reverse("community:taxi_list"))
        self.assertContains(res, "남춘천역")
        self.assertContains(res, "1/3")
        self.assertContains(self.client.get(reverse("community:home")), reverse("community:taxi_list"))


class TaxiWithdrawTests(CommunityTestCase):
    """계정 탈퇴(POST /accounts/withdraw/) 때 택시방 정리(ERR-010)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cara = make_user("cara_b", cls.dept_b)
        cls.mod = make_user("mod_b", cls.dept_b)
        cls.mod.user_permissions.add(Permission.objects.get(codename="moderate"))

    def withdraw(self, user):
        self.login(user)
        res = self.client.post(reverse("accounts:withdraw"), {"password": PASSWORD, "confirm": "on"})
        self.assertEqual(res.status_code, 200)
        self.assertFalse(type(user).objects.get(pk=user.pk).is_active)

    def bodies(self, room, user):
        """user 가 보는 방 화면 HTML 과 메시지 JSON 본문 목록."""
        self.login(user)
        html = self.client.get(reverse("community:taxi_room", args=[room.pk]))
        self.assertEqual(html.status_code, 200)
        data = self.client.get(reverse("community:taxi_messages", args=[room.pk]), {"after": 0}).json()
        return html, [m["body"] for m in data["messages"]]

    def test_host_withdraw_closes_open_room(self):
        room = new_room(self.alice)
        taxi.join(room, self.bob)
        self.withdraw(self.alice)
        room.refresh_from_db()
        self.assertEqual(room.status, TaxiRoom.CLOSED)
        self.assertIsNotNone(room.closed_at)
        self.assertNotIn(room, taxi.open_rooms(self.bob))
        self.login(self.bob)
        self.assertEqual(self.client.get(reverse("community:taxi_room", args=[room.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("community:taxi_messages", args=[room.pk])).json(), {"closed": True})
        self.assertNotContains(self.client.get(reverse("community:taxi_list")), "남춘천역")
        self.assertFalse(TaxiMessage.objects.filter(room=room, body__contains="나갔어요").exists())

    def test_withdraw_leaves_closed_and_hidden_rooms_untouched(self):
        closed, hidden = new_room(self.alice), new_room(self.amy)
        taxi.pop(closed, self.alice)
        TaxiRoom.objects.filter(pk=closed.pk).update(closed_at=timezone.now() - timedelta(days=2))
        taxi.moderate_hide(self.mod, hidden, "테스트")
        before = list(TaxiRoom.objects.order_by("pk").values_list("pk", "status", "close_reason", "closed_at"))
        self.withdraw(self.alice)
        self.withdraw(self.amy)
        after = list(TaxiRoom.objects.order_by("pk").values_list("pk", "status", "close_reason", "closed_at"))
        self.assertEqual(before, after)

    def test_member_withdraw_frees_seat_and_posts_leave_notice(self):
        room = new_room(self.alice, capacity=2)
        taxi.join(room, self.bob)
        with self.assertRaises(services.Rejected):
            taxi.join(room, self.cara)
        self.withdraw(self.bob)
        room.refresh_from_db()
        self.assertEqual(room.status, TaxiRoom.OPEN)
        self.assertEqual(taxi.head_count(room), 1)
        self.assertIsNone(taxi.active_member(room, self.bob))
        self.assertTrue(TaxiMember.objects.filter(room=room, user=self.bob).exists())   # 행은 남김(신고 보존)
        self.assertEqual(TaxiMessage.objects.filter(room=room, kind="system", body="익명1님이 나갔어요").count(), 1)
        self.assertEqual(taxi.join(room, self.cara).number, 2)

    def test_host_who_also_joined_another_room(self):
        mine, other = new_room(self.alice), new_room(self.bob)
        taxi.join(other, self.alice)
        self.assertEqual(taxi.head_count(other), 2)
        self.withdraw(self.alice)
        mine.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(mine.status, TaxiRoom.CLOSED)
        self.assertEqual(other.status, TaxiRoom.OPEN)
        self.assertEqual(taxi.head_count(other), 1)
        self.assertEqual(TaxiMessage.objects.filter(room=other, body="익명1님이 나갔어요").count(), 1)
        self.assertFalse(TaxiMessage.objects.filter(room=mine, body__contains="나갔어요").exists())
        self.assertFalse(TaxiMember.objects.filter(user=self.alice, left_at__isnull=True).exists())

    def test_withdrawn_member_messages_hidden_from_room_and_json(self):
        room = new_room(self.alice)
        taxi.join(room, self.bob)
        taxi.send(room, self.bob, "밥의비밀메시지")
        taxi.send(room, self.alice, "방장메시지")
        self.withdraw(self.bob)
        html, bodies = self.bodies(room, self.alice)
        self.assertNotContains(html, "밥의비밀메시지")
        self.assertContains(html, "방장메시지")
        self.assertNotIn("밥의비밀메시지", bodies)
        self.assertIn("방장메시지", bodies)
        self.assertTrue(any("방이 만들어졌어요" in b for b in bodies))     # 시스템 안내는 남는다
        self.assertIn("익명1님이 나갔어요", bodies)

    def test_unreported_messages_deleted_in_all_rooms(self):
        open_room, closed_room = new_room(self.alice), new_room(self.amy)
        taxi.join(open_room, self.bob)
        taxi.join(closed_room, self.bob)
        taxi.send(open_room, self.bob, "열린방밥말")
        taxi.send(closed_room, self.bob, "닫힌방밥말")
        taxi.send(open_room, self.alice, "알리스말")
        taxi.pop(closed_room, self.amy)
        system_before = TaxiMessage.objects.filter(room=closed_room, kind="system").count()
        self.withdraw(self.bob)
        self.assertFalse(TaxiMessage.objects.filter(member__user=self.bob, kind="text").exists())
        self.assertFalse(TaxiMessage.objects.filter(body__in=["열린방밥말", "닫힌방밥말"]).exists())
        self.assertTrue(TaxiMessage.objects.filter(body="알리스말").exists())
        self.assertEqual(TaxiMessage.objects.filter(room=closed_room, kind="system").count(), system_before)
        self.assertIsNotNone(TaxiMember.objects.get(room=closed_room, user=self.bob).left_at)

    def test_reported_message_kept_for_moderator_hidden_for_students(self):
        room = new_room(self.alice, capacity=4)
        taxi.join(room, self.bob)
        taxi.join(room, self.cara)
        m1 = taxi.send(room, self.bob, "신고된첫째말")
        m2 = taxi.send(room, self.bob, "처리된둘째말")
        m3 = taxi.send(room, self.bob, "신고없는셋째말")
        taxi.report(self.cara, room, m2, reason="spam")
        taxi.dismiss_reports(self.mod, room, "문제없음")
        taxi.report(self.alice, room, m1, reason="privacy")
        taxi.report(self.cara, room, reason="spam")
        reports_before = list(TaxiReport.objects.order_by("pk").values_list("pk", "status"))
        self.withdraw(self.bob)
        self.assertEqual(list(TaxiReport.objects.order_by("pk").values_list("pk", "status")), reports_before)
        self.assertEqual(TaxiMessage.objects.get(pk=m1.pk).body, "신고된첫째말")
        self.assertEqual(TaxiMessage.objects.get(pk=m2.pk).body, "처리된둘째말")
        self.assertFalse(TaxiMessage.objects.filter(pk=m3.pk).exists())
        self.login(self.mod)
        res = self.client.get(reverse("community:taxi_manage", args=[room.pk]))
        self.assertContains(res, "신고된첫째말")
        self.assertContains(res, "처리된둘째말")
        html, bodies = self.bodies(room, self.alice)
        for text in ("신고된첫째말", "처리된둘째말", "신고없는셋째말"):
            self.assertNotContains(html, text)
            self.assertNotIn(text, bodies)
        self.assertEqual(self.client.get(reverse("community:taxi_message_report", args=[m1.pk])).status_code, 404)

    def test_reports_filed_by_withdrawn_user_are_kept(self):
        room = new_room(self.alice)
        taxi.join(room, self.bob)
        msg = taxi.send(room, self.alice, "알리스말")
        taxi.report(self.bob, room, reason="spam")
        taxi.report(self.bob, room, msg, reason="abuse")
        self.withdraw(self.bob)
        kept = TaxiReport.objects.filter(room=room)
        self.assertEqual(kept.count(), 2)
        self.assertEqual(set(kept.values_list("reporter_id", "status")), {(self.bob.pk, "open")})

    def test_host_withdraw_room_follows_seven_day_purge(self):
        reported, plain = new_room(self.alice), new_room(self.amy)
        taxi.join(reported, self.bob)
        taxi.send(reported, self.bob, "밥말")
        taxi.report(self.bob, reported, reason="spam")
        self.withdraw(self.alice)
        self.withdraw(self.amy)
        TaxiRoom.objects.update(closed_at=timezone.now() - timedelta(days=8))
        self.assertEqual(taxi.purge_closed(), 1)
        self.assertEqual(list(TaxiRoom.objects.values_list("pk", flat=True)), [reported.pk])

    def test_withdraw_rolls_back_taxi_cleanup_on_failure(self):
        hosted = new_room(self.alice)
        joined = new_room(self.amy)
        taxi.join(hosted, self.bob)
        taxi.join(joined, self.alice)
        taxi.send(joined, self.alice, "롤백될말")
        self.login(self.alice)
        User = type(self.alice)
        with patch.object(taxi, "purge_user", wraps=taxi.purge_user) as spy, \
                patch.object(User, "save", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse("accounts:withdraw"), {"password": PASSWORD, "confirm": "on"})
        self.assertEqual(spy.call_count, 1)             # 택시 정리가 실행된 뒤에 실패했다
        self.assertTrue(User.objects.get(pk=self.alice.pk).is_active)
        hosted.refresh_from_db()
        self.assertEqual(hosted.status, TaxiRoom.OPEN)
        self.assertIsNotNone(taxi.active_member(joined, self.alice))
        self.assertTrue(TaxiMessage.objects.filter(body="롤백될말").exists())
        self.assertFalse(TaxiMessage.objects.filter(body__contains="나갔어요").exists())

    def test_withdraw_without_taxi_activity_still_works(self):
        room = new_room(self.alice)
        taxi.join(room, self.bob)
        self.withdraw(self.amy)
        room.refresh_from_db()
        self.assertEqual(room.status, TaxiRoom.OPEN)
        self.assertEqual(taxi.head_count(room), 2)
        self.assertEqual(TaxiMessage.objects.filter(room=room).count(), 2)   # 만들어짐 + 들어옴

    def test_admin_deactivated_user_messages_still_visible(self):
        """탈퇴가 아니라 관리자가 끈 계정(withdrawn_at 없음)의 대화는 숨기지 않는다."""
        room = new_room(self.alice)
        taxi.join(room, self.bob)
        taxi.send(room, self.bob, "비활성화된밥말")
        type(self.bob).objects.filter(pk=self.bob.pk).update(is_active=False)
        self.assertIn("비활성화된밥말", [m.body for m in taxi.messages_after(room)])
