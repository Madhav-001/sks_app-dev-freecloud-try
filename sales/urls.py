from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ProductViewSet,
    OrderViewSet,
    CollectionViewSet,
    EmployeeMonthlyTargetViewSet,
    EmployeeSpecialTargetViewSet,
)
from .analytics_views import EmployeeOrderAnalyticsView

router = DefaultRouter()
router.register(r"products", ProductViewSet)
router.register(r"orders", OrderViewSet)
router.register(r"collections", CollectionViewSet, basename="collection")
router.register(r"monthly-targets", EmployeeMonthlyTargetViewSet, basename="employee-monthly-target")
router.register(r"special-targets", EmployeeSpecialTargetViewSet, basename="employee-special-target")

urlpatterns = [
    path("", include(router.urls)),
    # Sales analytics — employee endpoint (scoped to authenticated user)
    path("order-analytics/", EmployeeOrderAnalyticsView.as_view(), name="employee-order-analytics"),
]
