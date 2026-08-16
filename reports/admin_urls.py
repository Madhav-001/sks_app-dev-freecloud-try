from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    AdminMorningReportView,
    AdminEODReportView,
    MonthlyTargetViewSet,
)

router = DefaultRouter(trailing_slash=True)
router.register("monthly-targets", MonthlyTargetViewSet, basename="admin-monthly-target")

urlpatterns = [
    path("morning/", AdminMorningReportView.as_view(), name="admin-morning-report"),
    path("eod/", AdminEODReportView.as_view(), name="admin-eod-report"),
    path("", include(router.urls)),
]
