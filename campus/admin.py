from django.contrib import admin

from .models import CollectionRun, Feedback, Meal


@admin.register(CollectionRun)
class CollectionRunAdmin(admin.ModelAdmin):
    """실패 원인과 마지막 성공 시각을 확인하는 곳."""

    list_display = ("source", "status", "started_at", "finished_at", "item_count", "short_message")
    list_filter = ("source", "status")
    readonly_fields = [f.name for f in CollectionRun._meta.fields]

    @admin.display(description="메시지")
    def short_message(self, obj):
        return obj.message[:80]


@admin.register(Meal)
class MealAdmin(admin.ModelAdmin):
    list_display = ("date", "meal_type", "items", "collected_at")
    list_filter = ("meal_type",)
    date_hierarchy = "date"


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    """시범 운영 학생 의견 확인. 이름·학번 등 개인정보는 받지 않는다."""

    list_display = ("created_at", "short_useful", "short_trouble", "participant_code", "reviewed")
    list_filter = ("reviewed",)
    list_editable = ("reviewed",)
    search_fields = ("useful", "trouble", "wish", "participant_code")
    readonly_fields = ("useful", "trouble", "wish", "participant_code", "created_at")
    exclude = ("client_hash",)

    @admin.display(description="유용했던 기능")
    def short_useful(self, obj):
        return obj.useful[:40]

    @admin.display(description="불편했던 점")
    def short_trouble(self, obj):
        return obj.trouble[:40]

    def has_add_permission(self, request):
        return False
