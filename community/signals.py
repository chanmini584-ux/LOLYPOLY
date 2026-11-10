"""학과가 새로 생기면 그 학과 게시판을 자동으로 만든다."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.models import Department

from .models import Board


@receiver(post_save, sender=Department)
def ensure_department_board(sender, instance, created, **kwargs):
    if kwargs.get("raw"):
        return
    Board.objects.get_or_create(department=instance, defaults={"kind": Board.DEPT, "slug": f"d{instance.pk}"})
