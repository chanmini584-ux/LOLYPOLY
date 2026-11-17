"""운영자 처리의 상태 전이 검증(ERR-011, D-072).

숨기기·복구·삭제 확정은 허용된 전이만 처리하고, 거절하면 아무것도 바꾸지 않는다. 판정은 DB 의 현재 값 기준.
지워진(DELETED) 글·댓글은 어떤 운영 처리로도 다시 보이거나 숨김 상태가 되지 않는다.
"""

import threading
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Group
from django.db import OperationalError, close_old_connections
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from community import services, taxi
from accounts.models import Department
from community.models import Board, Comment, ModerationLog, Post, Report, TaxiRoom
from community.tests.helpers import CommunityTestCase, image_file, make_user

ACTIONS = {"hide": services.moderate_hide, "restore": services.moderate_restore, "remove": services.moderate_remove}
ALLOWED = {
    ("visible", "hide"), ("visible", "remove"),
    ("hidden", "restore"), ("hidden", "remove"),
    ("deleted", "remove"),
}
STATES = ("visible", "hidden", "deleted", "purged")
SUCCESS = "처리했어요"


class TransitionTestCase(CommunityTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.mod = make_user("mod_user", cls.dept_b)
        cls.mod.groups.add(Group.objects.get(name="커뮤니티 운영자"))
        cls.reporter = make_user("reporter_x", cls.dept_b)

    def make(self, kind, state, *, report=True):
        """kind 대상 하나를 state 상태로 만든다. report=True 면 처리 전 신고 1건이 붙어 있다."""
        post = Post.objects.create(board=self.board_all, author=self.alice, title="대상 글", body="대상 본문")
        obj = post if kind == "post" else Comment.objects.create(post=post, author=self.amy, body="대상 댓글")
        target = {kind: obj}
        if state == "hidden":
            obj.status, obj.hidden_reason = obj.HIDDEN, "기존 사유"
            obj.save(update_fields=["status", "hidden_reason"])
        elif state == "deleted":                       # 처리 전 신고가 있어 내용이 검토용으로 남음
            Report.objects.create(reporter=self.reporter, reason="spam", **target)
            services.delete_post(obj) if kind == "post" else services.delete_comment(obj)
        elif state == "purged":                        # 신고 없이 작성자가 지움 → 내용 지워짐
            services.delete_post(obj) if kind == "post" else services.delete_comment(obj)
        if report and state != "deleted":
            Report.objects.create(reporter=self.reporter, reason="spam", **target)
        obj = type(obj).objects.get(pk=obj.pk)
        if state in ("deleted", "purged"):
            self.assertEqual(obj.status, obj.DELETED)
            self.assertEqual(bool(obj.purged_at), state == "purged")
        return obj

    def snapshot(self, obj):
        cur = type(obj).objects.get(pk=obj.pk)
        data = {
            "status": cur.status, "body": cur.body, "hidden_reason": cur.hidden_reason,
            "deleted_at": cur.deleted_at, "purged_at": cur.purged_at,
            "reports": list(cur.reports.order_by("pk").values_list("status", "handled_at", "handled_by")),
            "logs": ModerationLog.objects.count(),
        }
        if isinstance(cur, Post):
            data.update(title=cur.title, attachments=cur.attachments.count())
        return data

    def url(self, obj):
        kind = "post" if isinstance(obj, Post) else "comment"
        return f"/community/manage/{kind}/{obj.pk}/"

    def assert_count_matches(self, post_id):
        post = Post.objects.get(pk=post_id)
        self.assertEqual(post.comment_count, Comment.objects.filter(post=post, status=Comment.VISIBLE).count())


class ServiceTransitionTests(TransitionTestCase):
    def test_transition_matrix_allowed(self):
        expect = {
            "hide": (Post.HIDDEN, False, Report.ACTED),
            "restore": (Post.VISIBLE, False, Report.DISMISSED),
            "remove": (Post.DELETED, True, Report.ACTED),
        }
        for kind in ("post", "comment"):
            for state, action in sorted(ALLOWED):
                with self.subTest(kind=kind, state=state, action=action):
                    obj = self.make(kind, state)
                    before = ModerationLog.objects.count()
                    ACTIONS[action](self.mod, obj, "사유 기록")
                    cur = type(obj).objects.get(pk=obj.pk)
                    status, purged, report_status = expect[action]
                    self.assertEqual(cur.status, status)
                    self.assertEqual(bool(cur.purged_at), purged)
                    self.assertEqual(set(cur.reports.values_list("status", flat=True)), {report_status})
                    self.assertEqual(ModerationLog.objects.count(), before + 1)
                    log = ModerationLog.objects.latest("pk")
                    self.assertEqual((log.action, log.reason, log.actor_id), (action, "사유 기록", self.mod.pk))
                    if action == "hide":
                        self.assertEqual(cur.hidden_reason, "사유 기록")
                    if action == "restore":
                        self.assertEqual(cur.hidden_reason, "")
                    if purged:
                        self.assertEqual(cur.body, "")

    def test_hide_without_reason_uses_default_hidden_reason(self):
        obj = self.make("post", "visible")
        services.moderate_hide(self.mod, obj, "")
        obj.refresh_from_db()
        self.assertEqual(obj.hidden_reason, "운영 규칙에 따라 숨겼어요.")

    def test_transition_matrix_rejected_changes_nothing(self):
        rejected = [(s, a) for s in STATES for a in ACTIONS if (s, a) not in ALLOWED]
        self.assertEqual(len(rejected), 7)
        for kind in ("post", "comment"):
            for state, action in rejected:
                with self.subTest(kind=kind, state=state, action=action):
                    obj = self.make(kind, state)
                    before = self.snapshot(obj)
                    with self.assertRaises(services.Rejected) as ctx:
                        ACTIONS[action](self.mod, obj, "사유 기록")
                    self.assertEqual(self.snapshot(obj), before)
                    message = str(ctx.exception)
                    self.assertTrue(message.strip())
                    self.assertNotIn(SUCCESS, message)

    def test_deleted_never_becomes_visible_or_hidden_by_any_action(self):
        sequence = ["hide", "restore", "dismiss", "restrict", "unrestrict", "hide", "restore", "remove", "hide",
                    "restore"]
        for kind in ("post", "comment"):
            for state in ("deleted", "purged"):
                with self.subTest(kind=kind, state=state):
                    obj = self.make(kind, state)
                    post = obj if kind == "post" else obj.post
                    for action in sequence:
                        fresh = type(obj).objects.get(pk=obj.pk)
                        try:
                            if action in ACTIONS:
                                ACTIONS[action](self.mod, fresh, "사유")
                            elif action == "dismiss":
                                services.moderate_dismiss(self.mod, fresh, "사유")
                            elif action == "restrict":
                                services.moderate_restrict(self.mod, fresh.author_id, 3, "사유",
                                                           post=post if kind == "post" else None,
                                                           comment=None if kind == "post" else fresh)
                            else:
                                services.moderate_unrestrict(self.mod, fresh.author_id, "사유",
                                                             post=post if kind == "post" else None,
                                                             comment=None if kind == "post" else fresh)
                        except services.Rejected:
                            pass
                        self.assertEqual(type(obj).objects.get(pk=obj.pk).status, obj.DELETED, action)

    def test_author_deleted_post_never_comes_back(self):
        obj = self.make("post", "deleted")
        with self.assertRaises(services.Rejected):
            services.moderate_hide(self.mod, obj, "숨김")
        with self.assertRaises(services.Rejected):
            services.moderate_restore(self.mod, obj, "복구")
        obj.refresh_from_db()
        self.assertEqual(obj.status, Post.DELETED)
        self.assertEqual(ModerationLog.objects.count(), 0)
        self.login(self.bob)
        self.assertNotContains(self.client.get(f"/community/b/{self.board_all.slug}/"), "대상 글")

    def test_purged_post_never_comes_back(self):
        obj = self.make("post", "purged")
        for action in ("hide", "restore", "remove"):
            with self.assertRaises(services.Rejected):
                ACTIONS[action](self.mod, obj, "사유")
        obj.refresh_from_db()
        self.assertEqual((obj.status, obj.title), (Post.DELETED, "(삭제된 글)"))
        self.login(self.bob)
        self.assertNotContains(self.client.get(f"/community/b/{self.board_all.slug}/"), "(삭제된 글)")

    def test_restore_on_visible_now_rejected(self):
        for kind in ("post", "comment"):
            with self.subTest(kind=kind):
                obj = self.make(kind, "visible")
                before = ModerationLog.objects.count()
                with self.assertRaises(services.Rejected):
                    services.moderate_restore(self.mod, obj, "복구")
                self.assertEqual(ModerationLog.objects.count(), before)

    def test_stale_instance_uses_db_state(self):
        for kind in ("post", "comment"):
            with self.subTest(kind=kind):
                obj = self.make(kind, "visible")
                a, b = type(obj).objects.get(pk=obj.pk), type(obj).objects.get(pk=obj.pk)
                services.moderate_hide(self.mod, a, "첫 처리")
                with self.assertRaises(services.Rejected):
                    services.moderate_hide(self.mod, b, "겹친 처리")        # b 는 메모리에서 아직 VISIBLE
                logs = ModerationLog.objects.filter(action="hide", **{kind: obj})
                self.assertEqual(logs.count(), 1)
                self.assertEqual(type(obj).objects.get(pk=obj.pk).hidden_reason, "첫 처리")
                # 반대 방향: 메모리에서는 HIDDEN, DB 는 VISIBLE → 복구는 거절
                other = self.make(kind, "visible")
                other.status = other.HIDDEN
                with self.assertRaises(services.Rejected):
                    services.moderate_restore(self.mod, other, "복구")
                self.assertEqual(type(other).objects.get(pk=other.pk).status, other.VISIBLE)
                # 메모리에서는 VISIBLE 인데 DB 는 지워진 상태 → 숨기기 거절
                gone = self.make(kind, "visible")
                stale = type(gone).objects.get(pk=gone.pk)
                services.delete_post(gone) if kind == "post" else services.delete_comment(gone)
                with self.assertRaises(services.Rejected):
                    services.moderate_hide(self.mod, stale, "숨김")
                self.assertEqual(type(gone).objects.get(pk=gone.pk).status, gone.DELETED)

    def test_same_object_twice_logs_once(self):
        for kind in ("post", "comment"):
            with self.subTest(kind=kind):
                obj = self.make(kind, "hidden")
                with self.captureOnCommitCallbacks(execute=True):
                    services.moderate_remove(self.mod, obj, "삭제")
                with self.assertRaises(services.Rejected):
                    services.moderate_remove(self.mod, obj, "삭제")
                self.assertEqual(ModerationLog.objects.filter(action="remove", **{kind: obj}).count(), 1)

    def test_successful_call_syncs_caller_object(self):
        obj = self.make("post", "visible")
        services.moderate_hide(self.mod, obj, "숨김")
        self.assertEqual((obj.status, obj.hidden_reason), (Post.HIDDEN, "숨김"))
        services.moderate_remove(self.mod, obj, "삭제")
        self.assertEqual(obj.status, Post.DELETED)
        self.assertIsNotNone(obj.purged_at)
        self.assertEqual(obj.title, "(삭제된 글)")

    def test_remove_deleted_with_content_purges_photos(self):
        post = services.create_post(self.alice, self.board_all, category="free", title="사진 글", body="본문",
                                    uploads=[image_file()])
        att = post.attachments.get()
        paths = [Path(settings.MEDIA_ROOT) / att.path, Path(settings.MEDIA_ROOT) / att.thumb_path]
        Report.objects.create(reporter=self.reporter, post=post, reason="privacy")
        services.delete_post(post)
        self.assertTrue(all(p.exists() for p in paths))                    # 검토용으로 보관
        with self.captureOnCommitCallbacks(execute=True):
            services.moderate_remove(self.mod, Post.objects.get(pk=post.pk), "개인정보")
        post.refresh_from_db()
        self.assertEqual(post.status, Post.DELETED)
        self.assertIsNotNone(post.purged_at)
        self.assertEqual(post.attachments.count(), 0)
        self.assertFalse(any(p.exists() for p in paths))
        self.assertEqual(Report.objects.get(post=post).status, Report.ACTED)

    def test_hidden_reason_kept_when_hide_rejected(self):
        obj = self.make("comment", "hidden")
        with self.assertRaises(services.Rejected):
            services.moderate_hide(self.mod, obj, "새 사유")
        self.assertEqual(Comment.objects.get(pk=obj.pk).hidden_reason, "기존 사유")


class CommentCountTests(TransitionTestCase):
    def test_comment_count_after_allowed_actions(self):
        post = Post.objects.create(board=self.board_all, author=self.alice, title="댓글 글", body="본문")
        first = services.add_comment(self.amy, post, "첫 댓글")
        services.add_comment(self.bob, post, "둘째 댓글")
        self.assertEqual(Post.objects.get(pk=post.pk).comment_count, 2)
        services.moderate_hide(self.mod, first, "숨김")
        self.assert_count_matches(post.pk)
        self.assertEqual(Post.objects.get(pk=post.pk).comment_count, 1)
        services.moderate_restore(self.mod, first, "복구")
        self.assertEqual(Post.objects.get(pk=post.pk).comment_count, 2)
        services.moderate_remove(self.mod, first, "삭제")
        self.assertEqual(Post.objects.get(pk=post.pk).comment_count, 1)
        self.assert_count_matches(post.pk)

    def test_comment_count_after_rejected_action(self):
        for state, action in (("visible", "restore"), ("hidden", "hide"), ("deleted", "hide"), ("purged", "remove")):
            with self.subTest(state=state, action=action):
                obj = self.make("comment", state)                # objects.create 라 comment_count 는 어긋나 있을 수 있음
                Comment.objects.create(post=obj.post, author=self.bob, body="다른 공개 댓글")
                Post.objects.filter(pk=obj.post_id).update(comment_count=7)
                before = self.snapshot(obj)
                with self.assertRaises(services.Rejected):
                    ACTIONS[action](self.mod, obj, "사유")
                self.assertEqual(self.snapshot(obj), before)
                self.assert_count_matches(obj.post_id)

    def test_comment_count_after_dismiss_and_restrict_on_comment(self):
        self.login(self.mod)
        for action, extra in (("dismiss", {}), ("restrict", {"days": "3"}), ("unrestrict", {})):
            with self.subTest(action=action):
                obj = self.make("comment", "visible")
                Post.objects.filter(pk=obj.post_id).update(comment_count=9)
                res = self.client.post(self.url(obj), {"action": action, "reason": "확인", **extra})
                self.assertEqual(res.status_code, 302)
                self.assert_count_matches(obj.post_id)

    def test_comment_count_after_screen_rejection(self):
        obj = self.make("comment", "visible")
        Post.objects.filter(pk=obj.post_id).update(comment_count=5)
        self.login(self.mod)
        res = self.client.post(self.url(obj), {"action": "restore", "reason": "복구"})
        self.assertEqual(res.status_code, 200)
        self.assert_count_matches(obj.post_id)


class ScreenTransitionTests(TransitionTestCase):
    def values(self, html):
        return {v for v in ("hide", "restore", "remove", "dismiss", "restrict", "unrestrict")
                if f'value="{v}"' in html}

    def test_screen_choices_follow_state(self):
        expect = {"visible": {"hide", "remove"}, "hidden": {"restore", "remove"}, "deleted": {"remove"},
                  "purged": set()}
        self.login(self.mod)
        for kind in ("post", "comment"):
            for state in STATES:
                with self.subTest(kind=kind, state=state):
                    obj = self.make(kind, state)
                    res = self.client.get(self.url(obj))
                    self.assertEqual(res.status_code, 200)
                    self.assertEqual(self.values(res.content.decode()),
                                     expect[state] | {"dismiss", "restrict", "unrestrict"})

    def test_screen_rejection_shows_reason_without_success(self):
        self.login(self.mod)
        for kind in ("post", "comment"):
            with self.subTest(kind=kind):
                obj = self.make(kind, "purged")
                before = self.snapshot(obj)
                for follow in (False, True):
                    res = self.client.post(self.url(obj), {"action": "restore", "reason": "복구 시도"}, follow=follow)
                    self.assertEqual(res.status_code, 200)
                    self.assertContains(res, "내용이 이미 지워진")
                    self.assertNotContains(res, SUCCESS)
                self.assertEqual(self.snapshot(obj), before)

    def test_screen_rejects_hide_restore_on_author_deleted(self):
        self.login(self.mod)
        for kind in ("post", "comment"):
            with self.subTest(kind=kind):
                obj = self.make(kind, "deleted")
                before = self.snapshot(obj)
                for action in ("hide", "restore"):
                    res = self.client.post(self.url(obj), {"action": action, "reason": "시도"})
                    self.assertEqual(res.status_code, 200)
                    self.assertContains(res, "지워진")
                    self.assertNotContains(res, SUCCESS)
                self.assertEqual(self.snapshot(obj), before)
                self.assertEqual(type(obj).objects.get(pk=obj.pk).status, obj.DELETED)

    def test_screen_duplicate_submit_logs_once(self):
        self.login(self.mod)
        for kind in ("post", "comment"):
            with self.subTest(kind=kind):
                obj = self.make(kind, "visible")
                data = {"action": "hide", "reason": "비방"}
                self.assertEqual(self.client.post(self.url(obj), data).status_code, 302)
                res = self.client.post(self.url(obj), data)
                self.assertEqual(res.status_code, 200)
                self.assertContains(res, "이미 숨긴")
                self.assertContains(res, "status-bar--error")
                self.assertNotContains(res, SUCCESS)
                self.assertEqual(ModerationLog.objects.filter(action="hide", **{kind: obj}).count(), 1)
                later = self.client.get(self.url(obj))           # 지난 알림이 다음 화면에 다시 나오지 않음
                self.assertNotContains(later, SUCCESS)
                self.assertNotContains(later, "이미 숨긴")

    def test_screen_hidden_choice_post_is_rechecked(self):
        self.login(self.mod)
        obj = self.make("post", "visible")
        self.assertNotIn('value="restore"', self.client.get(self.url(obj)).content.decode())
        res = self.client.post(self.url(obj), {"action": "restore", "reason": "복구"})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "복구할 수 없어요")
        self.assertNotContains(res, SUCCESS)
        self.assertEqual(Post.objects.get(pk=obj.pk).status, Post.VISIBLE)
        self.assertEqual(ModerationLog.objects.count(), 0)

    def test_screen_after_rejection_shows_current_choices(self):
        self.login(self.mod)
        obj = self.make("post", "purged")
        res = self.client.post(self.url(obj), {"action": "hide", "reason": "숨김"})
        self.assertEqual(self.values(res.content.decode()), {"dismiss", "restrict", "unrestrict"})
        # 화면을 연 뒤 다른 운영자가 먼저 숨긴 경우: 거절 화면은 지금 상태(HIDDEN) 기준 선택지
        other = self.make("comment", "visible")
        services.moderate_hide(make_user("mod_other"), Comment.objects.get(pk=other.pk), "먼저 숨김")
        res = self.client.post(self.url(other), {"action": "hide", "reason": "숨김"})
        self.assertEqual(self.values(res.content.decode()), {"restore", "remove", "dismiss", "restrict", "unrestrict"})

    def test_screen_success_still_redirects_with_message(self):
        self.login(self.mod)
        obj = self.make("post", "visible")
        res = self.client.post(self.url(obj), {"action": "hide", "reason": "비방"}, follow=True)
        self.assertContains(res, SUCCESS)
        self.assertEqual(Post.objects.get(pk=obj.pk).status, Post.HIDDEN)


class ExistingBehaviorTests(TransitionTestCase):
    def test_dismiss_restrict_unrestrict_allowed_in_any_state(self):
        self.login(self.mod)
        for kind in ("post", "comment"):
            for state in ("deleted", "purged"):
                for action, extra in (("restrict", {"days": "2"}), ("unrestrict", {}), ("dismiss", {})):
                    with self.subTest(kind=kind, state=state, action=action):
                        obj = self.make(kind, state)
                        before = ModerationLog.objects.count()
                        res = self.client.post(self.url(obj), {"action": action, "reason": "확인", **extra})
                        self.assertEqual(res.status_code, 302)
                        self.assertEqual(ModerationLog.objects.count(), before + 1)
                        cur = type(obj).objects.get(pk=obj.pk)
                        self.assertEqual(cur.status, cur.DELETED)
                        if action == "dismiss":                  # 검토가 끝났으니 남은 내용도 지운다(기존 동작)
                            self.assertIsNotNone(cur.purged_at)
                            self.assertEqual(set(cur.reports.values_list("status", flat=True)), {Report.DISMISSED})

    def test_taxi_manage_still_works(self):
        room = taxi.create_room(self.alice, origin="학교(폴리텍대학)", destination="남춘천역",
                                departs_at=timezone.now() + timedelta(minutes=30), capacity=3, note="")
        self.login(self.mod)
        url = reverse("community:taxi_manage", args=[room.pk])
        html = self.client.get(url).content.decode()
        self.assertEqual({v for v in ("hide", "restore", "remove", "dismiss", "restrict", "unrestrict")
                          if f'value="{v}"' in html}, {"hide", "dismiss", "restrict"})
        res = self.client.post(url, {"action": "hide", "reason": "부적절한 방"}, follow=True)
        self.assertContains(res, SUCCESS)
        room.refresh_from_db()
        self.assertEqual(room.status, TaxiRoom.HIDDEN)


class ConcurrentModerationTests(TransactionTestCase):
    """같은 처리가 동시에 겹쳐 들어와도 하나만 처리되고 운영 기록은 1건(파일·공유 SQLite → TransactionTestCase)."""

    def test_parallel_hide_logs_once(self):
        dept = Department.objects.create(name="동시처리과", order=98)
        author = make_user("race_author", dept)
        mod = make_user("race_mod", dept)
        post = Post.objects.create(board=Board.objects.get(department=dept), author=author, title="겹친 글",
                                   body="본문")
        stale = [Post.objects.get(pk=post.pk) for _ in range(5)]     # 모두 VISIBLE 로 읽어 둔 낡은 객체
        results = []

        def attempt(obj):
            # 테스트 DB(공유 캐시 메모리 SQLite)는 잠금을 기다리지 않고 'table is locked' 를 바로 낸다.
            # 운영 DB 의 잠금 대기(timeout)를 흉내 내어 다시 시도한다. 다시 시도해도 obj 는 처음 읽은 낡은 값이다.
            try:
                for _ in range(200):
                    try:
                        services.moderate_hide(mod, obj, "동시 숨김")
                        results.append("ok")
                        return
                    except services.Rejected:
                        results.append("rejected")
                        return
                    except OperationalError as exc:
                        if "locked" not in str(exc):
                            raise
                        time.sleep(0.01)
                results.append("timeout")
            except Exception as exc:                    # 예상 밖 오류도 결과로 남겨 실패로 보이게 한다
                results.append(f"{type(exc).__name__}: {exc}")
            finally:
                close_old_connections()

        threads = [threading.Thread(target=attempt, args=(obj,)) for obj in stale]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results), ["ok"] + ["rejected"] * 4, results)
        self.assertEqual(ModerationLog.objects.filter(post=post, action="hide").count(), 1)
        self.assertEqual(Post.objects.get(pk=post.pk).status, Post.HIDDEN)
