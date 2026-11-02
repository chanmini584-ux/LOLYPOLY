from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Lolypoly 사용자 모델.

    지금은 Django 기본 인증 구조(AbstractUser)를 그대로 쓴다.
    로그인 기능은 아직 구현하지 않았다. 나중에 계정 기능을 붙일 때
    마이그레이션 충돌 없이 필드를 추가할 수 있도록 처음부터 교체 가능한 모델로 둔 것이다.

    향후 확장 후보(미구현): student_number(학번, 프로필 정보이며 인증 수단 아님),
    department(학과), grade(학년). 자세한 방향은 docs/DECISIONS.md 참고.
    """

    class Meta:
        verbose_name = "사용자"
        verbose_name_plural = "사용자"
