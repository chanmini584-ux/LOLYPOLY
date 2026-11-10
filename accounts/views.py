"""가입·로그인·로그아웃·비밀번호 변경·탈퇴.

- 학과는 본인이 고른 값이다(재학·학과 인증 아님). 가입 뒤 변경은 운영자에게 요청한다.
- 이메일을 받지 않으므로 비밀번호를 잊으면 스스로 되찾을 방법이 없다. 화면에서 그대로 안내한다.
- 로그인 뒤 이동(next)은 같은 사이트 주소만 허용한다.
"""

import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import throttle
from .forms import LoginForm, LolypolyPasswordChangeForm, SignupForm, WithdrawForm

REMEMBER_SECONDS = 60 * 60 * 24 * 30


def safe_next(request, default: str = "") -> str:
    target = request.POST.get("next") or request.GET.get("next") or ""
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()},
                                                  require_https=request.is_secure()):
        return target
    return default


def signup(request):
    if request.user.is_authenticated:
        return redirect("community:home")
    limited = False
    if request.method == "POST":
        form = SignupForm(request.POST)
        if throttle.signup_limited(request):
            limited = True
        elif form.is_valid():
            if form.cleaned_data["website"]:      # 봇: 만들지 않고 로그인 화면으로
                return redirect("accounts:login")
            user = form.save()
            throttle.signup_done(request)
            auth_login(request, user)
            request.session.set_expiry(0)         # 기본: 브라우저를 닫으면 로그아웃
            messages.success(request, "가입했어요. 커뮤니티 이용 규칙을 한 번 읽어 주세요.")
            return redirect(safe_next(request, reverse("community:home")))
    else:
        form = SignupForm()
    return render(request, "accounts/signup.html", {"page_title": "가입", "form": form, "limited": limited,
                                                    "next": safe_next(request)})


def login(request):
    if request.user.is_authenticated:
        return redirect(safe_next(request, reverse("community:home")))
    locked = False
    form = LoginForm(request, request.POST or None)
    if request.method == "POST":
        username = request.POST.get("username", "")
        if throttle.login_locked(request, username):
            locked = True
        elif form.is_valid():
            throttle.login_succeeded(request, username)
            auth_login(request, form.user)
            request.session.set_expiry(REMEMBER_SECONDS if form.cleaned_data["remember"] else 0)
            return redirect(safe_next(request, reverse("community:home")))
        else:
            throttle.login_failed(request, username)
    return render(request, "accounts/login.html", {"page_title": "로그인", "form": form, "locked": locked,
                                                   "next": safe_next(request)}, status=429 if locked else 200)


@require_POST
def logout(request):
    auth_logout(request)
    response = redirect("campus:my")
    # 이 브라우저에 남은 HTTP 캐시를 비운다(개인 화면은 애초에 no-store 지만 한 번 더).
    response["Clear-Site-Data"] = '"cache"'
    return response


@login_required
def password_change(request):
    form = LolypolyPasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        update_session_auth_hash(request, form.user)   # 지금 기기는 유지, 다른 기기는 로그아웃됨
        messages.success(request, "비밀번호를 바꿨어요. 다른 기기에서는 다시 로그인해야 해요.")
        return redirect("campus:my")
    return render(request, "accounts/password_change.html", {"page_title": "비밀번호 변경", "form": form})


@login_required
def withdraw(request):
    form = WithdrawForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        from community.services import purge_user_content

        user = request.user
        with transaction.atomic():
            purge_user_content(user)
            user.username = f"withdrawn-{uuid.uuid4().hex[:20]}"
            user.set_unusable_password()
            user.email = user.first_name = user.last_name = ""
            user.department = None
            user.is_active = False
            user.is_staff = user.is_superuser = False
            user.withdrawn_at = timezone.now()
            user.save()
            user.groups.clear()
            user.user_permissions.clear()
        auth_logout(request)
        response = render(request, "accounts/withdraw_done.html", {"page_title": "탈퇴 완료"})
        response["Clear-Site-Data"] = '"cache"'
        return response
    return render(request, "accounts/withdraw.html", {"page_title": "계정 탈퇴", "form": form,
                                                      "retention_days": settings.COMMUNITY_REVIEW_RETENTION_DAYS})
