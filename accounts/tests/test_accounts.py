"""가입·로그인·로그아웃·비밀번호 변경·탈퇴·이용 제한·로그인 시도 제한."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Department
from community.models import Comment, Post
from community.tests.helpers import PASSWORD, CommunityTestCase, make_user

User = get_user_model()


class SignupTests(TestCase):
    def setUp(self):
        cache.clear()
        self.dept = Department.objects.create(name="테스트A과")
        self.url = reverse("accounts:signup")

    def data(self, **over):
        return {"username": "newbie_01", "password1": PASSWORD, "password2": PASSWORD,
                "department": self.dept.pk, "agree": "on", **over}

    def test_signup_logs_in_and_stores_only_id_password_department(self):
        res = self.client.post(self.url, self.data())
        self.assertRedirects(res, reverse("community:home"))
        user = User.objects.get(username="newbie_01")
        self.assertEqual(user.department, self.dept)
        self.assertEqual((user.email, user.first_name, user.last_name), ("", "", ""))
        self.assertTrue(user.check_password(PASSWORD))
        self.assertNotIn(PASSWORD, user.password)                      # 해시로만 저장
        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_form_explains_self_declared_department_and_no_recovery(self):
        res = self.client.get(self.url)
        self.assertContains(res, "재학·학과 인증이 아니에요")
        self.assertContains(res, "스스로 되찾을 수 없어요")
        self.assertContains(res, "완전한 익명은 아니에요")
        self.assertNotContains(res, 'name="email"')
        self.assertNotContains(res, "인증 완료")

    def test_rejects_bad_input(self):
        cases = [
            self.data(username="ab"), self.data(username="한글아이디"), self.data(username="Has Space"),
            self.data(password2="different-pass-1!"), self.data(password1="12345678", password2="12345678"),
            self.data(department=""), self.data(department="99999"), {k: v for k, v in self.data().items() if k != "agree"},
        ]
        for data in cases:
            self.assertEqual(self.client.post(self.url, data).status_code, 200, data)
        self.assertEqual(User.objects.count(), 0)

    def test_username_is_case_insensitively_unique(self):
        make_user("taken_name")
        self.client.post(self.url, self.data(username="Taken_Name"))
        self.assertEqual(User.objects.count(), 1)

    def test_inactive_department_cannot_be_chosen(self):
        closed = Department.objects.create(name="닫힌과", is_active=False)
        self.assertNotContains(self.client.get(self.url), "닫힌과")
        self.client.post(self.url, self.data(department=closed.pk))
        self.assertEqual(User.objects.count(), 0)

    def test_honeypot_creates_nothing(self):
        self.client.post(self.url, self.data(website="http://spam.example"))
        self.assertEqual(User.objects.count(), 0)

    def test_many_signups_from_same_ip_are_allowed_until_loose_limit(self):
        """같은 학교 Wi-Fi 의 여러 학생이 가입할 수 있다. IP 한도는 느슨한 보조 장치."""
        for i in range(10):
            self.assertEqual(Client().post(self.url, self.data(username=f"student_{i:02d}")).status_code, 302)
        self.assertEqual(User.objects.count(), 10)
        with override_settings(SIGNUP_IP_HOURLY_LIMIT=10):
            res = Client().post(self.url, self.data(username="student_99"))
        self.assertContains(res, "가입 요청이 너무 많아요")
        self.assertEqual(User.objects.count(), 10)

    def test_csrf_enforced(self):
        self.assertEqual(Client(enforce_csrf_checks=True).post(self.url, self.data()).status_code, 403)


class LoginTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user("login_user")
        self.url = reverse("accounts:login")

    def test_login_default_ends_with_browser_and_remember_keeps_30_days(self):
        self.client.post(self.url, {"username": "login_user", "password": PASSWORD})
        self.assertTrue(self.client.session.get_expire_at_browser_close())
        other = Client()
        other.post(self.url, {"username": "LOGIN_USER", "password": PASSWORD, "remember": "on"})
        self.assertFalse(other.session.get_expire_at_browser_close())
        self.assertEqual(other.session.get_expiry_age(), 60 * 60 * 24 * 30)
        self.assertNotContains(self.client.get(self.url, follow=True), 'checked')   # 기본은 꺼짐

    def test_next_returns_to_original_page_but_never_to_other_sites(self):
        res = self.client.post(self.url + "?next=/community/b/all/", {"username": "login_user", "password": PASSWORD})
        self.assertRedirects(res, "/community/b/all/", fetch_redirect_response=False)
        for evil in ["https://evil.example/x", "//evil.example/x", "http:evil.example", "/\\evil.example"]:
            c = Client()
            res = c.post(self.url, {"username": "login_user", "password": PASSWORD, "next": evil})
            self.assertEqual(res["Location"], reverse("community:home"), evil)

    def test_wrong_password_message_does_not_reveal_which_part(self):
        res = self.client.post(self.url, {"username": "login_user", "password": "wrong-pass"})
        self.assertContains(res, "아이디 또는 비밀번호가 맞지 않아요")
        res = self.client.post(self.url, {"username": "nobody_here", "password": "wrong-pass"})
        self.assertContains(res, "아이디 또는 비밀번호가 맞지 않아요")

    @override_settings(LOGIN_FAIL_LIMIT=3)
    def test_lock_is_per_account_not_per_ip(self):
        for _ in range(3):
            self.client.post(self.url, {"username": "login_user", "password": "wrong-pass"})
        res = self.client.post(self.url, {"username": "login_user", "password": PASSWORD})
        self.assertEqual(res.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)
        # 같은 IP 의 다른 학생은 정상 로그인
        make_user("classmate")
        res = Client().post(self.url, {"username": "classmate", "password": PASSWORD})
        self.assertEqual(res.status_code, 302)

    @override_settings(LOGIN_FAIL_LIMIT=2)
    def test_admin_login_is_throttled(self):
        for _ in range(2):
            self.assertEqual(self.client.post("/admin/login/", {"username": "root", "password": "x"}).status_code, 200)
        self.assertEqual(self.client.post("/admin/login/", {"username": "root", "password": "x"}).status_code, 429)

    def test_logout_requires_post_and_clears_session(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        res = self.client.post(reverse("accounts:logout"))
        self.assertIn("cache", res["Clear-Site-Data"])
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.get("/community/").status_code, 302)

    def test_no_password_reset_feature_is_implied(self):
        res = self.client.get(self.url)
        self.assertContains(res, "자동으로 되찾는 기능이 없어요")
        self.assertEqual(self.client.get("/accounts/password_reset/").status_code, 404)


class PasswordChangeTests(TestCase):
    def test_change_keeps_this_session_and_drops_others(self):
        user = make_user("pw_user")
        here, elsewhere = Client(), Client()
        here.force_login(user)
        elsewhere.force_login(user)
        new = "brand-new-pass-77!"
        res = here.post(reverse("accounts:password_change"),
                        {"old_password": PASSWORD, "new_password1": new, "new_password2": new})
        self.assertRedirects(res, reverse("campus:my"))
        self.assertEqual(here.get("/community/").status_code, 200)
        self.assertEqual(elsewhere.get("/community/").status_code, 302)       # 다른 기기는 로그아웃
        user.refresh_from_db()
        self.assertTrue(user.check_password(new))

    def test_wrong_old_password(self):
        user = make_user("pw_user2")
        self.client.force_login(user)
        self.client.post(reverse("accounts:password_change"),
                         {"old_password": "nope", "new_password1": "brand-new-pass-77!", "new_password2": "brand-new-pass-77!"})
        user.refresh_from_db()
        self.assertTrue(user.check_password(PASSWORD))


class WithdrawTests(CommunityTestCase):
    def test_withdraw_removes_identity_content_and_existing_sessions(self):
        self.write(self.alice, self.board_a, title="알리스 글", body="곧 탈퇴")
        post = Post.objects.get()
        self.login(self.bob)
        self.client.post(f"/community/p/{post.pk}/like/")
        bob_post = Post.objects.create(board=self.board_all, author=self.bob, title="밥 글", body="b")
        comment = Comment.objects.create(post=bob_post, author=self.alice, body="알리스 댓글")

        other_device = Client()
        other_device.force_login(self.alice)
        self.login(self.alice)
        url = reverse("accounts:withdraw")
        self.assertEqual(self.client.post(url, {"password": "wrong", "confirm": "on"}).status_code, 200)
        self.assertEqual(self.client.post(url, {"password": PASSWORD}).status_code, 200)       # 확인란 없이
        self.assertTrue(User.objects.get(pk=self.alice.pk).is_active)
        res = self.client.post(url, {"password": PASSWORD, "confirm": "on"})
        self.assertContains(res, "탈퇴했어요")

        gone = User.objects.get(pk=self.alice.pk)
        self.assertFalse(gone.is_active)
        self.assertTrue(gone.username.startswith("withdrawn-"))
        self.assertFalse(gone.has_usable_password())
        self.assertIsNone(gone.department)
        post.refresh_from_db()
        comment.refresh_from_db()
        self.assertEqual((post.status, post.body), (Post.DELETED, ""))
        self.assertEqual((comment.status, comment.body), (Comment.DELETED, ""))
        # 다시 로그인 불가, 다른 기기의 기존 세션도 끊김
        self.assertEqual(self.client.get("/community/").status_code, 302)
        self.assertEqual(other_device.get("/community/").status_code, 302)
        res = Client().post(reverse("accounts:login"), {"username": "alice_a", "password": PASSWORD})
        self.assertEqual(res.status_code, 200)
        # 같은 아이디로 새로 가입할 수 있다(예전 글과 이어지지 않는다)
        self.assertFalse(User.objects.filter(username="alice_a").exists())


class RestrictionTests(CommunityTestCase):
    def test_restricted_account_can_read_and_delete_own_but_not_write(self):
        self.write(self.alice, self.board_a, title="제한 전 글")
        post = Post.objects.get()
        self.alice.restricted_until = timezone.now() + timedelta(days=3)
        self.alice.restriction_reason = "도배"
        self.alice.save()
        self.login(self.alice)
        self.assertEqual(self.client.get(f"/community/p/{post.pk}/").status_code, 200)
        self.assertContains(self.client.get(reverse("campus:my")), "이용 제한 중")
        self.assertEqual(self.write(self.alice, self.board_a, title="제한 중 글").status_code, 403)
        self.assertEqual(self.write(self.alice, self.board_all, title="제한 중 글").status_code, 403)
        self.assertEqual(self.client.post(f"/community/p/{post.pk}/comment/", {"body": "댓글"}).status_code, 403)
        self.assertEqual(self.client.post(f"/community/p/{post.pk}/edit/",
                                          {"category": "free", "title": "수정", "body": "수정"}).status_code, 403)
        self.assertEqual(Post.objects.count(), 1)
        self.assertEqual(self.client.post(f"/community/p/{post.pk}/delete/").status_code, 302)   # 본인 삭제는 가능

    def test_restriction_ends_by_itself(self):
        self.alice.restricted_until = timezone.now() - timedelta(minutes=1)
        self.alice.save()
        self.assertEqual(self.write(self.alice, self.board_a).status_code, 302)

    def test_deactivated_account_session_stops_working(self):
        self.login(self.alice)
        self.assertEqual(self.client.get("/community/").status_code, 200)
        User.objects.filter(pk=self.alice.pk).update(is_active=False)
        self.assertEqual(self.client.get("/community/").status_code, 302)
        self.assertEqual(self.client.post(f"/community/b/{self.board_a.slug}/write/",
                                          {"category": "free", "title": "t", "body": "b"}).status_code, 302)
        self.assertEqual(Post.objects.count(), 0)


class MyPageTests(CommunityTestCase):
    def test_my_is_public_guide_when_logged_out_and_personal_when_logged_in(self):
        res = self.client.get(reverse("campus:my"))
        self.assertContains(res, reverse("accounts:login"))
        self.assertIn("no-store", res["Cache-Control"])
        self.login(self.alice)
        res = self.client.get(reverse("campus:my"))
        self.assertContains(res, "alice_a")
        self.assertContains(res, "테스트A과")
        self.assertContains(res, "인증 아님")
        self.assertIn("no-store", res["Cache-Control"])
