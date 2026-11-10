from django.apps import AppConfig


class CommunityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community"
    verbose_name = "커뮤니티"

    def ready(self):
        from . import signals  # noqa: F401
