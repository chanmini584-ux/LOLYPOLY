"""Lolypoly 웹앱 운영 실행 (Windows). Gunicorn 은 Windows 에서 안 돌아서 waitress 를 쓴다.

127.0.0.1:8000 에만 연결한다(외부 직접 접근 불가). 바깥 공개는 Cloudflare Tunnel 이 맡는다.
runserver 는 쓰지 않는다. 사용: .venv\\Scripts\\python.exe deploy\\windows\\run_web.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from waitress import serve  # noqa: E402

from config.wsgi import application  # noqa: E402
from django.conf import settings  # noqa: E402

if __name__ == "__main__":
    # 터널(cloudflared, 같은 PC=127.0.0.1)이 붙여 주는 X-Forwarded-Proto/For 만 믿는다(waitress 기본은 무시).
    serve(
        application, host="127.0.0.1", port=8000, threads=8, connection_limit=200, channel_timeout=30,
        # x-forwarded-host: workers.dev 입구(Worker)가 원래 주소를 알려 준다(deploy/cloudflare-worker)
        trusted_proxy="127.0.0.1", trusted_proxy_headers={"x-forwarded-proto", "x-forwarded-for", "x-forwarded-host"},
        clear_untrusted_proxy_headers=True,
        # 요청 하나의 최대 크기: 사진 5장 × 10MiB + 여유(설정값을 그대로 따른다). 넘으면 본문을 받지 않고 거절.
        max_request_body_size=settings.COMMUNITY_MAX_REQUEST_BYTES,
    )
