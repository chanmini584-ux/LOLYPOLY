from django.urls import path

from . import views

app_name = "community"

urlpatterns = [
    path("", views.home, name="home"),
    path("rules/", views.rules, name="rules"),
    path("search/", views.search, name="search"),
    path("b/<slug:slug>/", views.board, name="board"),
    path("b/<slug:slug>/write/", views.post_create, name="post_create"),
    path("p/<int:pk>/", views.post_detail, name="post"),
    path("p/<int:pk>/edit/", views.post_edit, name="post_edit"),
    path("p/<int:pk>/delete/", views.post_delete, name="post_delete"),
    path("p/<int:pk>/recruit/", views.post_recruit, name="post_recruit"),
    path("p/<int:pk>/like/", views.post_like, name="post_like"),
    path("p/<int:pk>/scrap/", views.post_scrap, name="post_scrap"),
    path("p/<int:pk>/comment/", views.comment_create, name="comment_create"),
    path("c/<int:pk>/delete/", views.comment_delete, name="comment_delete"),
    path("report/<str:kind>/<int:pk>/", views.report, name="report"),
    path("block/<str:kind>/<int:pk>/", views.block, name="block"),
    path("unblock/<int:pk>/", views.unblock, name="unblock"),
    path("photo/<uuid:key>/", views.photo, name="photo"),
    path("photo/<uuid:key>/t/", views.photo, {"thumb": True}, name="thumb"),
    path("me/posts/", views.my_posts, name="my_posts"),
    path("me/comments/", views.my_comments, name="my_comments"),
    path("me/scraps/", views.my_scraps, name="my_scraps"),
    path("me/blocks/", views.blocks, name="blocks"),
    path("notifications/", views.notifications, name="notifications"),
    path("manage/", views.manage_reports, name="manage_reports"),
    path("manage/<str:kind>/<int:pk>/", views.manage_target, name="manage_target"),
]
