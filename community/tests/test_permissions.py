"""B2 권한: 모든 과 읽기, 쓰기는 전체 게시판 + 내 학과만. 요청을 직접 조작해도 서버가 막는지 확인한다."""

from django.test import Client
from django.urls import reverse

from community.models import Comment, Post, PostLike, Report, Scrap
from community.tests.helpers import CommunityTestCase, image_file


class AnonymousVisitorTests(CommunityTestCase):
    def test_public_pages_open_without_login(self):
        for name in ["home", "meals", "schedule", "notices", "bus", "feedback"]:
            self.assertEqual(self.client.get(reverse(f"campus:{name}")).status_code, 200, name)
        self.assertEqual(self.client.get(reverse("community:rules")).status_code, 200)

    def test_community_requires_login_everywhere(self):
        post = Post.objects.create(board=self.board_a, author=self.alice, title="t", body="b")
        gets = ["/community/", f"/community/b/{self.board_a.slug}/", f"/community/b/{self.board_a.slug}/write/",
                f"/community/p/{post.pk}/", f"/community/p/{post.pk}/edit/", "/community/search/?q=tt",
                "/community/notifications/", "/community/me/posts/", "/community/me/comments/",
                "/community/me/scraps/", "/community/me/blocks/", "/community/manage/",
                f"/community/report/post/{post.pk}/"]
        for url in gets:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 302, url)
            self.assertTrue(res["Location"].startswith("/accounts/login/?next="), url)
        posts = [f"/community/p/{post.pk}/like/", f"/community/p/{post.pk}/scrap/", f"/community/p/{post.pk}/comment/",
                 f"/community/p/{post.pk}/delete/", f"/community/block/post/{post.pk}/"]
        for url in posts:
            self.assertEqual(self.client.post(url, {"body": "x"}).status_code, 302, url)
        self.assertEqual((Comment.objects.count(), PostLike.objects.count()), (0, 0))
        self.assertEqual(Post.objects.get().status, Post.VISIBLE)


class ReadWriteTests(CommunityTestCase):
    def test_both_departments_read_each_other(self):
        self.write(self.alice, self.board_a, title="A과 소식", body="에이과 글")
        self.write(self.bob, self.board_b, title="B과 소식", body="비과 글")
        a_post, b_post = Post.objects.get(title="A과 소식"), Post.objects.get(title="B과 소식")
        self.login(self.bob)
        self.assertContains(self.client.get(f"/community/b/{self.board_a.slug}/"), "A과 소식")
        self.assertContains(self.client.get(f"/community/p/{a_post.pk}/"), "에이과 글")
        self.login(self.alice)
        self.assertContains(self.client.get(f"/community/b/{self.board_b.slug}/"), "B과 소식")
        self.assertContains(self.client.get(f"/community/p/{b_post.pk}/"), "비과 글")

    def test_other_department_board_explains_read_only(self):
        self.login(self.bob)
        res = self.client.get(f"/community/b/{self.board_a.slug}/")
        self.assertContains(res, "읽기만 할 수 있어요. 글·댓글은 테스트A과 소속만 쓸 수 있어요.")
        self.assertNotContains(res, f"/community/b/{self.board_a.slug}/write/")
        res = self.client.get(f"/community/b/{self.board_a.slug}/write/", follow=True)   # 주소를 직접 열어도
        self.assertContains(res, "읽기만 할 수 있어요")
        self.assertNotContains(res, 'enctype="multipart/form-data"')

    def test_other_department_cannot_write_post_comment_or_reply_even_with_forged_fields(self):
        self.write(self.alice, self.board_a, title="A과 글")
        post = Post.objects.get()
        Comment.objects.create(post=post, author=self.alice, body="A과 댓글")
        parent = Comment.objects.get()
        self.login(self.bob)
        forged = {"category": "free", "title": "침입", "body": "B과가 A과 게시판에", "board": self.board_b.slug,
                  "department": self.dept_a.pk, "author": self.alice.pk, "user": self.alice.pk}
        self.assertEqual(self.client.post(f"/community/b/{self.board_a.slug}/write/", forged).status_code, 403)
        self.assertEqual(self.client.post(f"/community/p/{post.pk}/comment/", {"body": "댓글", **forged}).status_code, 403)
        self.assertEqual(self.client.post(f"/community/p/{post.pk}/comment/",
                                          {"body": "답글", "parent": parent.pk}).status_code, 403)
        self.assertEqual(Post.objects.count(), 1)
        self.assertEqual(Comment.objects.count(), 1)
        res = self.client.get(f"/community/p/{post.pk}/")
        self.assertNotContains(res, 'name="body"')            # 댓글·답글 입력칸 자체가 없다

    def test_forged_author_field_is_ignored_on_allowed_board(self):
        self.login(self.bob)
        self.client.post("/community/b/all/write/", {"category": "free", "title": "전체 글", "body": "내용입니다",
                                                     "author": self.alice.pk, "board": self.board_a.slug})
        post = Post.objects.get()
        self.assertEqual((post.author, post.board), (self.bob, self.board_all))

    def test_everyone_writes_on_all_board_and_own_department(self):
        self.assertEqual(self.write(self.alice, self.board_all).status_code, 302)
        self.assertEqual(self.write(self.bob, self.board_all).status_code, 302)
        self.assertEqual(self.write(self.alice, self.board_a).status_code, 302)
        self.assertEqual(self.write(self.amy, self.board_a).status_code, 302)
        self.assertEqual(self.write(self.bob, self.board_b).status_code, 302)
        self.assertEqual(Post.objects.count(), 5)

    def test_other_department_can_like_scrap_report_block(self):
        self.write(self.alice, self.board_a, title="A과 글")
        post = Post.objects.get()
        self.login(self.bob)
        self.client.post(f"/community/p/{post.pk}/like/")
        self.client.post(f"/community/p/{post.pk}/scrap/")
        self.client.post(f"/community/report/post/{post.pk}/", {"reason": "spam"})
        self.assertEqual((PostLike.objects.count(), Scrap.objects.count(), Report.objects.count()), (1, 1, 1))
        self.assertEqual(self.client.post(f"/community/block/post/{post.pk}/").status_code, 302)
        self.assertNotContains(self.client.get(f"/community/b/{self.board_a.slug}/"), "A과 글")

    def test_user_without_department_reads_all_writes_only_all_board(self):
        from community.tests.helpers import make_user
        nobody = make_user("no_dept")
        self.assertEqual(self.write(nobody, self.board_all).status_code, 302)
        self.assertEqual(self.write(nobody, self.board_a).status_code, 403)
        self.assertEqual(self.client.get(f"/community/b/{self.board_a.slug}/").status_code, 200)

    def test_inactive_department_board_is_read_only(self):
        self.write(self.alice, self.board_a, title="예전 글")
        self.dept_a.is_active = False
        self.dept_a.save()
        self.assertEqual(self.write(self.alice, self.board_a, title="새 글").status_code, 403)
        self.assertContains(self.client.get(f"/community/b/{self.board_a.slug}/"), "예전 글")


class OwnershipTests(CommunityTestCase):
    def setUp(self):
        super().setUp()
        self.write(self.alice, self.board_a, title="알리스의 글", body="원래 내용", photos=image_file())
        self.post = Post.objects.get()
        self.comment = Comment.objects.create(post=self.post, author=self.alice, body="알리스 댓글")

    def test_others_cannot_edit_or_delete_even_in_same_department(self):
        for intruder in (self.amy, self.bob):
            self.login(intruder)
            self.assertEqual(self.client.get(f"/community/p/{self.post.pk}/edit/").status_code, 403)
            self.assertEqual(self.client.post(f"/community/p/{self.post.pk}/edit/",
                                              {"category": "free", "title": "가로챔", "body": "가로챔"}).status_code, 403)
            self.assertEqual(self.client.post(f"/community/p/{self.post.pk}/delete/").status_code, 403)
            self.assertEqual(self.client.post(f"/community/p/{self.post.pk}/recruit/", {"open": "0"}).status_code, 403)
            self.assertEqual(self.client.post(f"/community/c/{self.comment.pk}/delete/").status_code, 403)
        self.post.refresh_from_db()
        self.comment.refresh_from_db()
        self.assertEqual((self.post.title, self.post.body, self.post.status), ("알리스의 글", "원래 내용", Post.VISIBLE))
        self.assertEqual(self.comment.status, Comment.VISIBLE)
        self.assertEqual(self.post.attachments.count(), 1)

    def test_cannot_remove_another_posts_photo_by_swapping_attachment_id(self):
        self.write(self.amy, self.board_a, title="에이미 글", photos=image_file())
        amy_post = Post.objects.get(title="에이미 글")
        victim_key = str(self.post.attachments.get().key)
        self.login(self.amy)
        res = self.client.post(f"/community/p/{amy_post.pk}/edit/",
                               {"category": "free", "title": "에이미 글", "body": "내용입니다", "remove_photo": victim_key})
        self.assertEqual(res.status_code, 302)
        self.assertEqual(self.post.attachments.count(), 1)       # 남의 사진은 그대로
        self.assertEqual(amy_post.attachments.count(), 1)

    def test_reply_parent_must_belong_to_same_post(self):
        other = Post.objects.create(board=self.board_a, author=self.amy, title="다른 글", body="b")
        self.login(self.amy)
        res = self.client.post(f"/community/p/{other.pk}/comment/", {"body": "엉뚱한 부모", "parent": self.comment.pk})
        self.assertEqual(res.status_code, 404)
        self.assertEqual(Comment.objects.filter(post=other).count(), 0)

    def test_owner_edits_and_deletes(self):
        self.login(self.alice)
        res = self.client.post(f"/community/p/{self.post.pk}/edit/",
                               {"category": "question", "title": "고친 제목", "body": "고친 내용"})
        self.assertRedirects(res, f"/community/p/{self.post.pk}/")
        self.post.refresh_from_db()
        self.assertEqual((self.post.title, self.post.category), ("고친 제목", "question"))
        self.assertIsNotNone(self.post.edited_at)
        self.client.post(f"/community/p/{self.post.pk}/delete/")
        self.post.refresh_from_db()
        self.assertEqual((self.post.status, self.post.body), (Post.DELETED, ""))
        self.assertEqual(self.client.get(f"/community/p/{self.post.pk}/").status_code, 404)

    def test_after_department_change_old_post_is_editable_but_old_board_is_not_writable(self):
        """학과 변경(운영자 처리) 뒤: 예전 글 수정·삭제는 허용, 예전 학과에 새 글·댓글은 거부."""
        self.alice.department = self.dept_b
        self.alice.save()
        self.login(self.alice)
        res = self.client.post(f"/community/p/{self.post.pk}/edit/",
                               {"category": "free", "title": "옮긴 뒤 수정", "body": "수정"})
        self.assertEqual(res.status_code, 302)
        self.assertEqual(self.write(self.alice, self.board_a, title="예전 과에 새 글").status_code, 403)
        self.assertEqual(self.client.post(f"/community/p/{self.post.pk}/comment/", {"body": "예전 과 댓글"}).status_code, 403)
        self.assertEqual(self.write(self.alice, self.board_b, title="새 과 글").status_code, 302)
        self.assertEqual(self.client.post(f"/community/p/{self.post.pk}/delete/").status_code, 302)

    def test_csrf_required_for_every_change(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.alice)
        urls = [f"/community/b/{self.board_a.slug}/write/", f"/community/p/{self.post.pk}/edit/",
                f"/community/p/{self.post.pk}/delete/", f"/community/p/{self.post.pk}/like/",
                f"/community/p/{self.post.pk}/scrap/", f"/community/p/{self.post.pk}/comment/",
                f"/community/c/{self.comment.pk}/delete/", f"/community/report/post/{self.post.pk}/",
                f"/community/block/post/{self.post.pk}/", "/accounts/logout/", "/accounts/withdraw/"]
        for url in urls:
            self.assertEqual(c.post(url, {"body": "x", "title": "x", "category": "free"}).status_code, 403, url)
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, Post.VISIBLE)

    def test_state_changing_urls_reject_get(self):
        self.login(self.alice)
        for url in [f"/community/p/{self.post.pk}/delete/", f"/community/p/{self.post.pk}/like/",
                    f"/community/c/{self.comment.pk}/delete/", f"/community/block/post/{self.post.pk}/"]:
            self.assertEqual(self.client.get(url).status_code, 405, url)
