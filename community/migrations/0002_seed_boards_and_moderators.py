"""전체 게시판 1개 + 학과마다 게시판 1개, 그리고 '커뮤니티 운영자' 그룹(신고 처리 권한만) 만들기."""

from django.db import migrations


def seed(apps, schema_editor):
    Board = apps.get_model("community", "Board")
    Department = apps.get_model("accounts", "Department")
    Board.objects.get_or_create(kind="all", defaults={"slug": "all"})
    for dept in Department.objects.all():
        Board.objects.get_or_create(department=dept, defaults={"kind": "dept", "slug": f"d{dept.pk}"})


def moderators(apps, schema_editor):
    # 권한 행은 마이그레이션이 끝난 뒤(post_migrate) 만들어지므로, 여기서 직접 만들어 그룹에 넣는다.
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    ct, _ = ContentType.objects.get_or_create(app_label="community", model="post")
    perm, _ = Permission.objects.get_or_create(content_type=ct, codename="moderate",
                                               defaults={"name": "신고 처리·숨김·이용 제한을 할 수 있음"})
    group, _ = Group.objects.get_or_create(name="커뮤니티 운영자")
    group.permissions.add(perm)


class Migration(migrations.Migration):
    dependencies = [
        ("community", "0001_initial"),
        ("accounts", "0003_seed_departments"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]
    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
        migrations.RunPython(moderators, migrations.RunPython.noop),
    ]
