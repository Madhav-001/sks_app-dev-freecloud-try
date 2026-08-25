from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from admin_mixins import SoftDeleteAdminMixin
from .models import Employee, LoginHistory, EmployeeRole


@admin.register(Employee)
class EmployeeAdmin(SoftDeleteAdminMixin, UserAdmin):
    """
    - Superuser (employeeidnum=0): delete removes the Employee row from DB.
    - Everyone else:               delete sets is_deleted=True, row stays in DB.
    """

    use_soft_delete_manager = False

    list_display = (
        "id",
        "username",
        "employeeidnum",
        "name",
        "phone",
        "role",
        "date_of_join",
        "is_staff",
        "is_superuser",
        "is_deleted",
        "must_change_password",
    )
    list_filter = ("is_deleted", "role", "is_staff", "is_superuser")
    fieldsets = UserAdmin.fieldsets + (
        (
            "Additional Info",
            {
                "fields": (
                    "name",
                    "phone",
                    "address",
                    "dob",
                    "date_of_join",
                    "blood_group",
                    "role",
                    "is_deleted",
                    "date_of_leave",
                    "employeeidnum",
                )
            },
        ),
    )

    def get_queryset(self, request):
        # Show ALL employees (including soft-deleted) in admin.
        return Employee._base_manager.all()


@admin.register(LoginHistory)
class LoginHistoryAdmin(admin.ModelAdmin):
    list_display = ("id", "employee", "login_at", "logout_at", "ip_address", "status")
    list_filter = ("status", "employee")
    readonly_fields = ("employee", "login_at", "ip_address", "user_agent")


@admin.register(EmployeeRole)
class EmployeeRoleAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "display_name",
        "hierarchy_level",
        "is_builtin",
        "employee_manage",
        "dealers_manage",
        "products_manage",
        "collection_manage",
        "orders_manage",
        "attendance_manage",
        "visit_manage",
        "leads_manage",
        "milage_manage",
    )
    list_editable = (
        "hierarchy_level",
        "employee_manage",
        "dealers_manage",
        "products_manage",
        "collection_manage",
        "orders_manage",
        "attendance_manage",
        "visit_manage",
        "leads_manage",
        "milage_manage",
    )
    search_fields = ("name", "display_name")
    list_filter = ("is_builtin",)
    readonly_fields = ("id", "is_builtin", "created_at", "updated_at")

    def has_change_permission(self, request, obj=None):
        # OWNER role is fully protected — cannot be edited even in admin
        if obj and obj.name == "OWNER":
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        # Block deletion of OWNER and all built-in roles from admin UI
        if obj and (obj.name == "OWNER" or obj.is_builtin):
            return False
        return super().has_delete_permission(request, obj)
