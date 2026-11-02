from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # 관리자 화면: 개발·데이터 점검용. 학생용 로그인 기능이 아니다.
    path("admin/", admin.site.urls),
    path("", include("campus.urls")),
]
