from django.contrib import admin
from admin_mixins import SoftDeleteAdminMixin
from .models import SubDealer


@admin.register(SubDealer)
class SubDealerAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    """
    - Superuser: delete removes the SubDealer row from DB.
    - Others:    delete sets is_deleted=True.
    """

    # SubDealer uses Django's default manager (no SoftDeleteManager).
    use_soft_delete_manager = False

    list_display = ("id", "shop_name", "owner_name", "phone", "employee", "rank", "is_deleted")
    list_filter = ("is_deleted", "rank", "employee")
    search_fields = ("shop_name", "owner_name", "phone")
