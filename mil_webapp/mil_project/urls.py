from django.urls import include, path

urlpatterns = [
    path("", include("cases.urls")),
]
