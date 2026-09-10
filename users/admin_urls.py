"""
users/admin_urls.py
===================
Admin-specific endpoints for Users/Employees:
  GET /api/admin/auth/employee/{id}/
"""

from django.urls import path
from .employee_360_views import AdminEmployee360DetailView

urlpatterns = [
    # ── Employee 360 Full Detail ──────────────────────────────────────────
    # GET /api/admin/auth/employee/{id}/
    path('employee/<str:id>/', AdminEmployee360DetailView.as_view(), name='admin-employee-360-detail'),
]
