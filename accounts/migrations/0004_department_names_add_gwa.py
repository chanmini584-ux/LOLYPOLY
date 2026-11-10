"""학과 이름 끝에 '과'를 붙인다 (사용자 결정 2026-11-10: AI융합 → AI융합과).

0003 이 넣은 여섯 이름만 바꾼다. 운영자가 직접 추가·수정한 이름과 이미 '과'로 끝나는 이름은 건드리지 않는다.
"""

from django.db import migrations

NAMES = ["AI융합", "미디어크리에이터", "바이오의약공정", "에너지설비", "전기", "전기자동차"]


def add_suffix(apps, schema_editor):
    Department = apps.get_model("accounts", "Department")
    for name in NAMES:
        if not Department.objects.filter(name=name + "과").exists():
            Department.objects.filter(name=name).update(name=name + "과")


def remove_suffix(apps, schema_editor):
    Department = apps.get_model("accounts", "Department")
    for name in NAMES:
        if not Department.objects.filter(name=name).exists():
            Department.objects.filter(name=name + "과").update(name=name)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_seed_departments")]
    operations = [migrations.RunPython(add_suffix, remove_suffix)]
