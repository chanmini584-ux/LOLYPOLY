from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # 관리자 화면: 슈퍼유저의 학과·계정·데이터 관리용. 학생 로그인은 /accounts/login/
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("community/", include("community.urls")),
    path("", include("campus.urls")),
]
