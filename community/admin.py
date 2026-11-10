"""관리자 화면(슈퍼유저용). 일상적인 신고 처리는 /community/manage/ 에서 한다."""

from django.contrib import admin

from .models import Board, Comment, ModerationLog, Post, Report


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Board)
class BoardAdmin(ReadOnlyAdmin):
    list_display = ("__str__", "kind", "slug")


@admin.register(Post)
class PostAdmin(ReadOnlyAdmin):
    list_display = ("id", "board", "category", "title", "status", "like_count", "comment_count", "created_at")
    list_filter = ("status", "category", "board")
    search_fields = ("title", "body")
    exclude = ("author",)          # 목록·상세에서 계정을 바로 드러내지 않는다


@admin.register(Comment)
class CommentAdmin(ReadOnlyAdmin):
    list_display = ("id", "post", "short", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("body",)
    exclude = ("author",)

    @admin.display(description="내용")
    def short(self, obj):
        return obj.body[:50]


@admin.register(Report)
class ReportAdmin(ReadOnlyAdmin):
    list_display = ("id", "reason", "status", "post", "comment", "created_at", "handled_at")
    list_filter = ("status", "reason")
    exclude = ("reporter",)


@admin.register(ModerationLog)
class ModerationLogAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "action", "actor", "post", "comment", "reason")
    list_filter = ("action",)
    exclude = ("target_user",)
