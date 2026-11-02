from django.contrib import admin

from .models import CollectionRun, Meal


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
