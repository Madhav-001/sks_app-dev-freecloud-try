from django.urls import path
from .views import AdminOrderApproveView, AdminCollectionApproveView
from .analytics_views import AdminOrderAnalyticsView

urlpatterns = [
    path("orders/<uuid:pk>/", AdminOrderApproveView.as_view(), name="admin-order-approve"),
    path("collections/<uuid:pk>/", AdminCollectionApproveView.as_view(), name="admin-collection-approve"),
    # Admin sales analytics — requires Owner or orders_manage permission
    path("order-analytics/", AdminOrderAnalyticsView.as_view(), name="admin-order-analytics"),
]
