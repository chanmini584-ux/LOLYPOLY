"""신고·자동 임시 숨김·운영자 도구·운영 기록, 숨김 글의 노출 차단."""

from django.contrib.auth.models import Group
from django.test import override_settings

from community.models import Comment, ModerationLog, Post, Report
from community.tests.helpers import CommunityTestCase, make_user


class ReportTests(CommunityTestCase):
    def setUp(self):
        super().setUp()
        self.post = Post.objects.create(board=self.board_all, author=self.alice, title="신고될 글", body="본문")
        self.comment = Comment.objects.create(post=self.post, author=self.alice, body="신고될 댓글")

    def test_report_once_per_account_per_target(self):
        self.login(self.bob)
        url = f"/community/report/post/{self.post.pk}/"
        self.assertContains(self.client.get(url), "신고 이유")
        self.client.post(url, {"reason": "harass", "detail": "특정인 비방"})
        res = self.client.post(url, {"reason": "spam"}, follow=True)
        self.assertContains(res, "이미 신고한")
        self.assertEqual(Report.objects.count(), 1)
        self.client.post(f"/community/report/comment/{self.comment.pk}/", {"reason": "spam"})
        self.assertEqual(Report.objects.count(), 2)
        self.assertEqual(self.client.post(url, {"reason": "not-a-reason"}).status_code, 200)   # 엉뚱한 이유는 거절
        self.assertEqual(Report.objects.count(), 2)

    def test_cannot_report_own_content(self):
        self.login(self.alice)
        self.client.post(f"/community/report/post/{self.post.pk}/", {"reason": "spam"})
        self.assertEqual(Report.objects.count(), 0)

    def test_reports_alone_never_restrict_the_author(self):
        for i in range(10):
            self.login(make_user(f"reporter_{i}"))
            self.client.post(f"/community/report/post/{self.post.pk}/", {"reason": "spam"})
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.is_restricted)
        self.assertTrue(self.alice.is_active)

    @override_settings(COMMUNITY_REPORT_AUTOHIDE=3)
    def test_auto_hide_is_temporary_and_restorable(self):
        for i in range(3):
            self.login(make_user(f"reporter_{i}"))
            self.client.post(f"/community/report/post/{self.post.pk}/", {"reason": "privacy"})
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, Post.HIDDEN)
        self.assertEqual(ModerationLog.objects.get().action, "autohide")
        self.login(self.bob)
        self.assertEqual(self.client.get(f"/community/p/{self.post.pk}/").status_code, 404)
        self.assertNotContains(self.client.get("/community/b/all/"), "신고될 글")
        self.assertNotContains(self.client.get("/community/search/?q=신고될"), "신고될 글</span>")
        # 글쓴이는 숨겨졌다는 안내와 자기 글을 본다
        self.login(self.alice)
        res = self.client.get(f"/community/p/{self.post.pk}/")
        self.assertContains(res, "내가 쓴 글이에요", status_code=404)
        # 운영자가 문제없다고 보면 다시 보이게 한다
        mod = make_user("mod_user")
        mod.groups.add(Group.objects.get(name="커뮤니티 운영자"))
        self.login(mod)
        self.client.post(f"/community/manage/post/{self.post.pk}/", {"action": "restore", "reason": "확인 결과 문제없음"})
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, Post.VISIBLE)
        self.assertEqual(Report.objects.filter(status=Report.OPEN).count(), 0)

    @override_settings(COMMUNITY_REPORT_AUTOHIDE=0)
    def test_auto_hide_can_be_turned_off(self):
        for i in range(8):
            self.login(make_user(f"reporter_{i}"))
            self.client.post(f"/community/report/post/{self.post.pk}/", {"reason": "privacy"})
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, Post.VISIBLE)


class ModeratorToolTests(CommunityTestCase):
    def setUp(self):
        super().setUp()
        self.mod = make_user("mod_user", self.dept_b)
        self.mod.groups.add(Group.objects.get(name="커뮤니티 운영자"))
        self.post = Post.objects.create(board=self.board_a, author=self.alice, title="문제 글", body="문제 본문")
        self.comment = Comment.objects.create(post=self.post, author=self.amy, body="문제 댓글")
        Report.objects.create(reporter=self.bob, post=self.post, reason="harass", detail="비방")
        Report.objects.create(reporter=self.bob, comment=self.comment, reason="spam")

    def test_only_moderators_reach_manage_urls(self):
        urls = ["/community/manage/", f"/community/manage/post/{self.post.pk}/",
                f"/community/manage/comment/{self.comment.pk}/"]
        for user in (self.alice, self.bob):
            self.login(user)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 403, url)
            res = self.client.post(urls[1], {"action": "hide", "reason": "직접 요청"})
            self.assertEqual(res.status_code, 403)
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, Post.VISIBLE)
        self.assertEqual(ModerationLog.objects.count(), 0)
        self.assertNotContains(self.client.get("/my/"), "/community/manage/")
        # 운영자 권한은 신고 처리뿐: 관리자(admin) 화면에는 못 들어간다
        self.login(self.mod)
        self.assertEqual(self.client.get("/admin/").status_code, 302)
        self.assertContains(self.client.get("/my/"), "/community/manage/")

    def test_review_screen_shows_content_without_identity(self):
        self.login(self.mod)
        listing = self.client.get("/community/manage/")
        self.assertContains(listing, "문제 글")
        self.assertContains(listing, "문제 댓글")
        html = self.client.get(f"/community/manage/post/{self.post.pk}/").content.decode()
        self.assertIn("문제 본문", html)
        self.assertIn("비방", html)
        for secret in ("alice_a", "bob_b", "amy_a"):
            self.assertNotIn(secret, html)

    def test_hide_restore_remove_and_logs(self):
        self.login(self.mod)
        url = f"/community/manage/post/{self.post.pk}/"
        self.assertEqual(self.client.post(url, {"action": "hide"}).status_code, 200)       # 사유 없이는 처리 안 됨
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, Post.VISIBLE)
        self.client.post(url, {"action": "hide", "reason": "특정인 비방"})
        self.post.refresh_from_db()
        self.assertEqual((self.post.status, self.post.hidden_reason), (Post.HIDDEN, "특정인 비방"))
        self.assertEqual(Report.objects.get(post=self.post).status, Report.ACTED)
        self.client.post(url, {"action": "restore", "reason": "이의 제기 확인"})
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, Post.VISIBLE)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, {"action": "remove", "reason": "반복 위반"})
        self.post.refresh_from_db()
        self.assertEqual((self.post.status, self.post.body), (Post.DELETED, ""))
        self.assertEqual(list(ModerationLog.objects.order_by("created_at").values_list("action", "reason")),
                         [("hide", "특정인 비방"), ("restore", "이의 제기 확인"), ("remove", "반복 위반")])

    def test_hidden_comment_keeps_thread_and_updates_count(self):
        self.login(self.mod)
        self.client.post(f"/community/manage/comment/{self.comment.pk}/", {"action": "hide", "reason": "도배"})
        self.post.refresh_from_db()
        self.assertEqual(self.post.comment_count, 0)
        Comment.objects.create(post=self.post, author=self.alice, body="남은 답글", parent=self.comment)
        self.login(self.alice)
        res = self.client.get(f"/community/p/{self.post.pk}/")
        self.assertContains(res, "숨겨진 댓글이에요")
        self.assertNotContains(res, "문제 댓글")
        self.assertNotContains(self.client.get("/community/me/comments/"), "문제 댓글")

    def test_restrict_and_unrestrict_account_with_reason(self):
        self.login(self.mod)
        url = f"/community/manage/post/{self.post.pk}/"
        self.assertEqual(self.client.post(url, {"action": "restrict", "reason": "도배", "days": ""}).status_code, 200)
        self.client.post(url, {"action": "restrict", "reason": "반복 도배", "days": "7"})
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.is_restricted)
        self.assertEqual(self.write(self.alice, self.board_a, title="제한 중").status_code, 403)
        self.login(self.mod)
        self.assertContains(self.client.get(url), "이용 제한 중")
        self.client.post(url, {"action": "unrestrict", "reason": "소명 확인"})
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.is_restricted)
        self.assertEqual(self.write(self.alice, self.board_a, title="해제 후").status_code, 302)
        log = ModerationLog.objects.filter(action__in=["restrict", "unrestrict"]).order_by("created_at")
        self.assertEqual([entry.action for entry in log], ["restrict", "unrestrict"])
        self.assertTrue(all(entry.reason for entry in log))

    def test_dismiss_closes_reports_without_touching_content(self):
        self.login(self.mod)
        self.client.post(f"/community/manage/post/{self.post.pk}/", {"action": "dismiss", "reason": "문제없음"})
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, Post.VISIBLE)
        self.assertEqual(Report.objects.get(post=self.post).status, Report.DISMISSED)

    def test_superuser_manages_departments_and_user_department_in_admin(self):
        from accounts.models import Department

        root = make_user("root_admin", is_staff=True, is_superuser=True)
        self.login(root)
        self.assertEqual(self.client.get("/admin/accounts/department/").status_code, 200)
        self.assertEqual(self.client.get(f"/admin/accounts/user/{self.alice.pk}/change/").status_code, 200)
        self.client.post("/admin/accounts/department/add/", {"name": "테스트C과", "is_active": "on", "order": "92", "note": ""})
        dept = Department.objects.get(name="테스트C과")
        self.assertEqual(dept.board.slug, f"d{dept.pk}")                   # 학과를 만들면 게시판이 함께 생긴다
        self.assertContains(self.client.get("/community/"), "테스트C과")
