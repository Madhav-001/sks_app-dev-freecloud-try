from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import LeadViewSet, CustomerViewSet

router = DefaultRouter()
router.register(r'leads', LeadViewSet, basename='lead')
router.register(r'customers', CustomerViewSet)

urlpatterns = router.urls
