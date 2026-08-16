from django.urls import path, include
from rest_framework.routers import DefaultRouter
from notifications.views import NotificationViewSet, DeviceViewSet, PreferenceViewSet

router = DefaultRouter()
router.register(r'device', DeviceViewSet, basename='device')
router.register(r'', NotificationViewSet, basename='notification')

urlpatterns = [
    # Preferences endpoints mapped explicitly
    path('preferences/', PreferenceViewSet.as_view({'get': 'list', 'put': 'update', 'patch': 'update'}), name='preference-detail'),
    path('', include(router.urls)),
]
