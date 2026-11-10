"""계정·학과 모델.

- User: Django 기본 인증 구조(AbstractUser) + 자기 신고 학과 + 이용 제한·탈퇴 기록.
  학교 이메일·학번·실명·전화번호는 받지 않는다. 학과는 '인증'이 아니라 본인이 고른 값이다.
- Department: 학과 목록. 운영자가 관리자 화면에서 추가·비활성화한다.
"""

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class Department(models.Model):
    name = models.CharField("학과 이름", max_length=40, unique=True)
    is_active = models.BooleanField("사용 중", default=True,
                                    help_text="끄면 가입 화면과 학과 게시판 목록에서 빠지고, 그 게시판은 읽기만 가능해요.")
    order = models.PositiveSmallIntegerField("표시 순서", default=0)
    note = models.CharField("출처·메모", max_length=200, blank=True)

    class Meta:
        verbose_name = "학과"
        verbose_name_plural = "학과"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class User(AbstractUser):
    """Lolypoly 사용자.

    username = 로그인 아이디(다른 학생에게 보이지 않음). email·first_name·last_name 은 받지 않는다.
    """

    department = models.ForeignKey(Department, verbose_name="학과(자기 신고)", null=True, blank=True,
                                   on_delete=models.PROTECT, related_name="users")
    restricted_until = models.DateTimeField("이용 제한 종료 시각", null=True, blank=True,
                                            help_text="이 시각까지 글·댓글 작성이 막혀요. 비우면 제한 없음.")
    # db_default: 이전 버전 코드로 되돌려도(롤백) 이 칸 없이 행을 넣을 수 있게 DB 자체에 기본값을 둔다
    restriction_reason = models.CharField("이용 제한 사유", max_length=200, blank=True, db_default="")
    withdrawn_at = models.DateTimeField("탈퇴 시각", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "사용자"
        verbose_name_plural = "사용자"

    @property
    def is_restricted(self) -> bool:
        return bool(self.restricted_until and self.restricted_until > timezone.now())
