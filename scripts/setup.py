#!/usr/bin/env python3
"""Lolypoly 개발 환경 한 번에 준비하기 (Windows · macOS · Linux 공통, 표준 라이브러리만 사용)

다른 컴퓨터에서 git clone 한 뒤 프로젝트 폴더에서 실행:

    python scripts/setup.py              # 설치 + DB 준비
    python scripts/setup.py --collect    # + 공식 홈페이지에서 실제 데이터 수집 (인터넷 필요, 약 1분)
    python scripts/setup.py --test       # + 자동 테스트 실행 (인터넷 불필요)

(Windows에서 python 명령이 없으면 `py scripts/setup.py`, macOS/Linux는 `python3 scripts/setup.py`)

하는 일 — 이미 된 단계는 건너뛰고, 기존 파일을 덮어쓰지 않는다:
  1. Python 버전 확인 (3.10 이상)
  2. .venv 가상환경 만들기
  3. requirements.txt 설치
  4. 수집용 브라우저(Playwright Chromium) 설치   ← --no-browser 로 생략 가능
  5. .env 가 없으면 .env.example 을 복사 (있으면 그대로 둠)
  6. DB 마이그레이션 (db.sqlite3 생성/갱신)
  7. (선택) 테스트, 실제 데이터 수집
"""

import argparse
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
IS_WINDOWS = os.name == "nt"
VENV_PY = VENV / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
# 하위 프로세스 출력의 한글이 Windows 콘솔·로그에서 깨지지 않도록 UTF-8 모드
ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def step(n, text):
    print(f"\n[{n}] {text}", flush=True)


def run(args, hint=""):
    print("    $ " + " ".join(str(a) for a in args), flush=True)
    result = subprocess.run([str(a) for a in args], cwd=ROOT, env=ENV)
    if result.returncode != 0:
        print(f"\n실패했어요 (종료 코드 {result.returncode}).", file=sys.stderr)
        if hint:
            print("도움말: " + hint, file=sys.stderr)
        sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(description="Lolypoly 개발 환경 준비")
    parser.add_argument("--collect", action="store_true", help="공식 홈페이지에서 실제 데이터 수집까지 실행")
    parser.add_argument("--test", action="store_true", help="자동 테스트까지 실행")
    parser.add_argument("--no-browser", action="store_true", help="Playwright 브라우저 설치 생략 (수집을 안 할 때)")
    opts = parser.parse_args()

    step(1, "Python 버전 확인")
    print(f"    {sys.version.split()[0]} ({sys.executable})")
    if sys.version_info < (3, 10):
        sys.exit("Python 3.10 이상이 필요해요. https://www.python.org/downloads/ 에서 설치 후 다시 실행하세요.")

    step(2, "가상환경 .venv")
    if VENV_PY.exists():
        print("    이미 있어요 → 건너뜀")
    else:
        venv.EnvBuilder(with_pip=True).create(VENV)
        print("    만들었어요")

    step(3, "패키지 설치 (requirements.txt)")
    run([VENV_PY, "-m", "pip", "install", "--upgrade", "pip", "-q"])
    run([VENV_PY, "-m", "pip", "install", "-r", "requirements.txt", "-q"], "인터넷 연결과 Python 버전을 확인하세요.")

    step(4, "수집용 브라우저 (Playwright Chromium)")
    if opts.no_browser:
        print("    --no-browser → 건너뜀 (수집 명령은 이 브라우저가 있어야 동작)")
    else:
        run([VENV_PY, "-m", "playwright", "install", "chromium"],
            "Ubuntu에서 시스템 라이브러리가 부족하면: sudo .venv/bin/python -m playwright install-deps chromium")

    step(5, "환경설정 파일 .env")
    env_file = ROOT / ".env"
    if env_file.exists():
        print("    이미 있어요 → 그대로 둠 (덮어쓰지 않음)")
    else:
        shutil.copyfile(ROOT / ".env.example", env_file)
        print("    .env.example 을 복사했어요 (개발용: DEBUG=True)")

    step(6, "DB 준비 (migrate)")
    run([VENV_PY, "manage.py", "migrate", "--noinput"])
    run([VENV_PY, "manage.py", "check"])

    if opts.test:
        step(7, "자동 테스트")
        run([VENV_PY, "manage.py", "test"])

    if opts.collect:
        step(8, "실제 데이터 수집 (공식 홈페이지)")
        run([VENV_PY, "manage.py", "collect_all"],
            "일부 수집이 실패해도 나머지는 저장돼요. 실패 원인은 관리자 화면(/admin/) 수집 기록이나 위 메시지를 보세요.")

    activate = r".venv\Scripts\activate" if IS_WINDOWS else "source .venv/bin/activate"
    print(f"""
준비 완료!
  1) 가상환경 켜기:   {activate}
  2) 서버 실행:       python manage.py runserver
  3) 브라우저:        http://127.0.0.1:8000/
{"" if opts.collect else "  ※ 실제 식단·일정·공지를 보려면: python manage.py collect_all" + chr(10)}  작업 기준 문서: AGENTS.md → docs/PROGRESS.md → docs/DECISIONS.md""")


if __name__ == "__main__":
    main()
