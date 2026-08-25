from rest_framework import serializers
from .models import Product, Order, OrderItem, Collection, MonthlyTarget, SpecialTarget
from dealers.serializers import SubDealerSerializer
from users.serializers import EmployeeSerializer
from users.models import Employee
from users.permissions import (
    has_orders_manage_permission,
    has_collection_manage_permission,
    has_visit_manage_permission,
)


class ProductSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = Product
        fields = ["id", "name", "unit", "image", "price", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class OrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.ReadOnlyField(source="product.name")

    class Meta:
        model = OrderItem
        fields = ["id", "product", "product_name", "quantity", "unit_price"]


class CollectionSerializer(serializers.ModelSerializer):
    # employee  – set automatically from the authenticated user in the view (not sent by client)
    # status    – read-only; set by the view / business logic
    employee = serializers.PrimaryKeyRelatedField(read_only=True)
    status = serializers.ChoiceField(choices=Collection.STATUS_CHOICES, read_only=True)

    class Meta:
        model = Collection
        fields = [
            "id",
            "sub_dealer",   # The dealer who paid
            "employee",     # The employee who received the money
            "order",        # Related order (nullable)
            "amount",
            "payment_type",
            "status",
            "reference_id",
            "is_deleted",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "employee", "status", "is_deleted", "created_at", "updated_at"]


class OrderCreatedResponseSerializer(serializers.ModelSerializer):
    """Minimal response returned after POST /api/sales/orders/ — only IDs."""

    class Meta:
        model = Order
        fields = ["id", "sub_dealer", "employee"]


class OrderListSerializer(serializers.ModelSerializer):
    """Minimal serializer used for GET /api/sales/orders/ list."""

    items = OrderItemSerializer(many=True, read_only=True)
    collected_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    due_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )

    class Meta:
        model = Order
        fields = [
            "id",
            "sub_dealer",
            "employee",
            "status",
            "total_amount",
            "collected_amount",
            "due_amount",
            "items",
            "created_at",
            "updated_at",
        ]


class OrderSummarySerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    collections = CollectionSerializer(many=True, read_only=True)
    collected_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    due_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    sub_dealer_details = SubDealerSerializer(source="sub_dealer", read_only=True)
    employee_details = EmployeeSerializer(source="employee", read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "sub_dealer",
            "sub_dealer_details",
            "employee",
            "employee_details",
            "status",
            # "additional",
            "total_amount",
            "collected_amount",
            "due_amount",
            "items",
            "collections",
            "created_at",
            "updated_at",
        ]


class OrderItemUpdateSerializer(serializers.ModelSerializer):
    """
    Used inside OrderUpdateSerializer.
    - With 'id'    → updates the existing OrderItem.
    - Without 'id' → creates a new OrderItem on the order.
    """

    id = serializers.UUIDField(required=False, allow_null=True)  # optional: omit to add a new item
    product_name = serializers.ReadOnlyField(source="product.name")

    class Meta:
        model = OrderItem
        fields = ["id", "product", "product_name", "quantity", "unit_price"]
        extra_kwargs = {
            "product":    {"required": False},
            "quantity":   {"required": False},
            "unit_price": {"required": False},
        }


class OrderUpdateSerializer(serializers.ModelSerializer):
    """
    Used for PATCH /api/sales/orders/{id}/

    Fields:
      - items        : list of item objects to add / update (see below)
      - remove_items : list of item UUIDs to remove from the order

    Items behaviour:
      - Item WITH 'id'    → updates that existing item (quantity, unit_price, product)
      - Item WITHOUT 'id' → adds/updates by product (no duplicate rows)

    total_amount is always recalculated from the DB after all items are processed.
    """

    items = OrderItemUpdateSerializer(many=True, required=False)
    remove_items = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        write_only=True,
        help_text="List of OrderItem UUIDs to remove from this order.",
    )

    class Meta:
        model = Order
        fields = ["sub_dealer", "items", "remove_items"]
        extra_kwargs = {
            "sub_dealer": {"required": False},
        }

    def update(self, instance, validated_data):
        items_data      = validated_data.pop("items", None)
        remove_item_ids = validated_data.pop("remove_items", None)

        # Update top-level order fields (e.g. sub_dealer)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        # ── Remove items ──────────────────────────────────────────────
        if remove_item_ids:
            for item_id in remove_item_ids:
                try:
                    item = OrderItem.objects.get(id=item_id, order=instance)
                except OrderItem.DoesNotExist:
                    raise serializers.ValidationError(
                        {"remove_items": f"Item '{item_id}' does not belong to this order."}
                    )
                item.is_deleted = True
                item.save(update_fields=["is_deleted"])

        if items_data is not None:
            for item_data in items_data:
                item_id = item_data.pop("id", None)

                if item_id:
                    # ── UPDATE existing item ──────────────────────────────────
                    try:
                        item = OrderItem.objects.get(id=item_id, order=instance)
                    except OrderItem.DoesNotExist:
                        raise serializers.ValidationError(
                            {"items": f"Item '{item_id}' does not belong to this order."}
                        )
                    for attr, value in item_data.items():
                        setattr(item, attr, value)
                    item.save()

                else:
                    # ── ADD or UPDATE by product ──────────────────────────────
                    # If this product already exists on the order, update it.
                    # Only create a new row if the product is genuinely new.
                    required = {"product", "quantity", "unit_price"}
                    missing  = required - item_data.keys()
                    if missing:
                        raise serializers.ValidationError(
                            {"items": f"New items require: {', '.join(sorted(missing))}."}
                        )
                    product = item_data["product"]
                    existing = instance.items.filter(product=product).first()
                    if existing:
                        # Product already in order → update in place
                        existing.quantity   = item_data.get("quantity",   existing.quantity)
                        existing.unit_price = item_data.get("unit_price", existing.unit_price)
                        existing.save()
                    else:
                        # Genuinely new product → create
                        OrderItem.objects.create(order=instance, **item_data)

            # Recalculate total_amount from the updated DB rows
            from django.db.models import Sum, F, ExpressionWrapper, DecimalField
            agg = instance.items.aggregate(
                total=Sum(
                    ExpressionWrapper(
                        F("quantity") * F("unit_price"),
                        output_field=DecimalField(max_digits=12, decimal_places=2),
                    )
                )
            )
            instance.total_amount = agg["total"] or 0

        instance.save()
        return instance


class OrderCreateSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True)

    class Meta:
        model = Order
        # 'employee' is intentionally excluded — it is always set from the
        # authenticated user's access token in the view, not from the request body.
        fields = ["sub_dealer", "items"]

    def create(self, validated_data):
        items_data = validated_data.pop("items")
        # additional = validated_data.get("additional", 0)
        # Calculate total amount
        total_amount = sum(item["quantity"] * item["unit_price"] for item in items_data)

        order = Order.objects.create(total_amount=total_amount, **validated_data)

        for item_data in items_data:
            OrderItem.objects.create(order=order, **item_data)

        return order


class SimpleEmployeeSummarySerializer(serializers.ModelSerializer):
    """Compact employee representation for target responses."""
    class Meta:
        model = Employee
        fields = ["id", "employeeidnum", "name", "username", "phone"]


class MonthlyTargetSerializer(serializers.ModelSerializer):
    """Serializer used for reading MonthlyTarget (both admin and employee GET)."""
    employee_details = SimpleEmployeeSummarySerializer(source="employee", read_only=True)
    target_setby_details = SimpleEmployeeSummarySerializer(source="target_setby", read_only=True)

    class Meta:
        model = MonthlyTarget
        fields = [
            "id",
            "employee",
            "employee_details",
            "year",
            "month",
            "sales_target",
            "collection_target",
            "visits_target",
            "target_setby",
            "target_setby_details",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "target_setby",
            "created_at",
            "updated_at",
        ]


class AdminMonthlyTargetWriteSerializer(serializers.ModelSerializer):
    """
    Serializer used for creating (POST) and updating (PATCH) MonthlyTarget.
    Enforces field-level permissions for orders_manage, collection_manage, and visit_manage.
    """
    class Meta:
        model = MonthlyTarget
        fields = [
            "id",
            "employee",
            "year",
            "month",
            "sales_target",
            "collection_target",
            "visits_target",
            "target_setby",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "target_setby",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        request = self.context.get("request")
        user = request.user if request else None

        # Check field permissions
        if user and not user.is_owner:
            # Check sales_target
            if "sales_target" in attrs and not has_orders_manage_permission(user):
                raise serializers.ValidationError(
                    {"sales_target": "You do not have permission ('orders_manage') to set or update sales targets."}
                )
            # Check collection_target
            if "collection_target" in attrs and not has_collection_manage_permission(user):
                raise serializers.ValidationError(
                    {"collection_target": "You do not have permission ('collection_manage') to set or update collection targets."}
                )
            # Check visits_target
            if "visits_target" in attrs and not has_visit_manage_permission(user):
                raise serializers.ValidationError(
                    {"visits_target": "You do not have permission ('visit_manage') to set or update visits targets."}
                )

        # Unique constraint check on create
        if not self.instance:
            employee = attrs.get("employee")
            year = attrs.get("year")
            month = attrs.get("month")
            if employee and year and month:
                if MonthlyTarget.objects.filter(employee=employee, year=year, month=month).exists():
                    raise serializers.ValidationError(
                        {"non_field_errors": [f"Monthly target already exists for employee '{employee.username}' for {month}/{year}."]}
                    )

        return attrs


class SpecialTargetSerializer(serializers.ModelSerializer):
    """Serializer used for reading SpecialTarget (both admin and employee GET)."""
    employee_details = SimpleEmployeeSummarySerializer(source="employee", read_only=True)
    target_setby_details = SimpleEmployeeSummarySerializer(source="target_setby", read_only=True)

    class Meta:
        model = SpecialTarget
        fields = [
            "id",
            "employee",
            "employee_details",
            "title",
            "from_date",
            "to_date",
            "sales_target",
            "collection_target",
            "visits_target",
            "target_setby",
            "target_setby_details",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "target_setby",
            "created_at",
            "updated_at",
        ]


class AdminSpecialTargetWriteSerializer(serializers.ModelSerializer):
    """
    Serializer used for creating (POST) and updating (PATCH) SpecialTarget.
    Enforces field-level permissions and date range validation.
    """
    class Meta:
        model = SpecialTarget
        fields = [
            "id",
            "employee",
            "title",
            "from_date",
            "to_date",
            "sales_target",
            "collection_target",
            "visits_target",
            "target_setby",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "target_setby",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        request = self.context.get("request")
        user = request.user if request else None

        # Check field permissions
        if user and not user.is_owner:
            # Check sales_target
            if "sales_target" in attrs and not has_orders_manage_permission(user):
                raise serializers.ValidationError(
                    {"sales_target": "You do not have permission ('orders_manage') to set or update sales targets."}
                )
            # Check collection_target
            if "collection_target" in attrs and not has_collection_manage_permission(user):
                raise serializers.ValidationError(
                    {"collection_target": "You do not have permission ('collection_manage') to set or update collection targets."}
                )
            # Check visits_target
            if "visits_target" in attrs and not has_visit_manage_permission(user):
                raise serializers.ValidationError(
                    {"visits_target": "You do not have permission ('visit_manage') to set or update visits targets."}
                )

        from_date = attrs.get("from_date", getattr(self.instance, "from_date", None))
        to_date = attrs.get("to_date", getattr(self.instance, "to_date", None))

        if from_date and to_date and to_date < from_date:
            raise serializers.ValidationError(
                {"to_date": "to_date cannot be earlier than from_date."}
            )

        return attrs

