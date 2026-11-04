"""수집 데이터 모델.

- 화면은 이 모델만 조회한다 (요청마다 공식 홈페이지에 접속하지 않음).
- 날짜는 Asia/Seoul 기준 '정보의 날짜'(DateField), 시각은 UTC 저장(USE_TZ) 후 서울 시간으로 표시.
- 정보의 날짜(식단 날짜·게시일)와 수집 시각(collected_at)은 다른 필드로 구분한다.
"""

from django.db import models
from django.utils import timezone


class CollectionRun(models.Model):
    """수집 1회 실행 기록. 마지막 성공 시각과 실패 원인을 확인하는 용도."""

    class Source(models.TextChoices):
        MEALS = "meals", "식단"
        EVENTS = "events", "학사일정"
        NOTICES = "notices", "공지"

    class Status(models.TextChoices):
        RUNNING = "running", "진행 중"
        SUCCESS = "success", "성공"
        FAILED = "failed", "실패"

    source = models.CharField("수집 대상", max_length=20, choices=Source.choices)
    status = models.CharField("결과", max_length=20, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField("시작", default=timezone.now)
    finished_at = models.DateTimeField("종료", null=True, blank=True)
    item_count = models.PositiveIntegerField("저장 건수", default=0)
    message = models.TextField("메시지(요약·실패 원인)", blank=True)

    class Meta:
        verbose_name = "수집 기록"
        verbose_name_plural = "수집 기록"
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["source", "-started_at"])]

    def __str__(self):
        return f"{self.get_source_display()} {self.get_status_display()} {self.started_at:%Y-%m-%d %H:%M}"


class Meal(models.Model):
    """하루의 한 끼. (날짜, 끼니)가 같으면 같은 데이터 → 재수집 시 중복 없음."""

    class MealType(models.TextChoices):
        BREAKFAST = "breakfast", "조식"
        LUNCH = "lunch", "중식"
        DINNER = "dinner", "석식"

    date = models.DateField("식단 날짜")
    meal_type = models.CharField("끼니", max_length=10, choices=MealType.choices)
    # 메뉴 목록. 빈 목록 = 공식 식단표에 그 끼니가 비어 있음(수집은 됨).
    items = models.JSONField("메뉴", default=list, blank=True)
    source_url = models.URLField("원문 URL", max_length=500)
    collected_at = models.DateTimeField("수집 시각")

    class Meta:
        verbose_name = "식단"
        verbose_name_plural = "식단"
        ordering = ["date", "meal_type"]
        constraints = [
            models.UniqueConstraint(fields=["date", "meal_type"], name="unique_meal_per_date_type"),
        ]

    def __str__(self):
        return f"{self.date} {self.get_meal_type_display()}"


class AcademicEvent(models.Model):
    """학사일정 1건. (과정, 제목, 시작일, 종료일)이 같으면 같은 일정 → 재수집·월 경계 중복 없음."""

    title = models.CharField("일정명", max_length=300)          # 과정 머리말 제외
    course = models.CharField("과정", max_length=50, blank=True)  # 공식 머리말 [공통], [2년제학위과정] 등
    start_date = models.DateField("시작일")
    end_date = models.DateField("종료일")
    source_year = models.PositiveSmallIntegerField("수집한 연도 페이지")
    source_url = models.URLField("원문 URL", max_length=500)
    collected_at = models.DateTimeField("수집 시각")

    class Meta:
        verbose_name = "학사일정"
        verbose_name_plural = "학사일정"
        ordering = ["start_date", "end_date", "title"]
        constraints = [
            models.UniqueConstraint(fields=["course", "title", "start_date", "end_date"], name="unique_academic_event"),
        ]

    def __str__(self):
        return f"{self.start_date}~{self.end_date} {self.title}"


class Notice(models.Model):
    """공지사항 1건. 공식 게시글 번호(post_id)로 식별 → 재수집 시 갱신."""

    post_id = models.CharField("게시글 번호", max_length=20, unique=True)
    title = models.CharField("제목", max_length=500)                  # 공식 제목 그대로
    category = models.CharField("분류(제목 머리말)", max_length=50, blank=True)
    author = models.CharField("작성 부서", max_length=100, blank=True)
    posted_on = models.DateField("게시일")                            # 공식 작성일 (수집 시각과 다름)
    is_pinned = models.BooleanField("상단 고정(공식 '공지' 표시)", default=False)
    source_url = models.URLField("원문 URL", max_length=500)
    collected_at = models.DateTimeField("수집 시각")

    class Meta:
        verbose_name = "공지"
        verbose_name_plural = "공지"
        ordering = ["-posted_on", "-post_id"]

    def __str__(self):
        return self.title


class Feedback(models.Model):
    """시범 운영 학생 의견. 이름·학번·전화번호·첨부파일은 받지 않는다.

    participant_code 는 같은 사람의 반복 응답을 구분하고 싶을 때만 쓰는 선택 값(예: 배부물의 임의 코드).
    client_hash 는 도배 제한용으로 접속 주소를 비밀키와 섞어 한 방향으로 줄인 값이며 원래 주소로 되돌릴 수 없다.
    """

    useful = models.CharField("유용했던 기능", max_length=500, blank=True)
    trouble = models.CharField("막히거나 불편했던 점", max_length=500, blank=True)
    wish = models.CharField("다시 쓸 이유·원하는 개선", max_length=500, blank=True)
    participant_code = models.CharField("참여 코드(선택)", max_length=20, blank=True)
    client_hash = models.CharField(max_length=16, blank=True, editable=False)
    created_at = models.DateTimeField("제출 시각", default=timezone.now)
    reviewed = models.BooleanField("확인함", default=False)

    class Meta:
        verbose_name = "학생 의견"
        verbose_name_plural = "학생 의견"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["client_hash", "-created_at"])]

    def __str__(self):
        return f"의견 {self.created_at:%Y-%m-%d %H:%M}"
