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
    path("bus/", views.bus, name="bus"),
    path("bus/live/<str:group>/", views.bus_live, name="bus_live"),
    path("bus/nearest/", views.bus_nearest, name="bus_nearest"),
    # PWA
    path("manifest.webmanifest", pwa.manifest, name="manifest"),
    path("sw.js", pwa.service_worker, name="service_worker"),
    path("offline/", pwa.offline, name="offline"),
]
