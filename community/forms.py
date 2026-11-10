from django import forms

from .models import Post, Report


class MultiFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultiFileField(forms.FileField):
    """사진 여러 장. 종류·크기·화소 검사는 community.images 가 실제로 열어 보고 한다."""

    widget = MultiFileInput

    def clean(self, data, initial=None):
        if not data:
            return []
        items = data if isinstance(data, (list, tuple)) else [data]
        return [super(MultiFileField, self).clean(item, initial) for item in items]


class PostForm(forms.Form):
    category = forms.ChoiceField(label="분류", choices=Post.CATEGORIES, initial=Post.FREE)
    title = forms.CharField(label="제목", max_length=80, strip=True,
                            widget=forms.TextInput(attrs={"maxlength": 80, "autocomplete": "off"}))
    body = forms.CharField(label="내용", max_length=5000, strip=True,
                           widget=forms.Textarea(attrs={"rows": 8, "maxlength": 5000}))
    recruit_open = forms.TypedChoiceField(label="모집 상태", required=False, coerce=lambda v: v == "1",
                                          choices=[("1", "모집 중"), ("0", "마감")], empty_value=None)
    photos = MultiFileField(label="사진", required=False,
                            widget=MultiFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}))


class CommentForm(forms.Form):
    body = forms.CharField(label="댓글", max_length=1000, strip=True,
                           widget=forms.Textarea(attrs={"rows": 2, "maxlength": 1000}))


class ReportForm(forms.Form):
    reason = forms.ChoiceField(label="신고 이유", choices=Report.REASONS, widget=forms.RadioSelect)
    detail = forms.CharField(label="설명 (선택)", max_length=300, required=False, strip=True,
                             widget=forms.Textarea(attrs={"rows": 3, "maxlength": 300}))


class ModerationForm(forms.Form):
    ACTIONS = [
        ("hide", "숨기기"), ("restore", "다시 보이게(복구)"), ("remove", "삭제 확정(내용·사진 지움)"),
        ("dismiss", "문제없음으로 신고 종료"),
        ("restrict", "작성 계정 이용 제한"), ("unrestrict", "작성 계정 이용 제한 해제"),
    ]
    action = forms.ChoiceField(label="처리", choices=ACTIONS, widget=forms.RadioSelect)
    days = forms.IntegerField(label="이용 제한 기간(일)", min_value=1, max_value=365, required=False, initial=7)
    reason = forms.CharField(label="처리 사유", max_length=200, strip=True,
                             widget=forms.Textarea(attrs={"rows": 2, "maxlength": 200}))

    def clean(self):
        data = super().clean()
        if data.get("action") == "restrict" and not data.get("days"):
            self.add_error("days", "이용 제한 기간을 적어 주세요.")
        return data
