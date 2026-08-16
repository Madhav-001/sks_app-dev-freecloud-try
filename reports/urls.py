from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    MorningReportPreviewView,
    MorningReportConfirmView,
    EODReportPreviewView,
    EODReportConfirmView,
    MonthlyTargetViewSet,
)

router = DefaultRouter(trailing_slash=True)
router.register("monthly-targets", MonthlyTargetViewSet, basename="monthly-target")

urlpatterns = [
    path("morning/preview/", MorningReportPreviewView.as_view(), name="morning-report-preview"),
    path("morning/confirm/", MorningReportConfirmView.as_view(), name="morning-report-confirm"),
    path("eod/preview/", EODReportPreviewView.as_view(), name="eod-report-preview"),
    path("eod/confirm/", EODReportConfirmView.as_view(), name="eod-report-confirm"),
    path("", include(router.urls)),
]
