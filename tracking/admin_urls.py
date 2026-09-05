from django.urls import path
from .views import (
    AttendanceViewSet,
    AdminDailyMilageView,
    AdminEmployeeMilageSummaryView,
    AdminSODReportView,
    AdminEODReportView,
)

urlpatterns = [
    # ── Attendance ──────────────────────────────────────────────────────────

    # Today's working employees (basic list)
    # path('attendance/', AttendanceViewSet.as_view({'get': 'list'}), name='admin-attendance-list'),

    # All-category attendance for a given date with cursor pagination
    # GET /api/admin/tracking/attendance/date/?date=YYYY-MM-DD&cursor=<token>&page_size=<n>
    path('attendance/date/', AttendanceViewSet.as_view({'get': 'admin_attendance_by_date'}), name='admin-attendance-by-date'),

    # Full monthly attendance details for one employee
    # GET /api/admin/tracking/attendance/<user_id>/?month=7&year=2026
    path('attendance/<uuid:user_id>/', AttendanceViewSet.as_view({'get': 'admin_employee_attendance'}), name='admin-employee-attendance'),

    # ── SOD & EOD Admin Views ───────────────────────────────────────────────
    # GET /api/admin/tracking/sod/<employee_id>/?date=YYYY-MM-DD
    path('sod/<uuid:employee_id>/', AdminSODReportView.as_view(), name='admin-sod-report'),
    # GET /api/admin/tracking/eod/<employee_id>/?date=YYYY-MM-DD
    path('eod/<uuid:employee_id>/', AdminEODReportView.as_view(), name='admin-eod-report'),

    # ── Mileage ─────────────────────────────────────────────────────────────

    # IMPORTANT: 'summary/<uuid>' MUST be declared before 'milage/<str:date>'
    # so Django matches the fixed-prefix route first and doesn't swallow
    # "summary" as a date string.

    # Per-employee weekly scroll (cursor = ?before=YYYY-MM-DD, page = 7 days)
    # GET /api/admin/tracking/milage/summary/<employee_uuid>/
    # GET /api/admin/tracking/milage/summary/<employee_uuid>/?before=2026-07-20
    path(
        'milage/summary/<uuid:user_id>/',
        AdminEmployeeMilageSummaryView.as_view({'get': 'employee_milage_summary'}),
        name='admin-employee-milage-summary',
    ),

    # Daily mileage report for ALL employees (Owner / milage_manage roles only)
    # GET /api/admin/tracking/milage/2026-07-27/
    path(
        'milage/<str:date>/',
        AdminDailyMilageView.as_view({'get': 'daily_milage'}),
        name='admin-daily-milage',
    ),
]
