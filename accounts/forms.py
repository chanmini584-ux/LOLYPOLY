"""가입·로그인·비밀번호 변경·탈퇴 폼. 비밀번호 해시·검증은 Django 기본 기능을 쓴다."""

import re

from django import forms
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.forms import PasswordChangeForm

from .models import Department, User

USERNAME_RE = re.compile(r"[a-z0-9_]{4,20}")
USERNAME_HELP = "영문 소문자·숫자·밑줄(_) 4~20자. 다른 학생에게는 보이지 않아요."


class SignupForm(forms.Form):
    username = forms.CharField(label="아이디", min_length=4, max_length=20, strip=True, help_text=USERNAME_HELP,
                               widget=forms.TextInput(attrs={"autocomplete": "username", "autocapitalize": "none",
                                                             "spellcheck": "false", "inputmode": "latin"}))
    password1 = forms.CharField(label="비밀번호", strip=False, help_text="8자 이상. 숫자만으로는 만들 수 없어요.",
                                widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="비밀번호 확인", strip=False,
                                widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    department = forms.ModelChoiceField(label="학과", queryset=Department.objects.none(), empty_label="학과를 골라 주세요")
    agree = forms.BooleanField(label="이용 규칙과 안내를 읽었어요", error_messages={"required": "이용 규칙과 안내를 확인해 주세요."})
    website = forms.CharField(required=False)  # 숨은 칸(봇 걸러내기)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.filter(is_active=True)

    def clean_username(self):
        name = self.cleaned_data["username"].lower()
        if not USERNAME_RE.fullmatch(name):
            raise forms.ValidationError("영문 소문자·숫자·밑줄(_)만 4~20자로 적어 주세요.")
        if name.startswith("withdrawn") or User.objects.filter(username__iexact=name).exists():
            raise forms.ValidationError("이미 쓰고 있는 아이디예요. 다른 아이디를 적어 주세요.")
        return name

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "비밀번호가 서로 달라요.")
        elif p1:
            try:
                password_validation.validate_password(p1, User(username=data.get("username", "")))
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return data

    def save(self) -> User:
        data = self.cleaned_data
        return User.objects.create_user(username=data["username"], password=data["password1"],
                                        department=data["department"])


class LoginForm(forms.Form):
    username = forms.CharField(label="아이디", max_length=150, strip=True,
                               widget=forms.TextInput(attrs={"autocomplete": "username", "autocapitalize": "none",
                                                             "spellcheck": "false"}))
    password = forms.CharField(label="비밀번호", strip=False,
                               widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))
    remember = forms.BooleanField(label="이 기기에서 30일 동안 로그인 유지", required=False,
                                  help_text="학교·PC방 같은 공용 컴퓨터에서는 켜지 마세요.")

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user = None
        super().__init__(*args, **kwargs)

    def clean(self):
        data = super().clean()
        username, password = data.get("username"), data.get("password")
        if username and password:
            # 탈퇴·비활성 계정은 authenticate 가 None 을 돌려준다(이유를 구분해 알려 주지 않는다).
            self.user = authenticate(self.request, username=username.lower(), password=password)
            if self.user is None:
                raise forms.ValidationError("아이디 또는 비밀번호가 맞지 않아요.")
        return data


class LolypolyPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].label = "지금 비밀번호"
        self.fields["new_password1"].label = "새 비밀번호"
        self.fields["new_password1"].help_text = "8자 이상. 숫자만으로는 만들 수 없어요."
        self.fields["new_password2"].label = "새 비밀번호 확인"


class WithdrawForm(forms.Form):
    password = forms.CharField(label="비밀번호 확인", strip=False,
                               widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))
    confirm = forms.BooleanField(label="내 글·댓글·사진이 함께 지워지고 되돌릴 수 없다는 것을 확인했어요",
                                 error_messages={"required": "확인란에 표시해 주세요."})

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        if not self.user.check_password(self.cleaned_data["password"]):
            raise forms.ValidationError("비밀번호가 맞지 않아요.")
        return self.cleaned_data["password"]
