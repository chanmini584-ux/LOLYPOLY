"""커뮤니티의 변경 작업(글·댓글·공감·신고·차단·운영 처리). 뷰는 권한을 확인한 뒤 여기 함수를 부른다.

DB 변경과 사진 파일 변경이 어긋나지 않게: 사진은 먼저 검사·재인코딩(메모리)하고, DB 저장이 실패하면
방금 쓴 파일을 지운다. 파일 삭제는 DB 커밋이 끝난 뒤(on_commit)에 한다.
"""

from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from . import images
from .models import (Attachment, Block, Comment, ModerationLog, Notification, Post, PostAnon, PostLike, Report,
                     Scrap)


class Rejected(Exception):
    """사용자에게 보여 줄 수 있는 거절 사유(도배 제한, 사진 문제 등)."""


# ── 도배 제한: 계정 기준 ─────────────────────────────

def _too_many(queryset, limit: int, window_sec: int) -> bool:
    since = timezone.now() - timedelta(seconds=window_sec)
    return queryset.filter(created_at__gte=since).count() >= limit


def check_post_rate(user) -> None:
    if _too_many(Post.objects.filter(author=user), settings.COMMUNITY_POST_LIMIT, settings.COMMUNITY_POST_WINDOW_SEC):
        raise Rejected("글을 너무 자주 올리고 있어요. 잠시 뒤에 다시 써 주세요.")


def check_comment_rate(user) -> None:
    if _too_many(Comment.objects.filter(author=user), settings.COMMUNITY_COMMENT_LIMIT,
                 settings.COMMUNITY_COMMENT_WINDOW_SEC):
        raise Rejected("댓글을 너무 자주 달고 있어요. 잠시 뒤에 다시 써 주세요.")


def check_report_rate(user) -> None:
    if _too_many(Report.objects.filter(reporter=user), settings.COMMUNITY_REPORT_LIMIT, 3600):
        raise Rejected("신고를 너무 자주 하고 있어요. 잠시 뒤에 다시 해 주세요.")


# ── 사진 ─────────────────────────────────────────────

def _process_uploads(uploads, already: int = 0) -> list[images.Processed]:
    uploads = [u for u in uploads if u]
    if already + len(uploads) > settings.COMMUNITY_PHOTO_MAX_COUNT:
        raise Rejected(f"사진은 글 하나에 {settings.COMMUNITY_PHOTO_MAX_COUNT}장까지 올릴 수 있어요.")
    done = []
    for i, upload in enumerate(uploads, start=1):
        try:
            done.append(images.process(upload))
        except images.ImageRejected as exc:
            raise Rejected(f"{i}번째 사진: {exc}") from None
    return done


def _attach(post: Post, processed: list[images.Processed], start_order: int) -> list[str]:
    """사진을 저장하고 Attachment 를 만든다. 실패하면 호출한 쪽이 돌려받은 경로를 지울 수 있게 경로를 모은다."""
    written: list[str] = []
    for offset, item in enumerate(processed):
        key, main_rel, thumb_rel = images.store(item)
        written += [main_rel, thumb_rel]
        Attachment.objects.create(post=post, key=key, path=main_rel, thumb_path=thumb_rel, width=item.width,
                                  height=item.height, size=len(item.main), order=start_order + offset)
    return written


def _drop_attachments(attachments) -> None:
    paths = []
    for a in attachments:
        paths += [a.path, a.thumb_path]
        a.delete()
    if paths:
        transaction.on_commit(lambda: images.remove_files(*paths))


# ── 글 ───────────────────────────────────────────────

def create_post(user, board, *, category, title, body, recruit_open=None, uploads=()) -> Post:
    check_post_rate(user)
    processed = _process_uploads(uploads)
    written: list[str] = []
    try:
        with transaction.atomic():
            post = Post.objects.create(board=board, author=user, category=category, title=title, body=body,
                                       recruit_open=(True if recruit_open is None else recruit_open)
                                       if category == Post.RECRUIT else None)
            written = _attach(post, processed, 0)
    except Exception:
        images.remove_files(*written)
        raise
    return post


def update_post(post: Post, *, category, title, body, recruit_open=None, remove_keys=(), uploads=()) -> Post:
    keep = [a for a in post.attachments.all() if str(a.key) not in set(remove_keys)]
    processed = _process_uploads(uploads, already=len(keep))
    written: list[str] = []
    try:
        with transaction.atomic():
            _drop_attachments([a for a in post.attachments.all() if str(a.key) in set(remove_keys)])
            post.category, post.title, post.body = category, title, body
            post.recruit_open = (post.recruit_open if recruit_open is None else recruit_open) \
                if category == Post.RECRUIT else None
            if post.category == Post.RECRUIT and post.recruit_open is None:
                post.recruit_open = True
            post.edited_at = timezone.now()
            post.save()
            last = post.attachments.aggregate(m=Max("order"))["m"]
            written = _attach(post, processed, (last + 1) if last is not None else 0)
    except Exception:
        images.remove_files(*written)
        raise
    return post


def purge_post(post: Post) -> None:
    """글 내용과 사진을 실제로 지운다(행은 남겨 댓글 수·기록이 어긋나지 않게 한다)."""
    with transaction.atomic():
        _drop_attachments(list(post.attachments.all()))
        post.title, post.body = "(삭제된 글)", ""
        post.purged_at = timezone.now()
        post.save(update_fields=["title", "body", "purged_at"])
        PostLike.objects.filter(post=post).delete()
        Scrap.objects.filter(post=post).delete()
        Notification.objects.filter(post=post).delete()


def purge_comment(comment: Comment) -> None:
    comment.body = ""
    comment.purged_at = timezone.now()
    comment.save(update_fields=["body", "purged_at"])
    Notification.objects.filter(comment=comment).delete()


def delete_post(post: Post) -> None:
    """작성자 삭제. 처리 전 신고가 있으면 운영자 검토 기간 동안만 숨긴 채 둔다."""
    with transaction.atomic():
        post.status = Post.DELETED
        post.deleted_at = timezone.now()
        post.save(update_fields=["status", "deleted_at"])
        if not post.reports.filter(status=Report.OPEN).exists():
            purge_post(post)


def delete_comment(comment: Comment) -> None:
    with transaction.atomic():
        was_visible = comment.status == Comment.VISIBLE
        comment.status = Comment.DELETED
        comment.deleted_at = timezone.now()
        comment.save(update_fields=["status", "deleted_at"])
        if not comment.reports.filter(status=Report.OPEN).exists():
            purge_comment(comment)
        if was_visible:
            _recount_comments(comment.post_id)


def _recount_comments(post_id: int) -> None:
    n = Comment.objects.filter(post_id=post_id, status=Comment.VISIBLE).count()
    Post.objects.filter(pk=post_id).update(comment_count=n)


def set_recruit(post: Post, is_open: bool) -> None:
    Post.objects.filter(pk=post.pk, category=Post.RECRUIT).update(recruit_open=is_open)


# ── 익명 번호 ────────────────────────────────────────

def anon_number(post: Post, user) -> int:
    """이 글에서 이 사람이 쓸 익명 번호(없으면 새로 매김). 글쓴이는 0."""
    if post.author_id == user.id:
        return 0
    existing = PostAnon.objects.filter(post=post, user=user).values_list("number", flat=True).first()
    if existing is not None:
        return existing
    for _ in range(5):                    # 동시에 두 사람이 처음 댓글을 달아도 번호가 겹치지 않게
        number = (PostAnon.objects.filter(post=post).aggregate(m=Max("number"))["m"] or 0) + 1
        try:
            with transaction.atomic():
                return PostAnon.objects.create(post=post, user=user, number=number).number
        except IntegrityError:
            mine = PostAnon.objects.filter(post=post, user=user).values_list("number", flat=True).first()
            if mine is not None:
                return mine
    raise Rejected("잠시 뒤에 다시 시도해 주세요.")


def anon_labels(post: Post) -> dict[int, str]:
    """{계정 id: '글쓴이' | '익명N'} — 템플릿에는 이 이름만 넘긴다."""
    labels = {uid: f"익명{n}" for uid, n in PostAnon.objects.filter(post=post).values_list("user_id", "number")}
    labels[post.author_id] = "글쓴이"
    return labels


# ── 댓글·알림 ────────────────────────────────────────

def add_comment(user, post: Post, body: str, parent: Comment | None = None) -> Comment:
    check_comment_rate(user)
    with transaction.atomic():
        anon_number(post, user)
        comment = Comment.objects.create(post=post, author=user, parent=parent, body=body)
        _recount_comments(post.pk)
        notify: dict[int, str] = {}
        if post.author_id != user.id:
            notify[post.author_id] = Notification.COMMENT
        if parent is not None and parent.author_id != user.id and parent.status == Comment.VISIBLE:
            notify[parent.author_id] = Notification.REPLY     # 글쓴이이면서 부모 댓글 작성자면 '답글' 하나만
        if notify:
            muted = set(Block.objects.filter(blocker_id__in=notify, blocked=user).values_list("blocker_id", flat=True))
            Notification.objects.bulk_create([
                Notification(user_id=uid, kind=kind, post=post, comment=comment)
                for uid, kind in notify.items() if uid not in muted
            ])
    return comment


# ── 공감·스크랩 ──────────────────────────────────────

def toggle_like(user, post: Post) -> bool:
    """공감을 켜거나 끈다. 켜진 상태면 True. 같은 요청이 겹쳐도 계정당 1개(UNIQUE)이고 수는 다시 센다."""
    with transaction.atomic():
        deleted, _ = PostLike.objects.filter(post=post, user=user).delete()
        liked = False
        if not deleted:
            try:
                with transaction.atomic():
                    PostLike.objects.create(post=post, user=user)
            except IntegrityError:
                pass
            liked = True
        Post.objects.filter(pk=post.pk).update(like_count=PostLike.objects.filter(post=post).count())
    return liked


def toggle_scrap(user, post: Post) -> bool:
    with transaction.atomic():
        deleted, _ = Scrap.objects.filter(post=post, user=user).delete()
        if deleted:
            return False
        try:
            with transaction.atomic():
                Scrap.objects.create(post=post, user=user)
        except IntegrityError:
            pass
        return True


# ── 신고·차단 ────────────────────────────────────────

def report(user, *, post: Post | None = None, comment: Comment | None = None, reason: str, detail: str = "") -> bool:
    """신고 접수. 이미 신고한 대상이면 False(중복 저장 안 함)."""
    target = {"post": post} if post is not None else {"comment": comment}
    if Report.objects.filter(reporter=user, **target).exists():
        return False
    check_report_rate(user)
    try:
        with transaction.atomic():
            Report.objects.create(reporter=user, reason=reason, detail=detail, **target)
    except IntegrityError:
        return False
    _auto_hide(post=post, comment=comment)
    return True


def _auto_hide(*, post=None, comment=None) -> None:
    """서로 다른 계정의 처리 전 신고가 기준 이상 모이면 '임시'로 숨기고 운영자 확인을 기다린다(영구 제재 아님)."""
    threshold = settings.COMMUNITY_REPORT_AUTOHIDE
    if threshold <= 0:
        return
    obj = post if post is not None else comment
    if obj.status != obj.VISIBLE or obj.reports.filter(status=Report.OPEN).count() < threshold:
        return
    obj.status = obj.HIDDEN
    obj.hidden_reason = "신고가 여러 건 접수되어 운영자 확인 전까지 임시로 숨겼어요."
    obj.save(update_fields=["status", "hidden_reason"])
    ModerationLog.objects.create(actor=None, action="autohide", post=post, comment=comment,
                                 target_user_id=obj.author_id, reason=f"처리 전 신고 {threshold}건 이상")
    if comment is not None:
        _recount_comments(comment.post_id)


def block(user, target_user_id: int, label: str) -> bool:
    if target_user_id == user.id:
        return False
    _, created = Block.objects.get_or_create(blocker=user, blocked_id=target_user_id,
                                             defaults={"source_label": label[:60]})
    return created


def blocked_ids(user) -> set[int]:
    return set(Block.objects.filter(blocker=user).values_list("blocked_id", flat=True))


# ── 운영자 처리 ──────────────────────────────────────

def _close_reports(obj, moderator, status: str) -> None:
    obj.reports.filter(status=Report.OPEN).update(status=status, handled_at=timezone.now(), handled_by=moderator)


def moderate_hide(moderator, obj, reason: str) -> None:
    is_post = isinstance(obj, Post)
    with transaction.atomic():
        obj.status = obj.HIDDEN
        obj.hidden_reason = reason[:200] or "운영 규칙에 따라 숨겼어요."
        obj.save(update_fields=["status", "hidden_reason"])
        _close_reports(obj, moderator, Report.ACTED)
        ModerationLog.objects.create(actor=moderator, action="hide", post=obj if is_post else None,
                                     comment=None if is_post else obj, target_user_id=obj.author_id, reason=reason[:200])
        if not is_post:
            _recount_comments(obj.post_id)


def moderate_restore(moderator, obj, reason: str) -> None:
    is_post = isinstance(obj, Post)
    with transaction.atomic():
        if obj.status != obj.HIDDEN:
            return
        obj.status = obj.VISIBLE
        obj.hidden_reason = ""
        obj.save(update_fields=["status", "hidden_reason"])
        _close_reports(obj, moderator, Report.DISMISSED)
        ModerationLog.objects.create(actor=moderator, action="restore", post=obj if is_post else None,
                                     comment=None if is_post else obj, target_user_id=obj.author_id, reason=reason[:200])
        if not is_post:
            _recount_comments(obj.post_id)


def moderate_remove(moderator, obj, reason: str) -> None:
    """숨긴 글·댓글을 삭제 확정: 내용과 사진을 지운다(되돌릴 수 없음)."""
    is_post = isinstance(obj, Post)
    with transaction.atomic():
        was_visible = obj.status == obj.VISIBLE
        obj.status = obj.DELETED
        obj.deleted_at = timezone.now()
        obj.save(update_fields=["status", "deleted_at"])
        _close_reports(obj, moderator, Report.ACTED)
        ModerationLog.objects.create(actor=moderator, action="remove", post=obj if is_post else None,
                                     comment=None if is_post else obj, target_user_id=obj.author_id, reason=reason[:200])
        if is_post:
            purge_post(obj)
        else:
            purge_comment(obj)
            if was_visible:
                _recount_comments(obj.post_id)


def moderate_dismiss(moderator, obj, reason: str) -> None:
    is_post = isinstance(obj, Post)
    with transaction.atomic():
        _close_reports(obj, moderator, Report.DISMISSED)
        ModerationLog.objects.create(actor=moderator, action="dismiss", post=obj if is_post else None,
                                     comment=None if is_post else obj, target_user_id=obj.author_id, reason=reason[:200])
        # 작성자가 이미 지운 글이면 검토가 끝났으므로 내용도 지운다
        if obj.status == obj.DELETED and not obj.purged_at:
            purge_post(obj) if is_post else purge_comment(obj)


def moderate_restrict(moderator, author_id: int, days: int, reason: str, *, post=None, comment=None) -> None:
    from accounts.models import User

    until = timezone.now() + timedelta(days=days)
    User.objects.filter(pk=author_id).update(restricted_until=until, restriction_reason=reason[:200])
    ModerationLog.objects.create(actor=moderator, action="restrict", post=post, comment=comment,
                                 target_user_id=author_id, reason=f"{days}일: {reason}"[:200])


def moderate_unrestrict(moderator, author_id: int, reason: str, *, post=None, comment=None) -> None:
    from accounts.models import User

    User.objects.filter(pk=author_id).update(restricted_until=None, restriction_reason="")
    ModerationLog.objects.create(actor=moderator, action="unrestrict", post=post, comment=comment,
                                 target_user_id=author_id, reason=reason[:200])


# ── 탈퇴·보관 기간 정리 ──────────────────────────────

def purge_user_content(user) -> None:
    """탈퇴: 내 글·댓글·사진을 지우고, 공감·스크랩·차단·알림 기록을 없앤다."""
    now = timezone.now()
    for post in Post.objects.filter(author=user, purged_at__isnull=True):
        post.status, post.deleted_at = Post.DELETED, post.deleted_at or now
        post.save(update_fields=["status", "deleted_at"])
        purge_post(post)
    touched = set()
    for comment in Comment.objects.filter(author=user, purged_at__isnull=True):
        comment.status, comment.deleted_at = Comment.DELETED, comment.deleted_at or now
        comment.save(update_fields=["status", "deleted_at"])
        purge_comment(comment)
        touched.add(comment.post_id)
    for post_id in touched:
        _recount_comments(post_id)
    liked = list(PostLike.objects.filter(user=user).values_list("post_id", flat=True))
    PostLike.objects.filter(user=user).delete()
    for post_id in liked:
        Post.objects.filter(pk=post_id).update(like_count=PostLike.objects.filter(post_id=post_id).count())
    Scrap.objects.filter(user=user).delete()
    Block.objects.filter(blocker=user).delete()
    Block.objects.filter(blocked=user).delete()
    Notification.objects.filter(user=user).delete()
    PostAnon.objects.filter(user=user).delete()


def purge_expired(now=None) -> tuple[int, int]:
    """작성자가 지웠지만 신고 검토 때문에 남겨 둔 글·댓글을 보관 기간이 지나면 지운다."""
    cutoff = (now or timezone.now()) - timedelta(days=settings.COMMUNITY_REVIEW_RETENTION_DAYS)
    posts = list(Post.objects.filter(status=Post.DELETED, purged_at__isnull=True, deleted_at__lt=cutoff))
    for post in posts:
        purge_post(post)
    comments = list(Comment.objects.filter(status=Comment.DELETED, purged_at__isnull=True, deleted_at__lt=cutoff))
    for comment in comments:
        purge_comment(comment)
    return len(posts), len(comments)
