"""커뮤니티 테스트 도우미: 테스트용 학과·계정, 가짜 사진 파일."""

import io
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from accounts.models import Department
from community.models import Board

PASSWORD = "lolypoly-test-9!"


def make_user(username, dept=None, **extra):
    return get_user_model().objects.create_user(username=username, password=PASSWORD, department=dept, **extra)


def image_file(name="photo.jpg", fmt="JPEG", size=(1200, 800), color=(200, 60, 60), exif=None, mode="RGB"):
    img = Image.new(mode, size, color)
    out = io.BytesIO()
    kwargs = {"exif": exif} if exif is not None else {}
    img.save(out, format=fmt, **kwargs)
    types = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "GIF": "image/gif", "BMP": "image/bmp"}
    return SimpleUploadedFile(name, out.getvalue(), content_type=types.get(fmt, "application/octet-stream"))


class CommunityTestCase(TestCase):
    """테스트 전용 학과 2개(테스트A과·테스트B과)와 계정 3개. 사진은 임시 폴더에 저장하고 끝나면 지운다."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp(prefix="lolypoly-test-media-")
        cls._override = override_settings(MEDIA_ROOT=cls._media)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        cls.dept_a = Department.objects.create(name="테스트A과", order=90)
        cls.dept_b = Department.objects.create(name="테스트B과", order=91)
        cls.board_all = Board.objects.get(kind=Board.ALL)
        cls.board_a = Board.objects.get(department=cls.dept_a)
        cls.board_b = Board.objects.get(department=cls.dept_b)
        cls.alice = make_user("alice_a", cls.dept_a)      # A과
        cls.amy = make_user("amy_a", cls.dept_a)          # A과
        cls.bob = make_user("bob_b", cls.dept_b)          # B과

    def setUp(self):
        cache.clear()

    def login(self, user):
        self.client.force_login(user)

    def write(self, user, board, title="제목", body="내용입니다", category="free", **extra):
        self.login(user)
        return self.client.post(f"/community/b/{board.slug}/write/",
                                {"category": category, "title": title, "body": body, **extra})
