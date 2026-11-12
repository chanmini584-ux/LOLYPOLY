"""번개 택시방 화면(D-070). 로그인만 여기서 확인하고, 규칙 판정은 community/taxi.py 가 한다.

- 개인 화면이라 저장 금지(no-store)는 PrivateCacheMiddleware 가 /community/ 전체에 붙인다.
- 실시간: taxi.js 가 3초마다 taxi_messages(JSON)를 부른다(D-071). JS 가 없으면 보내기 폼 → 새로고침으로 동작.
- 학생에게는 닫힌·숨긴 방이 '없는 방'(404)이다. 운영자는 taxi_manage 에서 본다.
"""

from django.contrib import messages as flash
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services, taxi
from .forms import TAXI_PLACES, ModerationForm, ReportForm, TaxiMessageForm, TaxiRoomForm
from .models import ModerationLog, TaxiMember, TaxiMessage, TaxiRoom
from .views import member, moderator


def _visible_room(request, pk) -> TaxiRoom:
    """학생이 볼 수 있는(열린) 방. 시간이 지난 방은 이 자리에서 닫힘으로 저장한다."""
    taxi.close_expired()
    room = get_object_or_404(TaxiRoom, pk=pk)
    if not taxi.is_open(room):
        raise Http404("닫힌 방")
    return room


def _members(room: TaxiRoom, me_id: int) -> list[dict]:
    return [{"label": taxi.label(m.number), "me": m.user_id == me_id, "host": m.number == 0}
            for m in TaxiMember.objects.filter(room=room, left_at__isnull=True).order_by("number")]


def _message_json(m: TaxiMessage, me_id: int, blocked: set[int]) -> dict:
    if m.kind == TaxiMessage.SYSTEM:
        return {"id": m.id, "system": True, "body": m.body}
    hidden = m.member.user_id in blocked
    return {"id": m.id, "system": False, "who": taxi.label(m.member.number), "mine": m.member.user_id == me_id,
            "body": "차단한 사용자의 메시지예요." if hidden else m.body, "blocked": hidden,
            "time": timezone.localtime(m.created_at).strftime("%H:%M")}


@member
def taxi_list(request):
    taxi.close_expired()
    rooms = list(taxi.open_rooms(request.user))
    mine = set(TaxiMember.objects.filter(user=request.user, left_at__isnull=True, room__in=rooms)
               .values_list("room_id", flat=True))
    today = timezone.localdate()
    items = []
    for room in rooms:
        count = taxi.head_count(room)
        local = timezone.localtime(room.departs_at)
        items.append({"room": room, "count": count, "seats": [i < count for i in range(room.capacity)],
                      "time": local, "day": "오늘" if local.date() == today else "내일",
                      "is_host": room.host_id == request.user.id, "joined": room.id in mine,
                      "full": count >= room.capacity})
    return render(request, "community/taxi/list.html", {"page_title": "택시 같이 타기", "items": items})


@member
def taxi_new(request):
    form = TaxiRoomForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            room = taxi.create_room(request.user, origin=d["origin"], destination=d["destination"],
                                    departs_at=d["departs_at"], capacity=d["capacity"], note=d["note"])
        except services.Rejected as exc:
            form.add_error(None, str(exc))
        else:
            return redirect("community:taxi_room", pk=room.pk)
    return render(request, "community/taxi/new.html", {"page_title": "택시방 만들기", "form": form,
                                                        "places": TAXI_PLACES},
                  status=400 if request.method == "POST" else 200)


@member
def taxi_room(request, pk):
    room = _visible_room(request, pk)
    me = taxi.active_member(room, request.user)
    blocked = services.blocked_ids(request.user)
    history = [_message_json(m, request.user.id, blocked) for m in taxi.messages_after(room, 0)] if me else []
    return render(request, "community/taxi/room.html", {
        "page_title": "택시방", "room": room, "me": me, "me_label": taxi.label(me.number) if me else "",
        "is_host": room.host_id == request.user.id, "members": _members(room, request.user.id),
        "count": taxi.head_count(room), "history": history, "last_id": history[-1]["id"] if history else 0,
        "departs": timezone.localtime(room.departs_at), "closes": timezone.localtime(room.closes_at),
        "form": TaxiMessageForm(),
    })


def _act(request, pk, action, ok_message=""):
    room = _visible_room(request, pk)
    try:
        action(room, request.user)
    except services.Rejected as exc:
        flash.error(request, str(exc))
    else:
        if ok_message:
            flash.success(request, ok_message)
    return room


@member
@require_POST
def taxi_join(request, pk):
    _act(request, pk, taxi.join)
    return redirect("community:taxi_room", pk=pk)


@member
@require_POST
def taxi_leave(request, pk):
    _act(request, pk, taxi.leave, "방에서 나왔어요.")
    return redirect("community:taxi_list")


@member
@require_POST
def taxi_pop(request, pk):
    _act(request, pk, taxi.pop, "방을 터뜨렸어요. 대화 내용은 더 이상 보이지 않아요.")
    return redirect("community:taxi_list")


@member
@require_POST
def taxi_send(request, pk):
    room = _visible_room(request, pk)
    form = TaxiMessageForm(request.POST)
    wants_json = request.headers.get("Accept", "").startswith("application/json")
    error = ""
    if form.is_valid():
        try:
            taxi.send(room, request.user, form.cleaned_data["body"])
        except services.Rejected as exc:
            error = str(exc)
    else:
        error = "메시지를 1~200자로 입력해 주세요."
    if wants_json:
        return JsonResponse({"ok": not error, "error": error}, status=400 if error else 200,
                            json_dumps_params={"ensure_ascii": False})
    if error:
        flash.error(request, error)
    return redirect(reverse("community:taxi_room", args=[pk]) + "#chat-end")


@member
def taxi_messages(request, pk):
    """새 메시지(JSON). 참여 중인 사람만. 방이 닫혔으면 closed=true 로 알려 화면이 목록으로 돌아가게 한다."""
    taxi.close_expired()
    room = get_object_or_404(TaxiRoom, pk=pk)
    if not taxi.is_open(room):
        return JsonResponse({"closed": True})
    me = taxi.active_member(room, request.user)
    if me is None:
        return JsonResponse({"error": "참여하고 있지 않아요."}, status=403, json_dumps_params={"ensure_ascii": False})
    try:
        after = max(0, int(request.GET.get("after", 0)))
    except ValueError:
        after = 0
    blocked = services.blocked_ids(request.user)
    return JsonResponse({
        "closed": False, "me": taxi.label(me.number),
        "messages": [_message_json(m, request.user.id, blocked) for m in taxi.messages_after(room, after)],
        "members": _members(room, request.user.id), "count": taxi.head_count(room), "capacity": room.capacity,
    }, json_dumps_params={"ensure_ascii": False})


def _report(request, room, message=None):
    back = reverse("community:taxi_room", args=[room.pk])
    form = ReportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            created = taxi.report(request.user, room, message, reason=form.cleaned_data["reason"],
                                  detail=form.cleaned_data["detail"])
        except services.Rejected as exc:
            flash.error(request, str(exc))
        else:
            flash.success(request, "신고를 접수했어요. 운영자가 확인할게요." if created else "이미 신고했어요.")
        return redirect(back)
    preview = message.body if message else f"{room.origin} → {room.destination} {room.note}"
    return render(request, "community/taxi/report.html", {
        "page_title": "신고", "form": form, "back": back, "preview": preview[:60], "action": request.path,
        "what": "메시지" if message else "택시방",
    })


@member
def taxi_report(request, pk):
    return _report(request, _visible_room(request, pk))


@member
def taxi_message_report(request, pk):
    message = get_object_or_404(TaxiMessage.objects.select_related("room", "member"), pk=pk, kind=TaxiMessage.TEXT)
    room = _visible_room(request, message.room_id)
    if taxi.active_member(room, request.user) is None:
        raise PermissionDenied
    if message.member.user_id == request.user.id:
        flash.error(request, "내가 보낸 메시지는 신고할 수 없어요.")
        return redirect("community:taxi_room", pk=room.pk)
    return _report(request, room, message)


@moderator
def taxi_manage(request, pk):
    room = get_object_or_404(TaxiRoom, pk=pk)
    form = ModerationForm(request.POST or None)
    form.fields["action"].choices = [("hide", "방 숨기기(닫기)"), ("dismiss", "문제없음으로 신고 종료"),
                                     ("restrict", "방장 계정 이용 제한")]
    if request.method == "POST" and form.is_valid():
        action, reason = form.cleaned_data["action"], form.cleaned_data["reason"]
        if action == "hide":
            taxi.moderate_hide(request.user, room, reason)
        elif action == "dismiss":
            taxi.dismiss_reports(request.user, room, reason)
        elif action == "restrict":
            services.moderate_restrict(request.user, room.host_id, form.cleaned_data["days"], reason)
        flash.success(request, "처리했어요. 운영 기록에 남겼어요.")
        return redirect("community:taxi_manage", pk=pk)
    msgs = TaxiMessage.objects.filter(room=room).select_related("member").order_by("id")
    return render(request, "community/taxi/manage.html", {
        "page_title": "택시방 신고 처리", "room": room, "form": form,
        "messages_list": [{"who": taxi.label(m.member.number) if m.member else "안내", "body": m.body,
                           "time": timezone.localtime(m.created_at), "reported": m.reports.exists()} for m in msgs],
        "reports": room.reports.select_related("message"), "logs": ModerationLog.objects.filter(taxi_room=room),
    })
