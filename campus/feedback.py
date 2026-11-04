"""시범 운영 의견 폼: 입력 검증·도배 제한·제출 처리.

- 이름·학번·전화번호는 받지 않는다. 세 질문 중 하나 이상 입력해야 제출된다.
- 출력은 Django 템플릿 자동 이스케이프에 맡긴다. CSRF 는 미들웨어가 검사한다.
- 도배 제한: 같은 접속 주소(해시)에서 1시간에 5건까지.
- 숨은 칸(website)에 값이 있으면 봇으로 보고 저장하지 않되 화면에는 성공처럼 보여준다.
"""

import hashlib
import re
from datetime import timedelta

from django import forms
from django.conf import settings
from django.utils import timezone

from .models import Feedback

HOURLY_LIMIT = 5


class FeedbackForm(forms.Form):
    useful = forms.CharField(label="유용했던 기능", max_length=500, required=False, strip=True,
                             widget=forms.Textarea(attrs={"rows": 3, "maxlength": 500}))
    trouble = forms.CharField(label="막히거나 불편했던 점", max_length=500, required=False, strip=True,
                              widget=forms.Textarea(attrs={"rows": 3, "maxlength": 500}))
    wish = forms.CharField(label="다시 사용할 이유 또는 원하는 개선", max_length=500, required=False, strip=True,
                           widget=forms.Textarea(attrs={"rows": 3, "maxlength": 500}))
    participant_code = forms.CharField(label="참여 코드 (선택)", max_length=20, required=False, strip=True)
    website = forms.CharField(required=False)  # 숨은 칸(봇 걸러내기)

    def clean_participant_code(self):
        code = self.cleaned_data["participant_code"]
        if code and not re.fullmatch(r"[A-Za-z0-9_-]{1,20}", code):
            raise forms.ValidationError("영문·숫자·-·_ 20자까지만 쓸 수 있어요.")
        return code

    def clean(self):
        data = super().clean()
        if not any(data.get(k) for k in ("useful", "trouble", "wish")):
            raise forms.ValidationError("세 칸 중 한 곳 이상 적어 주세요.")
        return data


def client_hash(request) -> str:
    # LOLYPOLY_TRUST_PROXY_IP=True: Nginx 가 실제 접속 주소를 X-Real-IP 로 덮어써 주는 구조에서만 켠다.
    ip = request.META.get("REMOTE_ADDR", "")
    if getattr(settings, "TRUST_PROXY_IP", False):
        ip = request.META.get("HTTP_X_REAL_IP", ip)
    return hashlib.sha256(f"{settings.SECRET_KEY}|{ip}".encode()).hexdigest()[:16]


def rate_limited(chash: str) -> bool:
    since = timezone.now() - timedelta(hours=1)
    return Feedback.objects.filter(client_hash=chash, created_at__gte=since).count() >= HOURLY_LIMIT


def save_feedback(form: FeedbackForm, chash: str) -> Feedback | None:
    data = form.cleaned_data
    if data["website"]:  # 봇
        return None
    return Feedback.objects.create(
        useful=data["useful"], trouble=data["trouble"], wish=data["wish"],
        participant_code=data["participant_code"], client_hash=chash,
    )
