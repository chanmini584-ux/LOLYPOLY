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
        BUS = "bus", "버스 노선"

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


class BusRoute(models.Model):
    """학교 정류장을 지나는 버스 노선 1개 (TAGO routeId 단위, 왕복 전체).

    같은 번호라도 기점·경유지가 다른 변형은 routeId 가 따로다. 예: '901(기점군자리)', '동산1(동산102)'.
    화면은 괄호 앞 번호(group)로 묶어 탭 하나로 보여 준다.
    """

    route_id = models.CharField("노선 ID(TAGO)", max_length=30, unique=True)
    route_no = models.CharField("노선 이름(TAGO)", max_length=50)
    group = models.CharField("노선 번호(화면 탭)", max_length=30)
    route_type = models.CharField("노선 종류", max_length=20, blank=True)   # 지선버스·마을버스 등
    start_stop = models.CharField("기점", max_length=100, blank=True)
    end_stop = models.CharField("종점", max_length=100, blank=True)
    collected_at = models.DateTimeField("수집 시각")

    class Meta:
        verbose_name = "버스 노선"
        verbose_name_plural = "버스 노선"
        ordering = ["group", "route_no"]

    def __str__(self):
        return self.route_no


class BusRouteStop(models.Model):
    """노선의 정류장 1개. (노선, 순번)이 같으면 같은 데이터 → 재수집 시 중복 없음."""

    route = models.ForeignKey(BusRoute, on_delete=models.CASCADE, related_name="stops")
    order = models.PositiveSmallIntegerField("순번(nodeord)")
    node_id = models.CharField("정류장 ID(TAGO)", max_length=30)
    name = models.CharField("정류장 이름", max_length=100)
    direction = models.PositiveSmallIntegerField("방향(updowncd)", default=0)  # 0=가는 방향, 1=돌아오는 방향
    lat = models.FloatField("위도", null=True, blank=True)
    lng = models.FloatField("경도", null=True, blank=True)

    class Meta:
        verbose_name = "버스 노선 정류장"
        verbose_name_plural = "버스 노선 정류장"
        ordering = ["route", "order"]
        constraints = [
            models.UniqueConstraint(fields=["route", "order"], name="unique_bus_stop_order"),
        ]

    def __str__(self):
        return f"{self.route.route_no} {self.order}. {self.name}"
