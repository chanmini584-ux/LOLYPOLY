"""사진 첨부: 검사·재인코딩·메타데이터 제거·보호된 조회·정리."""

import io
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from PIL import Image

from community.models import Attachment, Post, Report
from community.tests.helpers import CommunityTestCase, image_file


def media_files():
    root = Path(settings.MEDIA_ROOT)
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []


def exif_bytes(orientation=6):
    exif = Image.Exif()
    exif[0x0112] = orientation                      # 방향: 6 = 시계 방향 90도로 돌려야 바로 섬
    exif[0x010F] = "LolyCam"                        # 제조사
    exif[0x0110] = "Secret Phone 15"                # 기기
    exif[0x8825] = {1: "N", 2: (37.0, 52.0, 30.0), 3: "E", 4: (127.0, 43.0, 48.0)}   # GPS
    return exif.tobytes()


class PhotoUploadTests(CommunityTestCase):
    def post_with(self, *files, user=None, board=None, **extra):
        return self.write(user or self.alice, board or self.board_a, title="사진 글", photos=list(files), **extra)

    def stored(self, attachment, thumb=False):
        return Path(settings.MEDIA_ROOT) / (attachment.thumb_path if thumb else attachment.path)

    def test_upload_reencodes_resizes_and_serves(self):
        before = len(media_files())
        res = self.post_with(image_file("내 사진 원본이름.png", "PNG", (3000, 2000)), image_file("b.webp", "WEBP", (800, 600)))
        self.assertEqual(res.status_code, 302)
        post = Post.objects.get()
        first, second = post.attachments.all()
        self.assertEqual(len(media_files()) - before, 4)                 # 사진마다 본문용 + 썸네일
        with Image.open(self.stored(first)) as img:
            self.assertEqual((img.format, img.size), ("JPEG", (1920, 1280)))      # 긴 변 1920 으로 줄임
        with Image.open(self.stored(first, thumb=True)) as img:
            self.assertEqual(max(img.size), 480)
        with Image.open(self.stored(second)) as img:
            self.assertEqual((img.format, img.size), ("JPEG", (800, 600)))        # 작은 사진은 키우지 않음
        # 저장 이름은 무작위: 원래 파일 이름·계정 아이디·계정 번호가 들어가지 않는다
        for a in (first, second):
            self.assertRegex(a.path, r"^community/\d{4}/\d{2}/[0-9a-f]{32}\.jpg$")
            self.assertNotIn("원본이름", a.path)
            self.assertNotIn("alice", a.path)
        detail = self.client.get(f"/community/p/{post.pk}/")
        self.assertContains(detail, f"/community/photo/{first.key}/")
        self.assertNotContains(detail, "원본이름")
        self.assertContains(self.client.get(f"/community/b/{self.board_a.slug}/"), f"/community/photo/{first.key}/t/")

    def test_exif_orientation_applied_and_metadata_removed(self):
        upload = image_file("gps.jpg", "JPEG", (400, 200), exif=exif_bytes(6))
        self.assertIn(b"Secret Phone 15", upload.read())
        upload.seek(0)
        self.post_with(upload)
        a = Attachment.objects.get()
        self.assertEqual((a.width, a.height), (200, 400))                # 방향 보정으로 세로가 됨
        for thumb in (False, True):
            data = self.stored(a, thumb).read_bytes()
            self.assertNotIn(b"Secret Phone 15", data)
            self.assertNotIn(b"LolyCam", data)
            self.assertNotIn(b"Exif", data)
            with Image.open(io.BytesIO(data)) as img:
                self.assertEqual(len(img.getexif()), 0)
                self.assertNotIn("icc_profile", img.info)

    def test_transparent_png_becomes_white_background_jpeg(self):
        self.post_with(image_file("t.png", "PNG", (50, 50), color=(0, 0, 0, 0), mode="RGBA"))
        with Image.open(self.stored(Attachment.objects.get())) as img:
            self.assertEqual(img.mode, "RGB")
            self.assertGreater(min(img.getpixel((25, 25))), 240)

    def test_disguised_and_unsupported_files_are_rejected(self):
        html = SimpleUploadedFile("a.jpg", b"<html><script>alert(1)</script></html>", content_type="image/jpeg")
        svg = SimpleUploadedFile("a.png", b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>', content_type="image/png")
        exe = SimpleUploadedFile("a.webp", b"MZ\x90\x00" + b"\x00" * 200, content_type="image/webp")
        gif = image_file("a.jpg", "GIF", (10, 10), mode="P", color=1)                # 진짜 이미지지만 허용 형식 아님
        bmp = image_file("a.png", "BMP", (10, 10))
        broken = SimpleUploadedFile("a.jpg", image_file().read()[:300], content_type="image/jpeg")   # 잘린 JPEG
        empty = SimpleUploadedFile("a.jpg", b"", content_type="image/jpeg")
        before = len(media_files())
        for bad in (html, svg, exe, gif, bmp, broken):
            res = self.post_with(bad)
            self.assertContains(res, "1번째 사진", status_code=400)
        self.assertEqual(self.post_with(empty).status_code, 400)        # 빈 파일은 폼 단계에서 거절
        self.assertEqual(Post.objects.count(), 0)
        self.assertEqual(len(media_files()), before)

    @override_settings(COMMUNITY_PHOTO_MAX_BYTES=20_000)
    def test_file_size_limit(self):
        noisy = Image.effect_noise((600, 600), 80).convert("RGB")
        out = io.BytesIO()
        noisy.save(out, "JPEG", quality=95)
        self.assertGreater(out.tell(), 20_000)
        res = self.post_with(SimpleUploadedFile("big.jpg", out.getvalue(), content_type="image/jpeg"))
        self.assertContains(res, "까지 올릴 수 있어요", status_code=400)
        self.assertEqual(Post.objects.count(), 0)

    @override_settings(COMMUNITY_PHOTO_MAX_PIXELS=1_000_000)
    def test_pixel_limit_rejects_before_decoding(self):
        res = self.post_with(image_file("huge.png", "PNG", (2000, 1500)))           # 3MP > 1MP
        self.assertContains(res, "화소 수 초과", status_code=400)
        res = self.post_with(image_file("bomb.png", "PNG", (4000, 3000)))           # 12MP > 2배 한도(압축 폭탄 판정)
        self.assertContains(res, "화소 수 초과", status_code=400)
        self.assertEqual(Post.objects.count(), 0)

    def test_count_limit_and_all_or_nothing(self):
        before = len(media_files())
        res = self.post_with(*[image_file(f"{i}.jpg") for i in range(6)])
        self.assertContains(res, "5장까지", status_code=400)
        # 5장 중 마지막 한 장이 가짜면 앞의 4장도 저장하지 않는다
        fake = SimpleUploadedFile("x.jpg", b"not an image", content_type="image/jpeg")
        res = self.post_with(*[image_file(f"{i}.jpg") for i in range(4)], fake)
        self.assertContains(res, "5번째 사진", status_code=400)
        self.assertEqual((Post.objects.count(), Attachment.objects.count()), (0, 0))
        self.assertEqual(len(media_files()), before)
        self.assertEqual(self.post_with(*[image_file(f"{i}.jpg") for i in range(5)]).status_code, 302)
        self.assertEqual(Attachment.objects.count(), 5)

    @override_settings(COMMUNITY_MAX_REQUEST_BYTES=5_000)
    def test_oversized_request_is_refused_up_front(self):
        res = self.post_with(image_file(size=(1200, 1200)))
        self.assertEqual(res.status_code, 413)
        self.assertEqual(Post.objects.count(), 0)

    def test_edit_removes_and_adds_photos_within_limit(self):
        self.post_with(image_file("1.jpg"), image_file("2.jpg"), image_file("3.jpg"))
        post = Post.objects.get()
        keys = [str(a.key) for a in post.attachments.all()]
        removed = post.attachments.first()
        removed_paths = [self.stored(removed), self.stored(removed, True)]
        base = {"category": "free", "title": "사진 글", "body": "내용입니다"}
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post(f"/community/p/{post.pk}/edit/",
                                   {**base, "remove_photo": keys[0], "photos": [image_file("4.jpg"), image_file("5.jpg")]})
        self.assertEqual(res.status_code, 302)
        self.assertEqual(post.attachments.count(), 4)
        self.assertFalse(any(p.exists() for p in removed_paths))          # 뺀 사진 파일은 지워짐
        # 4장 + 2장 = 6장은 거절되고 기존 사진은 그대로
        res = self.client.post(f"/community/p/{post.pk}/edit/", {**base, "photos": [image_file("6.jpg"), image_file("7.jpg")]})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(post.attachments.count(), 4)

    def test_deleting_post_removes_files(self):
        self.post_with(image_file("1.jpg"), image_file("2.jpg"))
        post = Post.objects.get()
        paths = [self.stored(a, t) for a in post.attachments.all() for t in (False, True)]
        self.assertTrue(all(p.exists() for p in paths))
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"/community/p/{post.pk}/delete/")
        self.assertFalse(any(p.exists() for p in paths))
        self.assertEqual(Attachment.objects.count(), 0)

    def test_reported_post_keeps_photos_only_for_review_period(self):
        from datetime import timedelta

        from django.utils import timezone

        from community import services

        self.post_with(image_file("1.jpg"))
        post = Post.objects.get()
        path = self.stored(post.attachments.get())
        Report.objects.create(reporter=self.bob, post=post, reason="privacy")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"/community/p/{post.pk}/delete/")
        self.assertTrue(path.exists())                                     # 처리 전 신고가 있어 검토용으로 보관
        self.assertEqual(self.client.get(f"/community/photo/{post.attachments.get().key}/").status_code, 404)   # 작성자도 못 봄
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(services.purge_expired(timezone.now() + timedelta(days=29)), (0, 0))
            self.assertEqual(services.purge_expired(timezone.now() + timedelta(days=31)), (1, 0))
        self.assertFalse(path.exists())
        post.refresh_from_db()
        self.assertEqual(post.body, "")


class PhotoAccessTests(CommunityTestCase):
    def setUp(self):
        super().setUp()
        self.write(self.alice, self.board_a, title="사진 글", photos=image_file())
        self.post = Post.objects.get()
        self.att = self.post.attachments.get()
        self.urls = [f"/community/photo/{self.att.key}/", f"/community/photo/{self.att.key}/t/"]

    def test_logged_in_reader_gets_jpeg_with_safe_headers(self):
        self.login(self.bob)                                              # 다른 과도 읽을 수 있다
        for url in self.urls:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res["Content-Type"], "image/jpeg")
            self.assertEqual(res["X-Content-Type-Options"], "nosniff")
            self.assertIn("no-store", res["Cache-Control"])
            self.assertIn("private", res["Cache-Control"])
            self.assertIn("inline", res["Content-Disposition"])
            self.assertTrue(b"".join(res.streaming_content).startswith(b"\xff\xd8"))

    def test_anonymous_cannot_fetch_even_with_the_exact_url(self):
        for url in self.urls:
            res = Client().get(url)
            self.assertEqual(res.status_code, 302)
            self.assertIn("/accounts/login/", res["Location"])

    def test_no_public_media_route_exists(self):
        self.login(self.bob)
        for url in [f"/media/{self.att.path}", f"/static/{self.att.path}", f"/community/photo/{self.att.path}"]:
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_hidden_post_photo_only_for_author_and_moderator(self):
        from django.contrib.auth.models import Group

        self.post.status = Post.HIDDEN
        self.post.save()
        self.login(self.bob)
        self.assertEqual(self.client.get(self.urls[0]).status_code, 404)
        self.login(self.alice)
        self.assertEqual(self.client.get(self.urls[0]).status_code, 200)
        self.amy.groups.add(Group.objects.get(name="커뮤니티 운영자"))
        self.login(self.amy)
        self.assertEqual(self.client.get(self.urls[0]).status_code, 200)

    def test_after_logout_or_withdrawal_photo_is_not_served(self):
        from community.tests.helpers import PASSWORD

        self.login(self.bob)
        self.assertEqual(self.client.get(self.urls[0]).status_code, 200)
        self.client.post("/accounts/logout/")
        self.assertEqual(self.client.get(self.urls[0]).status_code, 302)
        self.login(self.alice)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post("/accounts/withdraw/", {"password": PASSWORD, "confirm": "on"})
        self.login(self.bob)
        self.assertEqual(self.client.get(self.urls[0]).status_code, 404)       # 탈퇴하면 사진도 지워짐
        self.assertFalse((Path(settings.MEDIA_ROOT) / self.att.path).exists())

    def test_unknown_key_is_404(self):
        self.login(self.bob)
        self.assertEqual(self.client.get("/community/photo/00000000-0000-0000-0000-000000000000/").status_code, 404)
