"""글·댓글·답글, 익명 번호, 공감·스크랩, 검색·정렬·페이지, 알림, 차단, XSS, 도배 제한."""

import re

from django.db import IntegrityError, transaction
from django.test import Client, override_settings

from community import services
from community.models import Block, Comment, Notification, Post, PostAnon, PostLike, Scrap
from community.tests.helpers import CommunityTestCase, make_user


class AnonymityTests(CommunityTestCase):
    def setUp(self):
        super().setUp()
        self.post = Post.objects.create(board=self.board_all, author=self.alice, title="익명 글", body="본문")

    def comment(self, user, body, parent=None):
        self.login(user)
        data = {"body": body}
        if parent:
            data["parent"] = parent.pk
        return self.client.post(f"/community/p/{self.post.pk}/comment/", data)

    def test_numbers_are_stable_within_a_post(self):
        self.comment(self.bob, "밥 첫 댓글")
        self.comment(self.amy, "에이미 댓글")
        self.comment(self.bob, "밥 둘째 댓글")
        self.comment(self.alice, "글쓴이 댓글")
        self.login(self.amy)
        html = self.client.get(f"/community/p/{self.post.pk}/").content.decode()
        labels = re.findall(r'comment__who[^>]*>([^<]+)</strong>', html)
        self.assertEqual(labels, ["글쓴이", "익명1", "익명2", "익명1", "글쓴이"])     # 맨 앞은 본문의 글쓴이

    def test_numbers_do_not_link_across_posts(self):
        other = Post.objects.create(board=self.board_all, author=self.alice, title="다른 글", body="b")
        self.comment(self.bob, "첫 글에서는 익명1")
        self.login(self.amy)
        self.client.post(f"/community/p/{other.pk}/comment/", {"body": "다른 글에서는 에이미가 익명1"})
        self.login(self.bob)
        self.client.post(f"/community/p/{other.pk}/comment/", {"body": "같은 밥이 여기서는 익명2"})
        self.assertEqual(PostAnon.objects.get(post=self.post, user=self.bob).number, 1)
        self.assertEqual(PostAnon.objects.get(post=other, user=self.bob).number, 2)

    def test_no_account_identifier_leaks_into_pages(self):
        big = make_user("zz_unique_login_id", self.dept_b)
        self.comment(big, "식별자 누출 확인용 댓글")
        self.login(self.amy)
        pages = [f"/community/p/{self.post.pk}/", "/community/b/all/", "/community/", "/community/search/?q=익명",
                 "/community/notifications/"]
        for url in pages:
            html = self.client.get(url).content.decode()
            for secret in ("zz_unique_login_id", "alice_a", "bob_b"):
                self.assertNotIn(secret, html, url)
            # 작성자 프로필·계정 번호로 가는 링크나 data 속성이 없다
            self.assertNotRegex(html, r'data-(author|user)[-_a-z]*=')
            self.assertNotRegex(html, r'href="[^"]*(author|user|profile)[^"]*"')

    def test_two_first_comments_at_once_get_different_numbers(self):
        self.assertEqual(services.anon_number(self.post, self.bob), 1)
        # 다른 사람이 같은 번호를 먼저 가져간 상황을 흉내: UNIQUE(post, number)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PostAnon.objects.create(post=self.post, user=self.amy, number=1)
        self.assertEqual(services.anon_number(self.post, self.amy), 2)
        self.assertEqual(services.anon_number(self.post, self.bob), 1)
        self.assertEqual(services.anon_number(self.post, self.alice), 0)


class CommentTests(CommunityTestCase):
    def setUp(self):
        super().setUp()
        self.post = Post.objects.create(board=self.board_all, author=self.alice, title="댓글 글", body="본문")

    def test_reply_and_deleted_parent_keeps_thread(self):
        self.login(self.bob)
        self.client.post(f"/community/p/{self.post.pk}/comment/", {"body": "부모 댓글"})
        parent = Comment.objects.get()
        self.login(self.amy)
        self.client.post(f"/community/p/{self.post.pk}/comment/", {"body": "답글입니다", "parent": parent.pk})
        self.post.refresh_from_db()
        self.assertEqual(self.post.comment_count, 2)
        self.login(self.bob)
        self.client.post(f"/community/c/{parent.pk}/delete/")
        res = self.client.get(f"/community/p/{self.post.pk}/")
        self.assertContains(res, "삭제된 댓글이에요")
        self.assertContains(res, "답글입니다")
        self.assertNotContains(res, "부모 댓글")
        self.post.refresh_from_db()
        self.assertEqual(self.post.comment_count, 1)
        parent.refresh_from_db()
        self.assertEqual(parent.body, "")            # 내용은 실제로 지워진다

    def test_reply_to_reply_is_not_allowed(self):
        parent = Comment.objects.create(post=self.post, author=self.bob, body="부모")
        reply = Comment.objects.create(post=self.post, author=self.amy, body="답글", parent=parent)
        self.login(self.alice)
        res = self.client.post(f"/community/p/{self.post.pk}/comment/", {"body": "3단계", "parent": reply.pk})
        self.assertEqual(res.status_code, 404)

    def test_cannot_comment_on_deleted_or_hidden_post(self):
        self.post.status = Post.HIDDEN
        self.post.save()
        self.login(self.bob)
        self.assertEqual(self.client.post(f"/community/p/{self.post.pk}/comment/", {"body": "x"}).status_code, 404)

    @override_settings(COMMUNITY_COMMENT_LIMIT=3)
    def test_rate_limit_is_per_account_not_per_ip(self):
        self.login(self.bob)
        for i in range(5):
            self.client.post(f"/community/p/{self.post.pk}/comment/", {"body": f"도배 {i}"})
        self.assertEqual(Comment.objects.filter(author=self.bob).count(), 3)
        # 같은 IP(같은 테스트 클라이언트 주소)의 다른 계정은 영향이 없다
        self.login(self.amy)
        self.client.post(f"/community/p/{self.post.pk}/comment/", {"body": "정상 댓글"})
        self.assertEqual(Comment.objects.filter(author=self.amy).count(), 1)

    @override_settings(COMMUNITY_POST_LIMIT=2)
    def test_post_rate_limit_per_account(self):
        for i in range(4):
            self.write(self.bob, self.board_all, title=f"도배 {i}")
        self.assertEqual(Post.objects.filter(author=self.bob).count(), 2)
        self.assertEqual(self.write(self.amy, self.board_all, title="정상").status_code, 302)


class LikeScrapTests(CommunityTestCase):
    def setUp(self):
        super().setUp()
        self.post = Post.objects.create(board=self.board_a, author=self.alice, title="공감 글", body="본문")

    def test_like_once_per_account_and_cancel(self):
        self.login(self.bob)
        self.client.post(f"/community/p/{self.post.pk}/like/")
        self.post.refresh_from_db()
        self.assertEqual(self.post.like_count, 1)
        self.login(self.amy)
        self.client.post(f"/community/p/{self.post.pk}/like/")
        self.login(self.bob)
        self.client.post(f"/community/p/{self.post.pk}/like/")          # 취소
        self.post.refresh_from_db()
        self.assertEqual((self.post.like_count, PostLike.objects.count()), (1, 1))

    def test_duplicate_rows_are_impossible_and_count_follows_rows(self):
        PostLike.objects.create(post=self.post, user=self.bob)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PostLike.objects.create(post=self.post, user=self.bob)
        Scrap.objects.create(post=self.post, user=self.bob)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Scrap.objects.create(post=self.post, user=self.bob)
        # 저장된 수가 틀어져 있어도 다음 공감 때 실제 행 수로 다시 맞춘다
        Post.objects.filter(pk=self.post.pk).update(like_count=99)
        services.toggle_like(self.amy, self.post)
        self.post.refresh_from_db()
        self.assertEqual(self.post.like_count, 2)

    def test_scrap_list_and_cancel(self):
        self.login(self.bob)
        self.client.post(f"/community/p/{self.post.pk}/scrap/")
        self.assertContains(self.client.get("/community/me/scraps/"), "공감 글")
        self.client.post(f"/community/p/{self.post.pk}/scrap/")
        self.assertNotContains(self.client.get("/community/me/scraps/"), "공감 글")

    def test_like_redirect_stays_on_site(self):
        self.login(self.bob)
        res = self.client.post(f"/community/p/{self.post.pk}/like/", {"next": "https://evil.example/"})
        self.assertEqual(res["Location"], f"/community/p/{self.post.pk}/")


class ListSearchTests(CommunityTestCase):
    def test_category_filter_sort_search_and_pagination(self):
        for i in range(23):
            Post.objects.create(board=self.board_a, author=self.alice, title=f"자유글 {i:02d}", body="x")
        q = Post.objects.create(board=self.board_a, author=self.alice, category="question", title="질문 있어요", body="기숙사 세탁기")
        Post.objects.filter(pk=q.pk).update(like_count=7)
        self.login(self.bob)
        url = f"/community/b/{self.board_a.slug}/"
        first = self.client.get(url)
        self.assertEqual(len(first.context["page"].object_list), 20)
        self.assertEqual(first.context["page"].paginator.num_pages, 2)
        self.assertContains(self.client.get(url + "?page=2"), "자유글 00")
        self.assertEqual(self.client.get(url + "?page=999").status_code, 200)          # 범위를 벗어난 쪽 번호
        self.assertEqual(self.client.get(url + "?page=abc").status_code, 200)
        only_q = self.client.get(url + "?cat=question")
        self.assertEqual([p.title for p in only_q.context["page"]], ["질문 있어요"])
        self.assertEqual(self.client.get(url + "?cat=nonsense").context["category"], "")
        popular = self.client.get(url + "?sort=popular")
        self.assertEqual(popular.context["page"].object_list[0].title, "질문 있어요")
        self.assertEqual([p.title for p in self.client.get(url + "?q=세탁기").context["page"]], ["질문 있어요"])
        self.assertContains(self.client.get(url + "?q=없는낱말"), "검색 결과가 없어요")
        self.assertContains(self.client.get(url + "?q=a"), "두 글자 이상")

    def test_list_does_not_run_a_query_per_post(self):
        for i in range(15):
            p = Post.objects.create(board=self.board_a, author=self.alice, title=f"글 {i}", body="x")
            Comment.objects.create(post=p, author=self.bob, body="c")
        self.login(self.bob)
        with self.assertNumQueries(8):           # 글 수와 상관없이 일정: 세션·계정·게시판·차단·개수·게시판 목록·글 목록·사진 묶음
            self.client.get(f"/community/b/{self.board_a.slug}/")

    def test_global_search_excludes_hidden_deleted_and_blocked(self):
        Post.objects.create(board=self.board_a, author=self.alice, title="공통낱말 보임", body="x")
        Post.objects.create(board=self.board_b, author=self.bob, title="공통낱말 숨김", body="x", status=Post.HIDDEN)
        Post.objects.create(board=self.board_b, author=self.bob, title="공통낱말 삭제", body="x", status=Post.DELETED)
        Post.objects.create(board=self.board_all, author=self.amy, title="공통낱말 차단됨", body="x", like_count=5)
        Block.objects.create(blocker=self.bob, blocked=self.amy)
        self.login(self.bob)
        titles = [p.title for p in self.client.get("/community/search/?q=공통낱말").context["page"]]
        self.assertEqual(titles, ["공통낱말 보임"])
        self.assertNotContains(self.client.get("/community/"), "공통낱말 차단됨")       # 인기 글에서도 제외

    def test_empty_board_and_recruit_status(self):
        self.login(self.alice)
        self.assertContains(self.client.get(f"/community/b/{self.board_a.slug}/"), "아직 글이 없어요")
        self.write(self.alice, self.board_a, category="recruit", title="스터디 모집", recruit_open="1")
        post = Post.objects.get()
        self.assertTrue(post.recruit_open)
        self.assertContains(self.client.get(f"/community/b/{self.board_a.slug}/"), "모집 중")
        self.client.post(f"/community/p/{post.pk}/recruit/", {"open": "0"})
        self.assertContains(self.client.get(f"/community/p/{post.pk}/"), "마감")
        self.write(self.alice, self.board_a, category="free", title="자유", recruit_open="1")
        self.assertIsNone(Post.objects.get(title="자유").recruit_open)


class XssTests(CommunityTestCase):
    PAYLOAD = '<script>alert("x")</script><img src=x onerror=alert(1)>'

    def test_post_comment_and_search_term_are_escaped(self):
        self.write(self.alice, self.board_all, title=self.PAYLOAD[:70], body=self.PAYLOAD)
        post = Post.objects.get()
        self.login(self.bob)
        self.client.post(f"/community/p/{post.pk}/comment/", {"body": self.PAYLOAD})
        for url in [f"/community/p/{post.pk}/", "/community/b/all/", "/community/",
                    "/community/search/?q=" + self.PAYLOAD, "/community/b/all/?q=" + self.PAYLOAD]:
            html = self.client.get(url).content.decode()
            self.assertNotIn("<script>alert", html, url)
            self.assertNotIn("<img src=x", html, url)
        self.assertIn("&lt;script&gt;", self.client.get(f"/community/p/{post.pk}/").content.decode())
        self.login(self.alice)
        self.assertNotIn("<script>alert", self.client.get("/community/notifications/").content.decode())

    def test_security_headers(self):
        self.login(self.alice)
        res = self.client.get("/community/")
        self.assertEqual(res["X-Content-Type-Options"], "nosniff")
        self.assertEqual(res["X-Frame-Options"], "DENY")


class NotificationTests(CommunityTestCase):
    def setUp(self):
        super().setUp()
        self.post = Post.objects.create(board=self.board_all, author=self.alice, title="알림 글", body="본문")

    def test_comment_and_reply_notify_the_right_people_once(self):
        self.login(self.alice)
        self.client.post(f"/community/p/{self.post.pk}/comment/", {"body": "내 글에 내가 단 댓글"})
        self.assertEqual(Notification.objects.count(), 0)                       # 나 자신에게는 알림 없음
        self.login(self.bob)
        self.client.post(f"/community/p/{self.post.pk}/comment/", {"body": "밥의 댓글"})
        bob_comment = Comment.objects.get(author=self.bob)
        self.assertEqual(list(Notification.objects.values_list("user__username", "kind")), [("alice_a", "comment")])
        self.login(self.amy)
        self.client.post(f"/community/p/{self.post.pk}/comment/", {"body": "밥에게 답글", "parent": bob_comment.pk})
        kinds = set(Notification.objects.filter(comment__author=self.amy).values_list("user__username", "kind"))
        self.assertEqual(kinds, {("alice_a", "comment"), ("bob_b", "reply")})
        self.login(self.bob)
        self.client.post(f"/community/p/{self.post.pk}/comment/", {"body": "내 댓글에 내가 답글", "parent": bob_comment.pk})
        self.assertEqual(Notification.objects.filter(user=self.bob).count(), 1)

    def test_inbox_marks_read_and_hides_unavailable_content(self):
        c = Comment.objects.create(post=self.post, author=self.bob, body="비밀스러운 댓글 내용")
        Notification.objects.create(user=self.alice, kind="comment", post=self.post, comment=c)
        self.login(self.alice)
        self.assertContains(self.client.get("/my/"), "새 알림 1")
        self.assertContains(self.client.get("/community/notifications/"), "비밀스러운 댓글 내용")
        self.assertEqual(Notification.objects.filter(read_at__isnull=True).count(), 0)
        c.status = Comment.HIDDEN
        c.save()
        res = self.client.get("/community/notifications/")
        self.assertNotContains(res, "비밀스러운 댓글 내용")
        self.assertContains(res, "지금은 볼 수 없는 글의 알림")

    def test_other_users_cannot_see_my_notifications(self):
        c = Comment.objects.create(post=self.post, author=self.bob, body="알리스만 볼 알림")
        Notification.objects.create(user=self.alice, kind="comment", post=self.post, comment=c)
        self.login(self.amy)
        self.assertNotContains(self.client.get("/community/notifications/"), "내 글에 댓글이 달렸어요")

    def test_blocked_user_does_not_trigger_notification(self):
        Block.objects.create(blocker=self.alice, blocked=self.bob)
        self.login(self.bob)
        self.client.post(f"/community/p/{self.post.pk}/comment/", {"body": "차단된 사람의 댓글"})
        self.assertEqual(Notification.objects.count(), 0)


class BlockTests(CommunityTestCase):
    def test_block_by_content_hides_posts_and_comments_and_can_be_undone(self):
        post = Post.objects.create(board=self.board_all, author=self.alice, title="차단될 글", body="b")
        mine = Post.objects.create(board=self.board_all, author=self.bob, title="내 글", body="b")
        Comment.objects.create(post=mine, author=self.alice, body="차단될 사람의 댓글")
        self.login(self.bob)
        res = self.client.post(f"/community/block/post/{post.pk}/", {"blocked": self.amy.pk, "user": self.amy.pk})
        self.assertEqual(res.status_code, 302)
        block = Block.objects.get()
        self.assertEqual((block.blocker, block.blocked), (self.bob, self.alice))     # 대상은 서버가 글에서 판정
        self.assertNotContains(self.client.get("/community/b/all/"), "차단될 글")
        blocked_comment = Comment.objects.get(body="차단될 사람의 댓글")
        self.assertNotContains(self.client.get(f"/community/p/{mine.pk}/"), "차단될 사람의 댓글")
        Comment.objects.create(post=mine, author=self.amy, body="다른 사람의 답글", parent=blocked_comment)
        detail = self.client.get(f"/community/p/{mine.pk}/")
        self.assertContains(detail, "차단한 사용자의 댓글이에요")      # 답글이 달려 있으면 자리 표시만
        self.assertContains(detail, "다른 사람의 답글")
        self.assertNotContains(detail, "차단될 사람의 댓글")
        listing = self.client.get("/community/me/blocks/").content.decode()
        self.assertIn("차단될 글", listing)
        self.assertNotIn("alice_a", listing)
        # 남의 차단 기록은 못 푼다
        other = Client()
        other.force_login(self.amy)
        other.post(f"/community/unblock/{block.pk}/")
        self.assertEqual(Block.objects.count(), 1)
        self.client.post(f"/community/unblock/{block.pk}/")
        self.assertEqual(Block.objects.count(), 0)
        self.assertContains(self.client.get("/community/b/all/"), "차단될 글")

    def test_cannot_block_self(self):
        post = Post.objects.create(board=self.board_all, author=self.bob, title="내 글", body="b")
        self.login(self.bob)
        self.client.post(f"/community/block/post/{post.pk}/")
        self.assertEqual(Block.objects.count(), 0)


class MyActivityTests(CommunityTestCase):
    def test_my_posts_and_comments_show_only_mine(self):
        Post.objects.create(board=self.board_a, author=self.alice, title="알리스 글", body="b")
        p = Post.objects.create(board=self.board_all, author=self.bob, title="밥 글", body="b")
        Comment.objects.create(post=p, author=self.alice, body="알리스의 댓글")
        Comment.objects.create(post=p, author=self.bob, body="밥의 댓글")
        self.login(self.alice)
        posts = self.client.get("/community/me/posts/")
        self.assertContains(posts, "알리스 글")
        self.assertNotContains(posts, "밥 글")
        comments = self.client.get("/community/me/comments/")
        self.assertContains(comments, "알리스의 댓글")
        self.assertNotContains(comments, "밥의 댓글")
