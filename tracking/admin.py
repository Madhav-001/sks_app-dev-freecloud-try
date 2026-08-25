from django.contrib import admin
from .models import Attendance, Visit, Milage


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("id", "employee", "date", "start_km", "end_km", "total_km")
    list_filter = ("date", "employee")


@admin.register(Visit)
class VisitAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "employee",
        "dealer",
        "type",
        "time",
        "travelled_km",
        "attendance_id",
        "created_at",
        "updated_at"
    )
    list_filter = ("created_at", "employee", "dealer", "type")
    readonly_fields = ("travelled_km",)


@admin.register(Milage)
class MilageAdmin(admin.ModelAdmin):
    """
    Mileage records admin.

    Access rules (driven by the EmployeeRole.milage_manage flag):
      - OWNER / superuser                          →  always sees ALL employees' records
      - Roles with milage_manage=True in DB        →  sees ALL employees' records
      - Everyone else                              →  sees ONLY their own records

    The Owner can toggle milage_manage per role in the
    Admin > Employee Roles access-control table.
    """

    list_display = (
        "id", 
        "employee",
        "date",
        "total_distance_travelled",
        "return_to_home",
        "updated_at",
        "created_at",
    )
    list_filter = ("date", "employee")
    readonly_fields = (
        "employee",
        "date",
        "attendance_id",
        "return_to_home",
        "total_distance_travelled",
        "created_at",
        "updated_at",
    )
    ordering = ("-date", "employee")

    # ------------------------------------------------------------------ #
    # Helper                                                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _has_milage_manage(request):
        """
        Return True if the requesting user is allowed to see all employees'
        mileage records.

        Priority:
          1. Superuser / OWNER → always True (hardcoded, same as the API layer).
          2. For all other roles: look up EmployeeRole.milage_manage in the DB.
             If the role row doesn't exist → False (safe default).
        """
        user = request.user
        if user.is_superuser or getattr(user, "role", None) == "OWNER":
            return True

        from users.models import EmployeeRole
        try:
            role_obj = EmployeeRole.objects.get(name=user.role)
            return role_obj.milage_manage
        except EmployeeRole.DoesNotExist:
            return False

    # ------------------------------------------------------------------ #
    # Queryset scoping                                                     #
    # ------------------------------------------------------------------ #

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if self._has_milage_manage(request):
            return qs
        # Non-privileged staff only see their own record
        return qs.filter(employee=request.user)

    # ------------------------------------------------------------------ #
    # Permission overrides                                                 #
    # ------------------------------------------------------------------ #

    def has_add_permission(self, request):
        """Mileage records are system-generated; prevent manual creation."""
        return False

    def has_change_permission(self, request, obj=None):
        """
        Privileged users can open any record (all fields are read-only).
        Others can only open their own record.
        """
        if self._has_milage_manage(request):
            return True
        if obj is not None:
            return obj.employee == request.user
        return True

    def has_delete_permission(self, request, obj=None):
        """Only OWNER / superusers can delete mileage records."""
        user = request.user
        return user.is_superuser or getattr(user, "role", None) == "OWNER"
