from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    AdminOrderApproveView,
    AdminCollectionApproveView,
    AdminMonthlyTargetViewSet,
    AdminSpecialTargetViewSet,
)
from .analytics_views import AdminOrderAnalyticsView
from .dashboard_views import AdminDashboardView

router = DefaultRouter()
router.register(r"monthly-targets", AdminMonthlyTargetViewSet, basename="admin-monthly-target")
router.register(r"special-targets", AdminSpecialTargetViewSet, basename="admin-special-target")

urlpatterns = [
    path("dashboard/", AdminDashboardView.as_view(), name="admin-sales-dashboard"),
    path("orders/<uuid:pk>/", AdminOrderApproveView.as_view(), name="admin-order-approve"),
    path("collections/<uuid:pk>/", AdminCollectionApproveView.as_view(), name="admin-collection-approve"),
    # Admin sales analytics — requires Owner or orders_manage permission
    path("order-analytics/", AdminOrderAnalyticsView.as_view(), name="admin-order-analytics"),
    path("", include(router.urls)),
]
