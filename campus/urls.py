from django.urls import path

from . import pwa, views

app_name = "campus"

urlpatterns = [
    path("", views.home, name="home"),
    path("meals/", views.meals, name="meals"),
    path("schedule/", views.schedule, name="schedule"),
    path("notices/", views.notices, name="notices"),
    path("timetable/", views.timetable, name="timetable"),
    path("my/", views.my, name="my"),
    # PWA
    path("manifest.webmanifest", pwa.manifest, name="manifest"),
    path("sw.js", pwa.service_worker, name="service_worker"),
    path("offline/", pwa.offline, name="offline"),
]
