from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AttendanceViewSet, VisitViewSet, MilageViewSet

router = DefaultRouter(trailing_slash=True)
router.register('visit', VisitViewSet, basename='visit')

urlpatterns = [
    path('visit/<uuid:dealers_id>/', VisitViewSet.as_view({'get': 'retrieve_dealer'}), name='visit-dealer-detail'),
    path('visit/detail/<uuid:pk>/', VisitViewSet.as_view({
        'get': 'retrieve_visit_detail',
        'patch': 'partial_update_visit',
    }), name='visit-record-detail'),
    path('attendance/', AttendanceViewSet.as_view({'get': 'employee_monthly_attendance'}), name='attendance-monthly'),
    path('attendance/check-in/', AttendanceViewSet.as_view({'post': 'start'}), name='attendance-start'),
    path('attendance/check-out/', AttendanceViewSet.as_view({'post': 'end'}), name='attendance-end'),
    path('attendance/status/', AttendanceViewSet.as_view({'get': 'attendance_status'}), name='attendance-status'),
    path('attendance/km-report/', AttendanceViewSet.as_view({'get': 'km_report'}), name='attendance-km-report'),
    path('attendance/<uuid:pk>/', AttendanceViewSet.as_view({
        'get': 'retrieve',
        'patch': 'partial_update',
    }), name='attendance-detail'),
    # Milage — daily cumulative summary
    path('milage/summary/', MilageViewSet.as_view({'get': 'milage_summary'}), name='milage-summary'),
    path('', include(router.urls)),
]

