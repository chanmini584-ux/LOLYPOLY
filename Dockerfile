# Lolypoly 운영 이미지 (프로토타입 호스팅·다른 서버 공통)
#
# 1단계(collect): 수집용 브라우저를 설치하고 공식 홈페이지에서 공개정보를 한 번 수집해 DB를 만든다.
# 2단계(runtime): 브라우저 없이 앱 + 만들어 둔 DB만 담아 Gunicorn으로 실행한다.
#   → 실행 중에는 공식 홈페이지에 접속하지 않고, 메모리가 작은 무료 서버에서도 브라우저를 띄우지 않는다.
#   → 데이터 갱신 = 이미지 다시 빌드(캐시 없이). 화면의 '오래된 데이터' 안내가 갱신 시점을 알려 준다.
#
# 로컬 확인:
#   docker build --build-arg COLLECT_STAMP=$(date +%F) -t lolypoly .
#   docker run --rm -p 8000:8000 -e DJANGO_SECRET_KEY=아무긴값 -e DJANGO_ALLOWED_HOSTS=localhost lolypoly

ARG PYTHON_IMAGE=python:3.13-slim-bookworm

# ---------- 1단계: 수집 ----------
FROM ${PYTHON_IMAGE} AS collect
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt \
    && python -m playwright install --with-deps chromium
COPY . .
# 값을 바꾸면(예: 날짜) 이 아래부터 캐시 없이 다시 수집한다.
ARG COLLECT_STAMP=none
# 수집이 일부 실패해도 빌드는 계속한다: 실패 기록이 DB에 남아 화면에 '갱신 실패'로 정직하게 표시된다.
# COLLECT=0 이면 수집을 건너뛴다(화면만 확인할 때). 이때 화면은 '정보가 없어요'.
ARG COLLECT=1
RUN echo "collect stamp: ${COLLECT_STAMP}" \
    && DJANGO_DEBUG=False DJANGO_SECRET_KEY=build-only DJANGO_SQLITE_PATH=/data/db.sqlite3 \
       sh -c 'mkdir -p /data && python manage.py migrate --noinput \
              && if [ "${COLLECT}" = "1" ]; then python manage.py collect_all || echo "수집 일부 실패: 기록을 DB에 남기고 계속"; fi'

# ---------- 2단계: 실행 ----------
FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    DJANGO_DEBUG=False \
    DJANGO_SQLITE_PATH=/data/db.sqlite3
WORKDIR /app
RUN useradd --create-home --uid 10001 app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput
COPY --from=collect /data /data
RUN chown -R app:app /data
USER app
EXPOSE 8000
# 버스 노선은 TAGO 키(TAGO_SERVICE_KEY)가 실행 환경변수로만 주어지므로(빌드에 비밀값을 넣지 않음),
# 서버 시작 때 노선 데이터가 비어 있으면 한 번 수집한다. 실패해도 서버는 뜬다(화면에 '노선 정보 없음').
# 노선 수집(TAGO 약 20번 호출)은 뒤에서 돌리고 Gunicorn 을 바로 띄운다(D-043): 무료 호스팅이 깨어날 때 기다리는 시간을 줄인다.
#   → 서버가 뜬 직후 몇 초 동안은 버스 화면이 '노선 정보 없음'일 수 있다.
# PORT는 호스팅이 정해 주면 그 값을, 없으면 8000. 무료 서버(512MB) 기준 워커 2개 × 스레드 4개(D-044):
#   실시간 버스처럼 바깥 응답을 기다리는 요청이 있어도 다른 화면 요청을 계속 처리한다.
CMD ["sh", "-c", "python manage.py collect_bus --if-empty & exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${GUNICORN_WORKERS:-2} --threads ${GUNICORN_THREADS:-4} --access-logfile - --timeout 30"]
