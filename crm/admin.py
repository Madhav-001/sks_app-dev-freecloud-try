from django.contrib import admin
from admin_mixins import SoftDeleteAdminMixin
from .models import Lead, Customer


@admin.register(Lead)
class LeadAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    """
    - Superuser: delete removes the Lead row from DB.
    - Others:    delete sets is_deleted=True.
    """

    # Lead uses Django's default manager (no SoftDeleteManager).
    use_soft_delete_manager = False

    list_display = (
        "name",
        "company_name",
        "phone",
        "employee",
        "rank",
        "card",
        "notes",
        "is_deleted",
        "deleted_at",
    )
    list_filter = ("is_deleted", "rank", "employee", "source")
    search_fields = ("name", "company_name", "phone")


@admin.register(Customer)
class CustomerAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    """
    - Superuser: delete removes the Customer row from DB.
    - Others:    delete sets is_deleted=True.
    """

    # Customer uses Django's default manager (no SoftDeleteManager).
    use_soft_delete_manager = False

    list_display = ("name", "phone", "email", "is_deleted", "deleted_at")
    list_filter = ("is_deleted",)
    search_fields = ("name", "phone", "email")
