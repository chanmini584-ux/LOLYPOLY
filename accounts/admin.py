from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Department, User


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    """학과 추가·이름 수정·사용 중지. 지우는 대신 '사용 중'을 끈다(게시판과 글이 남는다)."""

    list_display = ("name", "is_active", "order", "user_count", "note")
    list_editable = ("is_active", "order")
    search_fields = ("name",)

    @admin.display(description="소속 계정 수")
    def user_count(self, obj):
        return obj.users.filter(is_active=True).count()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(User)
class LolypolyUserAdmin(UserAdmin):
    """계정 관리: 학과(자기 신고) 변경, 이용 제한·해제. 비밀번호는 볼 수 없고 새로 정해 줄 수만 있다."""

    list_display = ("username", "department", "is_active", "restricted_until", "is_staff", "date_joined")
    list_filter = ("is_active", "is_staff", "department")
    search_fields = ("username",)
    readonly_fields = ("withdrawn_at", "last_login", "date_joined")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("학과·이용 제한", {"fields": ("department", "restricted_until", "restriction_reason")}),
        ("권한", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("기록", {"fields": ("last_login", "date_joined", "withdrawn_at")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("username", "department", "password1", "password2")}),)
