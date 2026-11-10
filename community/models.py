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
    target_user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reason = models.CharField("사유", max_length=200, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "운영 기록"
        verbose_name_plural = "운영 기록"
        ordering = ["-created_at"]
