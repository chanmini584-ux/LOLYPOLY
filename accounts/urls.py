from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path("login/", views.login, name="login"),
    path("logout/", views.logout, name="logout"),
    path("password/", views.password_change, name="password_change"),
    path("withdraw/", views.withdraw, name="withdraw"),
]
