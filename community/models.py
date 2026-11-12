"""학과별 익명 커뮤니티 모델.

관계
  Board(학교 전체 1개 + 학과마다 1개) ─< Post ─< Comment(답글은 parent 로 1단계)
  Post ─< Attachment(사진), PostLike(공감), Scrap(스크랩), PostAnon(글 안에서만 쓰는 익명 번호)
  Report(신고) → Post 또는 Comment,  Block(차단) 차단한 사람 → 차단된 사람
  Notification(알림함),  ModerationLog(운영 기록)

익명
  글·댓글은 내부적으로 계정(author)과 연결돼 있지만 다른 학생에게는 '글쓴이'·'익명N'으로만 보인다.
  익명 번호(PostAnon.number)는 글마다 1부터 새로 매기므로 다른 글의 번호와 이어지지 않는다.
  계정 ID·아이디는 화면·주소·사진 파일명 어디에도 넣지 않는다.

삭제 정책
  작성자가 지우면 내용과 사진을 바로 지운다(status=deleted, 본문 비움). 단, 처리 안 된 신고가 걸려 있으면
  운영자 검토를 위해 COMMUNITY_REVIEW_RETENTION_DAYS 일 동안만 숨긴 채 두었다가 purge_community 명령이 지운다.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

User = settings.AUTH_USER_MODEL


class Board(models.Model):
    ALL = "all"
    DEPT = "dept"
    KINDS = [(ALL, "학교 전체"), (DEPT, "학과")]

    kind = models.CharField("종류", max_length=8, choices=KINDS)
    department = models.OneToOneField("accounts.Department", verbose_name="학과", null=True, blank=True,
                                      on_delete=models.PROTECT, related_name="board")
    slug = models.SlugField("주소 이름", max_length=20, unique=True)

    class Meta:
        verbose_name = "게시판"
        verbose_name_plural = "게시판"
        constraints = [
            models.UniqueConstraint(fields=["kind"], condition=Q(kind="all"), name="community_single_all_board"),
            models.CheckConstraint(
                condition=(Q(kind="all") & Q(department__isnull=True)) | (Q(kind="dept") & Q(department__isnull=False)),
                name="community_board_kind_matches_department"),
        ]

    def __str__(self):
        return self.name

    @property
    def is_all(self) -> bool:
        return self.kind == self.ALL

    @property
    def name(self) -> str:
        return "전체 게시판" if self.is_all else f"{self.department.name} 게시판"

    @property
    def short_name(self) -> str:
        return "전체" if self.is_all else self.department.name


class Post(models.Model):
    FREE, QUESTION, RECRUIT, INFO = "free", "question", "recruit", "info"
    CATEGORIES = [(FREE, "자유"), (QUESTION, "질문"), (RECRUIT, "모집"), (INFO, "정보")]
    VISIBLE, HIDDEN, DELETED = "visible", "hidden", "deleted"
    STATUSES = [(VISIBLE, "공개"), (HIDDEN, "운영자·신고 숨김"), (DELETED, "삭제됨")]

    board = models.ForeignKey(Board, verbose_name="게시판", on_delete=models.PROTECT, related_name="posts")
    author = models.ForeignKey(User, verbose_name="작성 계정", on_delete=models.PROTECT, related_name="posts")
    category = models.CharField("분류", max_length=10, choices=CATEGORIES, default=FREE)
    title = models.CharField("제목", max_length=80)
    body = models.TextField("내용", max_length=5000)
    recruit_open = models.BooleanField("모집 중", null=True, blank=True)   # 모집 글에서만 사용
    status = models.CharField("상태", max_length=8, choices=STATUSES, default=VISIBLE)
    hidden_reason = models.CharField("숨김 사유", max_length=200, blank=True)
    created_at = models.DateTimeField("작성 시각", default=timezone.now)
    edited_at = models.DateTimeField("수정 시각", null=True, blank=True)
    deleted_at = models.DateTimeField("삭제 시각", null=True, blank=True)
    purged_at = models.DateTimeField("내용 삭제 시각", null=True, blank=True)
    like_count = models.PositiveIntegerField("공감 수", default=0)
    comment_count = models.PositiveIntegerField("댓글 수", default=0)

    class Meta:
        verbose_name = "게시글"
        verbose_name_plural = "게시글"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["board", "status", "-created_at"], name="post_board_recent"),
            models.Index(fields=["board", "status", "category", "-created_at"], name="post_board_cat_recent"),
            models.Index(fields=["status", "-like_count", "-created_at"], name="post_popular"),
            models.Index(fields=["author", "-created_at"], name="post_author_recent"),
        ]
        permissions = [("moderate", "신고 처리·숨김·이용 제한을 할 수 있음")]

    def __str__(self):
        return f"[{self.get_category_display()}] {self.title[:30]}"

    @property
    def is_visible(self) -> bool:
        return self.status == self.VISIBLE


class Attachment(models.Model):
    """게시글 사진. 서버가 다시 만든 JPEG 2개(본문용·썸네일)만 저장한다. 원본 파일과 원래 파일명은 저장하지 않는다."""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="attachments")
    key = models.UUIDField("공개 식별자(무작위)", default=uuid.uuid4, unique=True, editable=False)
    path = models.CharField("본문용 파일(MEDIA_ROOT 기준)", max_length=120)
    thumb_path = models.CharField("썸네일 파일(MEDIA_ROOT 기준)", max_length=120)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    size = models.PositiveIntegerField("본문용 파일 크기(bytes)")
    order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "사진"
        verbose_name_plural = "사진"
        ordering = ["order", "id"]


class PostAnon(models.Model):
    """글 하나 안에서 댓글 단 사람에게 주는 번호. 글쓴이는 번호 없이 '글쓴이'로 표시한다."""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="anons")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    number = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["post", "user"], name="community_anon_once_per_post"),
            models.UniqueConstraint(fields=["post", "number"], name="community_anon_number_unique"),
        ]


class Comment(models.Model):
    VISIBLE, HIDDEN, DELETED = "visible", "hidden", "deleted"
    STATUSES = [(VISIBLE, "공개"), (HIDDEN, "운영자·신고 숨김"), (DELETED, "삭제됨")]

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="comments")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies")
    body = models.TextField("내용", max_length=1000)
    status = models.CharField("상태", max_length=8, choices=STATUSES, default=VISIBLE)
    hidden_reason = models.CharField("숨김 사유", max_length=200, blank=True)
    created_at = models.DateTimeField("작성 시각", default=timezone.now)
    deleted_at = models.DateTimeField(null=True, blank=True)
    purged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "댓글"
        verbose_name_plural = "댓글"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["post", "created_at"], name="comment_post_time"),
            models.Index(fields=["author", "-created_at"], name="comment_author_recent"),
        ]

    def __str__(self):
        return self.body[:30]


class PostLike(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="likes")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["post", "user"], name="community_like_once")]


class Scrap(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="scraps")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="scraps")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["post", "user"], name="community_scrap_once")]


class Block(models.Model):
    """익명 사용자 차단. 화면에는 차단한 날짜와 계기(글 제목 일부)만 보여 주고 상대가 누구인지는 알려 주지 않는다."""

    blocker = models.ForeignKey(User, on_delete=models.CASCADE, related_name="blocks")
    blocked = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    source_label = models.CharField("차단 계기", max_length=60, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["blocker", "blocked"], name="community_block_once")]


class Report(models.Model):
    REASONS = [
        ("privacy", "개인정보 노출"),
        ("harass", "특정인 괴롭힘·비방"),
        ("spam", "도배·광고"),
        ("obscene", "음란·불쾌한 내용"),
        ("other", "기타"),
    ]
    OPEN, ACTED, DISMISSED = "open", "acted", "dismissed"
    STATUSES = [(OPEN, "처리 전"), (ACTED, "조치함"), (DISMISSED, "문제없음")]

    reporter = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    post = models.ForeignKey(Post, null=True, blank=True, on_delete=models.CASCADE, related_name="reports")
    comment = models.ForeignKey(Comment, null=True, blank=True, on_delete=models.CASCADE, related_name="reports")
    reason = models.CharField("이유", max_length=10, choices=REASONS)
    detail = models.CharField("설명(선택)", max_length=300, blank=True)
    status = models.CharField("처리 상태", max_length=10, choices=STATUSES, default=OPEN)
    created_at = models.DateTimeField(default=timezone.now)
    handled_at = models.DateTimeField(null=True, blank=True)
    handled_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = "신고"
        verbose_name_plural = "신고"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["reporter", "post"], condition=Q(post__isnull=False),
                                    name="community_report_post_once"),
            models.UniqueConstraint(fields=["reporter", "comment"], condition=Q(comment__isnull=False),
                                    name="community_report_comment_once"),
            models.CheckConstraint(condition=Q(post__isnull=False) ^ Q(comment__isnull=False),
                                   name="community_report_one_target"),
        ]
        indexes = [models.Index(fields=["status", "-created_at"], name="report_status_recent")]


class Notification(models.Model):
    COMMENT, REPLY = "comment", "reply"
    KINDS = [(COMMENT, "내 글에 댓글"), (REPLY, "내 댓글에 답글")]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=10, choices=KINDS)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="+")
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["user", "read_at", "-created_at"], name="notif_user_unread")]


class ModerationLog(models.Model):
    """운영자가 한 일(숨김·복구·이용 제한·해제·신고 처리)과 사유. 수정·삭제하지 않는다."""

    ACTIONS = [
        ("hide", "숨김"), ("restore", "복구"), ("remove", "삭제 확정"),
        ("restrict", "이용 제한"), ("unrestrict", "이용 제한 해제"),
        ("dismiss", "신고 문제없음 처리"), ("autohide", "신고 누적 자동 임시 숨김"),
    ]

    actor = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=12, choices=ACTIONS)
    post = models.ForeignKey(Post, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    comment = models.ForeignKey(Comment, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    taxi_room = models.ForeignKey("TaxiRoom", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    target_user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reason = models.CharField("사유", max_length=200, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "운영 기록"
        verbose_name_plural = "운영 기록"
        ordering = ["-created_at"]


# ── 번개 택시방 (택시 합승 임시 채팅, D-070) ────────────────────────────
#
# 방은 '열림' = status=open 이고 지금 < 출발 + 1시간. 시간이 지난 방은 처음 손대는 요청이 닫힘으로 저장한다(taxi.close_expired).
# 참여자 번호: 방장 0, 들어온 순서대로 1·2·3. 나갔다 다시 들어오면 같은 행·같은 번호를 쓴다.
# 닫힌(숨김 포함) 지 7일이 지나면 purge_community 가 방·참여자·메시지·신고를 지운다(처리 전 신고가 있으면 보관).


class TaxiRoom(models.Model):
    OPEN, CLOSED, HIDDEN = "open", "closed", "hidden"
    STATUSES = [(OPEN, "모집 중"), (CLOSED, "닫힘"), (HIDDEN, "운영자 숨김")]
    REASONS = [("host", "방장이 터뜨림"), ("expired", "출발 1시간 지남"), ("moderator", "운영자 숨김")]
    CAPACITIES = [(2, "2명"), (3, "3명"), (4, "4명")]

    host = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    origin = models.CharField("출발지", max_length=30)
    destination = models.CharField("도착지", max_length=30)
    departs_at = models.DateTimeField("출발 시각")
    capacity = models.PositiveSmallIntegerField("정원(방장 포함)", choices=CAPACITIES)
    note = models.CharField("한마디", max_length=40, blank=True)
    status = models.CharField("상태", max_length=8, choices=STATUSES, default=OPEN)
    close_reason = models.CharField("닫힌 이유", max_length=10, choices=REASONS, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    # 입장·메시지 처리 첫 줄에서 이 칸을 갱신해 SQLite 쓰기 잠금을 먼저 잡는다 → 같은 방 요청이 한 줄로 처리된다
    touched_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "택시방"
        verbose_name_plural = "택시방"
        ordering = ["departs_at", "id"]
        indexes = [models.Index(fields=["status", "departs_at"], name="taxi_status_departs")]

    def __str__(self):
        return f"{self.departs_at:%m/%d %H:%M} {self.origin} → {self.destination}"

    @property
    def closes_at(self):
        from datetime import timedelta
        return self.departs_at + timedelta(hours=1)


class TaxiMember(models.Model):
    room = models.ForeignKey(TaxiRoom, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    number = models.PositiveSmallIntegerField("방 안 번호")   # 0 = 방장
    joined_at = models.DateTimeField(default=timezone.now)
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(fields=["room", "user"], name="taxi_member_once"),
            models.UniqueConstraint(fields=["room", "number"], name="taxi_member_number_once"),
        ]


class TaxiMessage(models.Model):
    TEXT, SYSTEM = "text", "system"
    KINDS = [(TEXT, "대화"), (SYSTEM, "안내")]

    room = models.ForeignKey(TaxiRoom, on_delete=models.CASCADE, related_name="messages")
    member = models.ForeignKey(TaxiMember, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=8, choices=KINDS, default=TEXT)
    body = models.CharField("내용", max_length=200)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["id"]


class TaxiReport(models.Model):
    """택시방·메시지 신고. 기존 Report 의 제약을 바꾸지 않으려고 따로 둔다(선택지는 Report 와 같다)."""

    reporter = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    room = models.ForeignKey(TaxiRoom, on_delete=models.CASCADE, related_name="reports")
    message = models.ForeignKey(TaxiMessage, null=True, blank=True, on_delete=models.CASCADE, related_name="reports")
    reason = models.CharField("이유", max_length=10, choices=Report.REASONS)
    detail = models.CharField("설명(선택)", max_length=300, blank=True)
    status = models.CharField("처리 상태", max_length=10, choices=Report.STATUSES, default=Report.OPEN)
    created_at = models.DateTimeField(default=timezone.now)
    handled_at = models.DateTimeField(null=True, blank=True)
    handled_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = "택시방 신고"
        verbose_name_plural = "택시방 신고"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["reporter", "room"], condition=Q(message__isnull=True),
                                    name="taxi_report_room_once"),
            models.UniqueConstraint(fields=["reporter", "message"], condition=Q(message__isnull=False),
                                    name="taxi_report_message_once"),
        ]
