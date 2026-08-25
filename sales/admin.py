from django.contrib import admin
from admin_mixins import SoftDeleteAdminMixin
from .models import Product, Order, OrderItem, Collection, MonthlyTarget, SpecialTarget


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0

    def get_queryset(self, request):
        # Show ALL order items (including soft-deleted) in the inline panel.
        return OrderItem._default_manager.all_with_deleted()


@admin.register(Product)
class ProductAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    """
    - Superuser: delete removes the Product row from DB.
    - Others:    delete sets is_deleted=True.
    """

    use_soft_delete_manager = True  # Product uses SoftDeleteManager

    list_display = ("id", "name", "price", "unit", "is_deleted")
    search_fields = ("name",)
    list_filter = ("is_deleted",)

    def get_queryset(self, request):
        return Product._default_manager.all_with_deleted()


@admin.register(Order)
class OrderAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    """
    - Superuser: delete removes the Order row from DB.
    - Others:    delete sets is_deleted=True.
    """

    use_soft_delete_manager = True  # Order uses SoftDeleteManager

    list_display = (
        "id",
        "sub_dealer",
        "employee",
        "total_amount",
        "status",
        "is_deleted",
        "created_at",
    )
    list_filter = ("is_deleted", "status", "sub_dealer", "employee")
    inlines = [OrderItemInline]
    readonly_fields = ("total_amount",)

    def get_queryset(self, request):
        return Order._default_manager.all_with_deleted()


@admin.register(OrderItem)
class OrderItemAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    """
    - Superuser: delete removes the OrderItem row from DB.
    - Others:    delete sets is_deleted=True.
    """

    use_soft_delete_manager = True  # OrderItem uses SoftDeleteManager

    list_display = ("id", "order", "product", "quantity", "unit_price", "is_deleted")
    list_filter = ("is_deleted",)

    def get_queryset(self, request):
        return OrderItem._default_manager.all_with_deleted()


@admin.register(Collection)
class CollectionAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    """
    - Superuser: delete removes the Collection row from DB.
    - Others:    delete sets is_deleted=True.
    """

    use_soft_delete_manager = True  # Collection uses SoftDeleteManager

    list_display = (
        "id",
        "order",
        "sub_dealer",
        "employee",
        "amount",
        "payment_type",
        "status",
        "is_deleted",
        "updated_at",
        "created_at",
    )
    list_filter = ("is_deleted", "status", "payment_type", "employee")

    def get_queryset(self, request):
        return Collection._default_manager.all_with_deleted()


@admin.register(MonthlyTarget)
class MonthlyTargetAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "employee",
        "year",
        "month",
        "sales_target",
        "collection_target",
        "visits_target",
        "target_setby",
        "updated_at",
        "created_at",
    )
    list_filter = ("year", "month", "employee")
    search_fields = ("employee__username", "employee__name")


@admin.register(SpecialTarget)
class SpecialTargetAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "employee",
        "title",
        "from_date",
        "to_date",
        "sales_target",
        "collection_target",
        "visits_target",
        "target_setby",
        "updated_at",
        "created_at",
    )
    list_filter = ("from_date", "to_date", "employee")
    search_fields = ("employee__username", "employee__name", "title")

