"""커뮤니티 화면.

모든 화면은 로그인이 필요하다(@member). 변경 요청은 POST + CSRF 이고, 누가 무엇을 할 수 있는지는
community/policy.py 가 서버에서 판정한다. 요청에 담긴 작성자·학과·게시판 값은 믿지 않고
'지금 로그인한 계정'과 'URL 이 가리키는 글·게시판'만으로 판단한다.
"""

from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.views import safe_next

from . import images, policy, services
from .forms import CommentForm, ModerationForm, PostForm, ReportForm
from .models import Attachment, Block, Board, Comment, Notification, Post, Report, Scrap

PAGE_SIZE = 20
CATEGORY_LABELS = dict(Post.CATEGORIES)


def member(view):
    """로그인한 정상 계정만. (탈퇴·비활성 계정은 Django 가 세션을 인정하지 않아 로그인 화면으로 간다.)"""
    return login_required(view)


def moderator(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not policy.is_moderator(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def _boards():
    return list(Board.objects.select_related("department").order_by("kind", "department__order", "department__name"))


def _post_queryset(user):
    """목록·검색·인기글 공통: 공개 글만, 내가 차단한 사람의 글 제외."""
    qs = Post.objects.filter(status=Post.VISIBLE)
    blocked = services.blocked_ids(user)
    if blocked:
        qs = qs.exclude(author_id__in=blocked)
    return qs


def _with_list_extras(qs):
    first_photo = Prefetch("attachments", queryset=Attachment.objects.order_by("order", "id"))
    return qs.select_related("board", "board__department").prefetch_related(first_photo)


def _paginate(request, qs):
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return page, params.urlencode()


def _unread(user) -> int:
    return Notification.objects.filter(user=user, read_at__isnull=True).count()


# ── 게시판 ───────────────────────────────────────────

@member
def home(request):
    boards = _boards()
    mine = next((b for b in boards if b.department_id and b.department_id == request.user.department_id), None)
    others = [b for b in boards if not b.is_all and b is not mine and b.department.is_active]
    popular = _with_list_extras(_post_queryset(request.user).filter(
        like_count__gt=0, created_at__gte=timezone.now() - timedelta(days=14),
    ).order_by("-like_count", "-comment_count", "-created_at"))[:5]
    return render(request, "community/home.html", {
        "page_title": "커뮤니티",
        "all_board": next(b for b in boards if b.is_all),
        "my_board": mine,
        "other_boards": others,
        "popular": popular,
        "unread": _unread(request.user),
    })


@member
def board(request, slug):
    board_obj = get_object_or_404(Board.objects.select_related("department"), slug=slug)
    qs = _post_queryset(request.user).filter(board=board_obj)
    category = request.GET.get("cat", "")
    if category in CATEGORY_LABELS:
        qs = qs.filter(category=category)
    else:
        category = ""
    query = (request.GET.get("q") or "").strip()[:50]
    if len(query) >= 2:
        qs = qs.filter(Q(title__icontains=query) | Q(body__icontains=query))
    sort = "popular" if request.GET.get("sort") == "popular" else "recent"
    qs = qs.order_by("-like_count", "-comment_count", "-created_at") if sort == "popular" else qs.order_by("-created_at", "-id")
    page, params = _paginate(request, _with_list_extras(qs))
    boards = _boards()
    return render(request, "community/board.html", {
        "page_title": board_obj.name,
        "board": board_obj,
        "boards": [b for b in boards if b.is_all or b.department.is_active or b == board_obj],
        "is_mine": bool(board_obj.department_id and board_obj.department_id == request.user.department_id),
        "categories": Post.CATEGORIES, "category": category, "sort": sort, "query": query,
        "query_too_short": bool(request.GET.get("q")) and len(query) < 2,
        "page": page, "params": params,
        "write_block": policy.write_block_reason(request.user, board_obj),
    })


@member
def search(request):
    query = (request.GET.get("q") or "").strip()[:50]
    page, params = None, ""
    if len(query) >= 2:
        qs = _post_queryset(request.user).filter(Q(title__icontains=query) | Q(body__icontains=query))
        page, params = _paginate(request, _with_list_extras(qs.order_by("-created_at", "-id")))
    return render(request, "community/search.html", {
        "page_title": "검색", "query": query, "page": page, "params": params,
        "query_too_short": bool(request.GET.get("q")) and len(query) < 2,
    })


# ── 글 ───────────────────────────────────────────────

def _get_post(pk) -> Post:
    return get_object_or_404(Post.objects.select_related("board", "board__department"), pk=pk)


def _readable_post(request, pk) -> Post:
    """다른 사람이 읽을 수 있는 공개 글만. 숨김·삭제 글은 404(작성자·운영자 전용 화면은 따로 처리)."""
    post = _get_post(pk)
    if post.status != Post.VISIBLE:
        raise Http404("볼 수 없는 글")
    return post


def _unavailable(request, post: Post):
    mine = post.author_id == request.user.id
    return render(request, "community/unavailable.html", {
        "page_title": "볼 수 없는 글", "post": post, "mine": mine, "board": post.board,
        "is_moderator": policy.is_moderator(request.user),
    }, status=404)


@member
def post_detail(request, pk):
    post = _get_post(pk)
    if post.status != Post.VISIBLE:
        return _unavailable(request, post)
    user = request.user
    blocked = services.blocked_ids(user)
    labels = services.anon_labels(post)
    top, replies = [], {}
    for c in post.comments.all():
        c.label = labels.get(c.author_id, "익명")
        c.is_mine = c.author_id == user.id
        c.is_blocked = c.author_id in blocked
        c.shown = c.status == Comment.VISIBLE and not c.is_blocked
        if c.parent_id:
            replies.setdefault(c.parent_id, []).append(c)
        else:
            top.append(c)
    for c in top:
        c.children = replies.get(c.pk, [])
    # 지워진 댓글은 답글이 달려 있을 때만 '삭제된 댓글' 자리 표시로 남긴다(대화 맥락 유지)
    top = [c for c in top if c.shown or c.children]
    Notification.objects.filter(user=user, post=post, read_at__isnull=True).update(read_at=timezone.now())
    return render(request, "community/post_detail.html", {
        "page_title": post.board.name, "post": post, "board": post.board,
        "attachments": list(post.attachments.all()),
        "comments": top,
        "author_blocked": post.author_id in blocked,
        "is_mine": post.author_id == user.id,
        "can_edit": policy.can_edit_post(user, post),
        "liked": post.likes.filter(user=user).exists(),
        "scrapped": post.scraps.filter(user=user).exists(),
        "write_block": policy.write_block_reason(user, post.board),
        "comment_form": CommentForm(),
        "is_moderator": policy.is_moderator(user),
    })


def _post_form_response(request, form, board_obj, post=None, status=200):
    return render(request, "community/post_form.html", {
        "page_title": "글 수정" if post else "글쓰기", "form": form, "board": board_obj, "post": post,
        "attachments": list(post.attachments.all()) if post else [],
        "max_count": settings.COMMUNITY_PHOTO_MAX_COUNT,
        "max_mb": settings.COMMUNITY_PHOTO_MAX_BYTES // (1024 * 1024),
    }, status=status)


@member
def post_create(request, slug):
    board_obj = get_object_or_404(Board.objects.select_related("department"), slug=slug)
    reason = policy.write_block_reason(request.user, board_obj)
    if reason:
        if request.method == "POST":
            raise PermissionDenied(reason)
        messages.error(request, reason)
        return redirect("community:board", slug=board_obj.slug)
    form = PostForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            post = services.create_post(request.user, board_obj, category=data["category"], title=data["title"],
                                        body=data["body"], recruit_open=data["recruit_open"], uploads=data["photos"])
        except services.Rejected as exc:
            form.add_error(None, str(exc))
        else:
            return redirect("community:post", pk=post.pk)
    return _post_form_response(request, form, board_obj, status=400 if form.errors else 200)


@member
def post_edit(request, pk):
    post = _get_post(pk)
    if not policy.can_edit_post(request.user, post):
        raise PermissionDenied("이 글을 수정할 수 없어요.")
    if request.method == "POST":
        form = PostForm(request.POST, request.FILES)
        if form.is_valid():
            data = form.cleaned_data
            mine = {str(a.key) for a in post.attachments.all()}
            remove = [k for k in request.POST.getlist("remove_photo") if k in mine]   # 이 글의 사진만
            try:
                services.update_post(post, category=data["category"], title=data["title"], body=data["body"],
                                     recruit_open=data["recruit_open"], remove_keys=remove, uploads=data["photos"])
            except services.Rejected as exc:
                form.add_error(None, str(exc))
            else:
                return redirect("community:post", pk=post.pk)
    else:
        form = PostForm(initial={"category": post.category, "title": post.title, "body": post.body,
                                 "recruit_open": "" if post.recruit_open is None else ("1" if post.recruit_open else "0")})
    return _post_form_response(request, form, post.board, post=post, status=400 if form.errors else 200)


@member
@require_POST
def post_delete(request, pk):
    post = _get_post(pk)
    if not policy.can_delete_post(request.user, post):
        raise PermissionDenied("이 글을 지울 수 없어요.")
    services.delete_post(post)
    messages.success(request, "글을 지웠어요.")
    return redirect("community:board", slug=post.board.slug)


@member
@require_POST
def post_recruit(request, pk):
    post = _get_post(pk)
    if not policy.can_edit_post(request.user, post) or post.category != Post.RECRUIT:
        raise PermissionDenied
    services.set_recruit(post, request.POST.get("open") == "1")
    return redirect("community:post", pk=post.pk)


@member
@require_POST
def post_like(request, pk):
    post = _readable_post(request, pk)
    services.toggle_like(request.user, post)
    return redirect(safe_next(request, reverse("community:post", args=[post.pk])))


@member
@require_POST
def post_scrap(request, pk):
    post = _readable_post(request, pk)
    services.toggle_scrap(request.user, post)
    return redirect(safe_next(request, reverse("community:post", args=[post.pk])))


# ── 댓글 ─────────────────────────────────────────────

@member
@require_POST
def comment_create(request, pk):
    post = _readable_post(request, pk)
    reason = policy.write_block_reason(request.user, post.board)
    if reason:
        raise PermissionDenied(reason)
    parent = None
    parent_id = request.POST.get("parent")
    if parent_id:
        # 부모 댓글은 반드시 '이 글'의 최상위 공개 댓글이어야 한다(다른 글의 댓글 번호를 넣어도 통하지 않게)
        parent = get_object_or_404(Comment, pk=parent_id, post=post, parent__isnull=True, status=Comment.VISIBLE)
    form = CommentForm(request.POST)
    if not form.is_valid():
        messages.error(request, "댓글 내용을 1,000자 안으로 적어 주세요.")
        return redirect("community:post", pk=post.pk)
    try:
        comment = services.add_comment(request.user, post, form.cleaned_data["body"], parent)
    except services.Rejected as exc:
        messages.error(request, str(exc))
        return redirect("community:post", pk=post.pk)
    return redirect(reverse("community:post", args=[post.pk]) + f"#c{comment.pk}")


@member
@require_POST
def comment_delete(request, pk):
    comment = get_object_or_404(Comment.objects.select_related("post"), pk=pk)
    if not policy.can_delete_comment(request.user, comment):
        raise PermissionDenied("이 댓글을 지울 수 없어요.")
    services.delete_comment(comment)
    return redirect("community:post", pk=comment.post_id)


# ── 신고·차단 ────────────────────────────────────────

def _report_target(request, kind, pk):
    if kind == "post":
        return _readable_post(request, pk), None
    comment = get_object_or_404(Comment.objects.select_related("post", "post__board"), pk=pk, status=Comment.VISIBLE)
    if comment.post.status != Post.VISIBLE:
        raise Http404
    return None, comment


@member
def report(request, kind, pk):
    post, comment = _report_target(request, kind, pk)
    target = post or comment
    back = reverse("community:post", args=[post.pk if post else comment.post_id])
    if target.author_id == request.user.id:
        messages.error(request, "내가 쓴 글·댓글은 신고할 수 없어요. 지우고 싶으면 삭제를 눌러 주세요.")
        return redirect(back)
    form = ReportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            created = services.report(request.user, post=post, comment=comment, reason=form.cleaned_data["reason"],
                                      detail=form.cleaned_data["detail"])
        except services.Rejected as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "신고를 접수했어요. 운영자가 확인할게요." if created else "이미 신고한 글·댓글이에요.")
        target.refresh_from_db()
        if post is not None and post.status != Post.VISIBLE:      # 신고 누적으로 방금 임시 숨김된 경우
            return redirect("community:board", slug=post.board.slug)
        return redirect(back)
    return render(request, "community/report.html", {
        "page_title": "신고", "form": form, "kind": kind, "target": target, "back": back,
        "preview": (post.title if post else comment.body)[:60],
    })


@member
@require_POST
def block(request, kind, pk):
    post, comment = _report_target(request, kind, pk)
    target = post or comment
    label = (post.title if post else comment.body)[:40]
    back = reverse("community:board", args=[post.board.slug]) if post else reverse("community:post", args=[comment.post_id])
    if target.author_id == request.user.id:
        messages.error(request, "나 자신은 차단할 수 없어요.")
        return redirect(back)
    services.block(request.user, target.author_id, label)
    messages.success(request, "이 사용자의 글·댓글이 이제 보이지 않아요. MY의 차단 목록에서 풀 수 있어요.")
    return redirect(back)


@member
@require_POST
def unblock(request, pk):
    Block.objects.filter(pk=pk, blocker=request.user).delete()
    return redirect("community:blocks")


# ── 사진: 로그인 + 글 열람 권한이 있을 때만 ──────────

@member
def photo(request, key, thumb=False):
    attachment = get_object_or_404(Attachment.objects.select_related("post"), key=key)
    post = attachment.post
    allowed = post.status == Post.VISIBLE or policy.is_moderator(request.user) or \
        (post.author_id == request.user.id and post.status == Post.HIDDEN)
    if not allowed:
        raise Http404
    path = images.media_root() / (attachment.thumb_path if thumb else attachment.path)
    if not path.is_file():
        raise Http404
    response = FileResponse(path.open("rb"), content_type="image/jpeg")
    response["Content-Disposition"] = 'inline; filename="photo.jpg"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response      # Cache-Control: no-store, private 는 PrivateCacheMiddleware 가 붙인다


# ── 내 활동·알림 ─────────────────────────────────────

@member
def my_posts(request):
    qs = Post.objects.filter(author=request.user).exclude(status=Post.DELETED).order_by("-created_at")
    page, params = _paginate(request, _with_list_extras(qs))
    return render(request, "community/my_list.html", {"page_title": "내가 쓴 글", "page": page, "params": params,
                                                     "kind": "posts", "empty": "아직 쓴 글이 없어요."})


@member
def my_comments(request):
    qs = Comment.objects.filter(author=request.user, status=Comment.VISIBLE, post__status=Post.VISIBLE) \
        .select_related("post", "post__board", "post__board__department").order_by("-created_at")
    page, params = _paginate(request, qs)
    return render(request, "community/my_list.html", {"page_title": "내가 쓴 댓글", "page": page, "params": params,
                                                     "kind": "comments", "empty": "아직 쓴 댓글이 없어요."})


@member
def my_scraps(request):
    qs = _post_queryset(request.user).filter(scraps__user=request.user).order_by("-scraps__created_at")
    page, params = _paginate(request, _with_list_extras(qs))
    return render(request, "community/my_list.html", {"page_title": "스크랩", "page": page, "params": params,
                                                     "kind": "posts", "empty": "스크랩한 글이 없어요."})


@member
def blocks(request):
    return render(request, "community/blocks.html", {"page_title": "차단 목록",
                                                    "blocks": Block.objects.filter(blocker=request.user)})


@member
def notifications(request):
    qs = Notification.objects.filter(user=request.user).select_related("post", "comment")
    page, params = _paginate(request, qs)
    blocked = services.blocked_ids(request.user)
    for n in page:
        # 지워졌거나 숨겨진 글·댓글의 알림은 내용을 보여 주지 않는다
        n.available = (n.post.status == Post.VISIBLE and n.comment.status == Comment.VISIBLE
                       and n.comment.author_id not in blocked)
        n.unread = n.read_at is None
    response = render(request, "community/notifications.html", {"page_title": "알림", "page": page, "params": params})
    Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
    return response


def rules(request):
    """이용 규칙·익명성 범위·보관 안내. 가입 전에도 읽을 수 있게 로그인 없이 연다."""
    return render(request, "community/rules.html", {
        "page_title": "커뮤니티 이용 규칙",
        "retention_days": settings.COMMUNITY_REVIEW_RETENTION_DAYS,
        "autohide": settings.COMMUNITY_REPORT_AUTOHIDE,
    })


# ── 운영자 ───────────────────────────────────────────

@moderator
def manage_reports(request):
    show = "all" if request.GET.get("show") == "all" else "open"
    posts = Post.objects.annotate(open_reports=Count("reports", filter=Q(reports__status=Report.OPEN)),
                                  total_reports=Count("reports"))
    comments = Comment.objects.select_related("post").annotate(
        open_reports=Count("reports", filter=Q(reports__status=Report.OPEN)), total_reports=Count("reports"))
    if show == "open":
        posts = posts.filter(Q(open_reports__gt=0) | Q(status=Post.HIDDEN))
        comments = comments.filter(Q(open_reports__gt=0) | Q(status=Comment.HIDDEN))
    else:
        posts, comments = posts.filter(total_reports__gt=0), comments.filter(total_reports__gt=0)
    return render(request, "community/manage_reports.html", {
        "page_title": "신고 관리", "show": show,
        "posts": posts.select_related("board", "board__department").order_by("-open_reports", "-created_at")[:100],
        "comments": comments.order_by("-open_reports", "-created_at")[:100],
    })


@moderator
def manage_target(request, kind, pk):
    if kind == "post":
        obj = get_object_or_404(Post.objects.select_related("board", "board__department", "author"), pk=pk)
        post, comment = obj, None
    else:
        obj = get_object_or_404(Comment.objects.select_related("post", "author"), pk=pk)
        post, comment = obj.post, obj
    form = ModerationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        action, reason = form.cleaned_data["action"], form.cleaned_data["reason"]
        kwargs = {"post": post if kind == "post" else None, "comment": comment}
        if action == "hide":
            services.moderate_hide(request.user, obj, reason)
        elif action == "restore":
            services.moderate_restore(request.user, obj, reason)
        elif action == "remove":
            services.moderate_remove(request.user, obj, reason)
        elif action == "dismiss":
            services.moderate_dismiss(request.user, obj, reason)
        elif action == "restrict":
            services.moderate_restrict(request.user, obj.author_id, form.cleaned_data["days"], reason, **kwargs)
        elif action == "unrestrict":
            services.moderate_unrestrict(request.user, obj.author_id, reason, **kwargs)
        messages.success(request, "처리했어요. 운영 기록에 남겼어요.")
        return redirect("community:manage_target", kind=kind, pk=pk)
    from .models import ModerationLog

    logs = ModerationLog.objects.filter(**({"post": obj} if kind == "post" else {"comment": obj}))
    author = obj.author
    return render(request, "community/manage_target.html", {
        "page_title": "신고 처리", "kind": kind, "obj": obj, "post": post, "comment": comment, "form": form,
        "reports": obj.reports.all(), "logs": logs,
        "attachments": list(post.attachments.all()) if kind == "post" else [],
        # 운영자에게도 아이디·연락처는 보여 주지 않는다. 필요한 것은 상태뿐이다.
        "author_state": {
            "restricted": author.is_restricted, "restricted_until": author.restricted_until,
            "withdrawn": not author.is_active,
            "past_actions": ModerationLog.objects.filter(target_user=author, action__in=["hide", "remove", "restrict"]).count(),
        },
    })
