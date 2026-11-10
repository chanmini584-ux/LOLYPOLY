"""춘천캠퍼스 학과 목록 넣기.

출처: 한국폴리텍대학 춘천캠퍼스 홈페이지(https://www.kopo.ac.kr/chuncheon/index.do) '학과안내' 메뉴, 2026-11-10 확인.
  학위과정(2년제): 미디어크리에이터·에너지설비·전기·AI융합·바이오의약공정
  전문기술과정   : 미디어크리에이터·에너지설비·전기·전기자동차
  하이테크과정   : 전기·AI융합·바이오의약공정
같은 이름의 학과는 과정(2년제·전문기술·하이테크)이 달라도 게시판 하나로 묶었다(게시판을 잘게 나누지 않기 위해).
과정별로 나누거나 이름을 고치려면 관리자 화면(학과)에서 추가·수정한다. 이미 있는 이름은 건드리지 않는다.
"""

from django.db import migrations

NAMES = ["AI융합", "미디어크리에이터", "바이오의약공정", "에너지설비", "전기", "전기자동차"]
NOTE = "공식 홈페이지 학과안내 메뉴 2026-11-10 확인"


def seed(apps, schema_editor):
    Department = apps.get_model("accounts", "Department")
    for order, name in enumerate(NAMES, start=1):
        Department.objects.get_or_create(name=name, defaults={"order": order, "note": NOTE})


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_department_and_user_fields")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
