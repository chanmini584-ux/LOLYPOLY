"""번개 택시방 규칙(D-070). 뷰는 로그인만 확인하고 나머지 판정은 모두 여기서 한다.

- 열림: status=open 이고 지금 < 출발 + 1시간. 시간이 지난 방은 close_expired() 가 닫힘으로 저장한다
  (따로 도는 예약 작업 없이, 목록·방·입장·메시지 요청이 먼저 부른다).
- 정원 경쟁: 입장은 트랜잭션 첫 줄에서 방 행을 UPDATE(touched_at) 해 SQLite 쓰기 잠금을 먼저 잡는다.
  그래서 같은 방에 동시에 들어오는 요청은 한 줄로 처리되고, 인원을 센 값이 낡지 않는다.
- 거절은 services.Rejected(사용자에게 보여 줄 문장).
"""

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.utils import timezone

from . import services
from .models import ModerationLog, Report, TaxiMember, TaxiMessage, TaxiReport, TaxiRoom
from .services import Rejected

OPEN_AFTER_DEPARTURE = timedelta(hours=1)
MAX_AHEAD = timedelta(hours=24)
MAX_HOSTING = 1          # 방장인 열린 방
MAX_JOINED = 2           # 참여 중인 열린 방(방장 포함)
MESSAGE_LIMIT = 5        # 10초에 5개
MESSAGE_WINDOW = timedelta(seconds=10)
RETENTION = timedelta(days=7)


def label(number: int) -> str:
    return "방장" if number == 0 else f"익명{number}"


def _open_q(now):
    return Q(status=TaxiRoom.OPEN, departs_at__gt=now - OPEN_AFTER_DEPARTURE)


def close_expired(now=None) -> int:
    """출발 1시간이 지났는데 아직 열림으로 저장된 방을 닫는다. 닫은 방 수."""
    now = now or timezone.now()
    return TaxiRoom.objects.filter(status=TaxiRoom.OPEN, departs_at__lte=now - OPEN_AFTER_DEPARTURE).update(
        status=TaxiRoom.CLOSED, close_reason="expired", closed_at=now)


def is_open(room: TaxiRoom, now=None) -> bool:
    now = now or timezone.now()
    return room.status == TaxiRoom.OPEN and now < room.closes_at


def open_rooms(user, now=None):
    """목록: 열린 방, 출발 순. 내가 차단한 사람이 방장인 방은 뺀다."""
    now = now or timezone.now()
    qs = TaxiRoom.objects.filter(_open_q(now))
    blocked = services.blocked_ids(user)
    if blocked:
        qs = qs.exclude(host_id__in=blocked)
    return qs.order_by("departs_at", "id")


def active_member(room: TaxiRoom, user) -> TaxiMember | None:
    return TaxiMember.objects.filter(room=room, user=user, left_at__isnull=True).first()


def head_count(room: TaxiRoom) -> int:
    return TaxiMember.objects.filter(room=room, left_at__isnull=True).count()


def _joined_open(user, now) -> int:
    return TaxiMember.objects.filter(user=user, left_at__isnull=True).filter(
        room__status=TaxiRoom.OPEN, room__departs_at__gt=now - OPEN_AFTER_DEPARTURE).count()


def _system(room: TaxiRoom, text: str) -> None:
    TaxiMessage.objects.create(room=room, kind=TaxiMessage.SYSTEM, body=text[:200])


def _lock(room: TaxiRoom, now) -> TaxiRoom:
    """방 행을 먼저 써서 잠금을 잡고 최신 값을 읽는다(트랜잭션 안에서만 부른다)."""
    TaxiRoom.objects.filter(pk=room.pk).update(touched_at=now)
    return TaxiRoom.objects.get(pk=room.pk)


def create_room(user, *, origin: str, destination: str, departs_at, capacity: int, note: str = "") -> TaxiRoom:
    now = timezone.now()
    if user.is_restricted:
        raise Rejected("이용 제한 중이라 택시방을 만들 수 없어요.")
    if not now <= departs_at <= now + MAX_AHEAD:
        raise Rejected("출발 시각은 지금부터 24시간 안으로 정해 주세요.")
    if capacity not in (2, 3, 4):
        raise Rejected("정원은 2·3·4명 중에서 골라 주세요.")
    close_expired(now)
    if TaxiRoom.objects.filter(_open_q(now), host=user).count() >= MAX_HOSTING:
        raise Rejected("이미 만든 택시방이 있어요. 그 방을 터뜨린 뒤에 새로 만들 수 있어요.")
    if _joined_open(user, now) >= MAX_JOINED:
        raise Rejected(f"택시방은 동시에 {MAX_JOINED}개까지만 참여할 수 있어요.")
    with transaction.atomic():
        room = TaxiRoom.objects.create(host=user, origin=origin.strip()[:30], destination=destination.strip()[:30],
                                       departs_at=departs_at, capacity=capacity, note=note.strip()[:40])
        TaxiMember.objects.create(room=room, user=user, number=0)
        _system(room, "방이 만들어졌어요. 연락처·학번은 적지 말아 주세요.")
    return room


def join(room: TaxiRoom, user) -> TaxiMember:
    now = timezone.now()
    if user.is_restricted:
        raise Rejected("이용 제한 중이라 택시방에 들어갈 수 없어요.")
    if room.host_id in services.blocked_ids(user):
        raise Rejected("내가 차단한 사용자가 만든 방이에요.")
    with transaction.atomic():
        room = _lock(room, now)
        if not is_open(room, now):
            raise Rejected("이미 닫힌 방이에요.")
        existing = TaxiMember.objects.filter(room=room, user=user).first()
        if existing and existing.left_at is None:
            return existing
        if _joined_open(user, now) >= MAX_JOINED:
            raise Rejected(f"택시방은 동시에 {MAX_JOINED}개까지만 참여할 수 있어요.")
        if head_count(room) >= room.capacity:
            raise Rejected("정원이 다 찼어요.")
        if existing:
            existing.left_at, existing.joined_at = None, now
            existing.save(update_fields=["left_at", "joined_at"])
            member = existing
        else:
            number = (TaxiMember.objects.filter(room=room).aggregate(m=Max("number"))["m"] or 0) + 1
            member = TaxiMember.objects.create(room=room, user=user, number=number)
        text = f"{label(member.number)}님이 들어왔어요"
        if head_count(room) >= room.capacity:
            text += " · 정원이 다 찼어요"
        _system(room, text)
    return member


def leave(room: TaxiRoom, user) -> None:
    member = active_member(room, user)
    if member is None:
        raise Rejected("이 방에 참여하고 있지 않아요.")
    if member.number == 0:
        raise Rejected("방장은 나갈 수 없어요. 방을 끝내려면 '방 터뜨리기'를 눌러 주세요.")
    with transaction.atomic():
        member.left_at = timezone.now()
        member.save(update_fields=["left_at"])
        if is_open(room):
            _system(room, f"{label(member.number)}님이 나갔어요")


def pop(room: TaxiRoom, user) -> None:
    if room.host_id != user.id:
        raise Rejected("방장만 방을 터뜨릴 수 있어요.")
    now = timezone.now()
    TaxiRoom.objects.filter(pk=room.pk, status=TaxiRoom.OPEN).update(
        status=TaxiRoom.CLOSED, close_reason="host", closed_at=now)


def _check_message_rate(member: TaxiMember) -> None:
    since = timezone.now() - MESSAGE_WINDOW
    if TaxiMessage.objects.filter(member=member, created_at__gte=since).count() >= MESSAGE_LIMIT:
        raise Rejected("메시지를 너무 빨리 보내고 있어요. 잠시 뒤에 보내 주세요.")


def send(room: TaxiRoom, user, body: str) -> TaxiMessage:
    body = (body or "").strip()
    if not body:
        raise Rejected("메시지를 입력해 주세요.")
    if len(body) > 200:
        raise Rejected("메시지는 200자까지 보낼 수 있어요.")
    if user.is_restricted:
        raise Rejected("이용 제한 중이라 메시지를 보낼 수 없어요.")
    room.refresh_from_db()
    if not is_open(room):
        raise Rejected("이미 닫힌 방이에요.")
    member = active_member(room, user)
    if member is None:
        raise Rejected("이 방에 참여하고 있지 않아요.")
    _check_message_rate(member)
    return TaxiMessage.objects.create(room=room, member=member, kind=TaxiMessage.TEXT, body=body)


def messages_after(room: TaxiRoom, after_id: int = 0) -> list[TaxiMessage]:
    return list(TaxiMessage.objects.filter(room=room, id__gt=after_id).select_related("member").order_by("id")[:200])


def report(user, room: TaxiRoom, message: TaxiMessage | None = None, *, reason: str, detail: str = "") -> bool:
    """신고 접수. 같은 방·메시지를 이미 신고했으면 False."""
    if TaxiReport.objects.filter(reporter=user, room=room, message=message).exists():
        return False
    if TaxiReport.objects.filter(reporter=user, created_at__gte=timezone.now() - timedelta(hours=1)).count() >= 20:
        raise Rejected("신고를 너무 자주 하고 있어요. 잠시 뒤에 다시 해 주세요.")
    try:
        with transaction.atomic():
            TaxiReport.objects.create(reporter=user, room=room, message=message, reason=reason, detail=detail[:300])
    except IntegrityError:
        return False
    return True


def moderate_hide(moderator, room: TaxiRoom, reason: str) -> None:
    now = timezone.now()
    with transaction.atomic():
        TaxiRoom.objects.filter(pk=room.pk).update(status=TaxiRoom.HIDDEN, close_reason="moderator",
                                                   closed_at=room.closed_at or now)
        room.reports.filter(status=Report.OPEN).update(status=Report.ACTED, handled_at=now, handled_by=moderator)
        ModerationLog.objects.create(actor=moderator, action="hide", taxi_room=room, target_user_id=room.host_id,
                                     reason=reason[:200])


def dismiss_reports(moderator, room: TaxiRoom, reason: str) -> None:
    now = timezone.now()
    with transaction.atomic():
        room.reports.filter(status=Report.OPEN).update(status=Report.DISMISSED, handled_at=now, handled_by=moderator)
        ModerationLog.objects.create(actor=moderator, action="dismiss", taxi_room=room, target_user_id=room.host_id,
                                     reason=reason[:200])


def purge_closed(now=None) -> int:
    """닫힌(숨김 포함) 지 7일 지난 방을 지운다. 처리 전 신고가 있거나 마지막 신고 처리 후 7일 안이면 남긴다."""
    now = now or timezone.now()
    close_expired(now)
    cutoff = now - RETENTION
    candidates = TaxiRoom.objects.filter(status__in=[TaxiRoom.CLOSED, TaxiRoom.HIDDEN], closed_at__lt=cutoff)
    keep = TaxiReport.objects.filter(Q(status=Report.OPEN) | Q(handled_at__gte=cutoff)).values("room_id")
    doomed = candidates.exclude(pk__in=keep)
    count = doomed.count()
    doomed.delete()
    return count
