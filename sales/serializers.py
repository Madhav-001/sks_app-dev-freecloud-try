from decimal import Decimal

from django.db.models import Count, Sum, Case, When, F, Value, DecimalField
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Order statuses that count as "processed" (i.e. the sale went through).
_PROCESSED_ORDER_STATUSES = ["approve", "in_transit", "delivered"]


def _format_cr_amount(cr_amount: Decimal) -> str:
    """
    Format decimal Cr value for API JSON string output.
    Keeps 2 decimal places for standard Cr/Lakh amounts (e.g. '0.30', '1.50'),
    or up to 4 decimal places for Thousand amounts (e.g. '0.007').
    """
    if cr_amount is None:
        return "0.00"
    cr_amount = Decimal(str(cr_amount))
    if cr_amount == 0:
        return "0.00"
    q2 = cr_amount.quantize(Decimal("0.01"))
    if q2 == cr_amount:
        return str(q2)
    s = f"{cr_amount:.4f}".rstrip("0").rstrip(".")
    if "." in s:
        decimals = len(s.split(".")[1])
        if decimals < 2:
            return f"{cr_amount:.2f}"
    return s


def _format_cr_display(cr_amount: Decimal) -> str:
    """
    Format decimal Cr value into short Cr display string.
    Examples:
      1.50  → "1.5Cr"
      2.00  → "2Cr"
      0.30  → "0.3Cr"
      0.007 → "0.007Cr"
      0.00  → "0Cr"
    """
    if cr_amount is None:
        return "0Cr"
    cr_amount = Decimal(str(cr_amount))
    if cr_amount == 0:
        return "0Cr"
    s = f"{cr_amount:.4f}".rstrip("0").rstrip(".")
    if not s or s == "0":
        return "0Cr"
    return f"{s}Cr"


def _format_indian_amount(amount: Decimal) -> str:
    """
    Format a decimal amount into the Indian short-scale notation.

    Examples:
      1_057_893  → "10.58L"
      25_000_000 → "2.5Cr"
      9_500      → "9500"   (below 1 Lakh, returned as plain integer string)
    """
    amount = Decimal(str(amount))
    crore = Decimal("10000000")   # 1 Cr  = 10,000,000
    lakh  = Decimal("100000")     # 1 L   = 1,00,000

    if amount >= crore:
        value = (amount / crore).quantize(Decimal("0.01")).normalize()
        return f"{value}Cr"
    elif amount >= lakh:
        value = (amount / lakh).quantize(Decimal("0.01")).normalize()
        return f"{value}L"
    else:
        return str(int(amount))


def _format_target_dict(target_obj) -> dict:
    """Format sales_target, collection_target, visits_target into standard dict."""
    if not target_obj:
        return None
    coll = Decimal(str(target_obj.collection_target))
    return {
        "sales_tons": round(float(target_obj.sales_target), 3),
        "collection_amount": _format_cr_amount(coll),
        "collection_amount_display": _format_cr_display(coll),
        "visits_count": target_obj.visits_target,
    }


def _build_achieved(employee_id, orders_qs, collections_qs, visits_qs) -> dict:
    """
    Compute the three achievement metrics given pre-filtered querysets.

    Parameters
    ----------
    employee_id   : PK of the employee (used to filter each queryset)
    orders_qs     : base Orders queryset already filtered to the right period
    collections_qs: base Collections queryset already filtered to the right period
    visits_qs     : base Visits queryset already filtered to the right period

    Returns a dict with keys: sales_tons, collection_amount, collection_count,
    collection_amount_display, visits_count.
    """
    # ── Sales weight in tons ────────────────────────────────────────────────
    processed_orders = orders_qs.filter(
        employee_id=employee_id,
        status__in=_PROCESSED_ORDER_STATUSES,
    ).values_list("id", flat=True)

    total_qty = (
        OrderItem.objects
        .filter(order_id__in=processed_orders)
        .aggregate(total=Sum("quantity"))["total"]
        or 0
    )
    # quantity unit = 1 kg  →  tons = qty / 1000
    sales_tons = round(total_qty / 1000, 3)

    # ── Approved collections in Cr ──────────────────────────────────────────
    # Convert amounts based on reference_id ('C'=Crore, 'L'=Lakh, 'T'=Thousand)
    # Result stored directly in Cr:
    #   'C' -> amount * 1.0 (already in Cr)
    #   'L' -> amount * 0.01 (1 Lakh = 0.01 Cr)
    #   'T' -> amount * 0.0001 (1 Thousand = 0.0001 Cr)
    #   other/null -> amount / 10,000,000 (if raw rupees)
    coll_agg = (
        collections_qs
        .filter(employee_id=employee_id, status="success")
        .aggregate(
            total_cr=Sum(
                Case(
                    When(reference_id="C", then=F("amount") * Value(Decimal("1.000000"))),
                    When(reference_id="L", then=F("amount") * Value(Decimal("0.010000"))),
                    When(reference_id="T", then=F("amount") * Value(Decimal("0.000100"))),
                    default=F("amount") / Value(Decimal("10000000.0")),
                    output_field=DecimalField(max_digits=14, decimal_places=6),
                )
            ),
            count=Count("id"),
        )
    )
    coll_cr = coll_agg["total_cr"] or Decimal("0.00")
    coll_count = coll_agg["count"] or 0

    # ── Visits ──────────────────────────────────────────────────────────────
    visits_count = visits_qs.filter(employee_id=employee_id).count()

    return {
        "sales_tons": round(sales_tons, 3),
        "collection_amount": _format_cr_amount(coll_cr),
        "collection_amount_display": _format_cr_display(coll_cr),
        "collection_count": coll_count,
        "visits_count": visits_count,
    }


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
    role = serializers.CharField(source="role.name", read_only=True, default=None)

    class Meta:
        model = Employee
        fields = ["id", "employeeidnum", "name", "username", "phone", "role"]


class MonthlyTargetSerializer(serializers.ModelSerializer):
    """Serializer used for reading MonthlyTarget (both admin and employee GET)."""
    employee_details = SimpleEmployeeSummarySerializer(source="employee", read_only=True)
    target_setby_details = SimpleEmployeeSummarySerializer(source="target_setby", read_only=True)
    target = serializers.SerializerMethodField()
    achieved = serializers.SerializerMethodField()

    class Meta:
        model = MonthlyTarget
        fields = [
            "id",
            "employee",
            "employee_details",
            "year",
            "month",
            "target",
            "achieved",
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

    def get_target(self, obj):
        """
        Return the set targets in the same shape as `achieved` for easy comparison.

        sales_tons          : target in tons (3 decimal places, e.g. 1.250)
        collection_amount   : raw decimal amount string
        collection_amount_display: Indian short-scale (e.g. 10.58L, 2.5Cr)
        visits_count        : target visit count
        """
        coll = Decimal(str(obj.collection_target))
        return {
            "sales_tons": round(float(obj.sales_target), 3),
            "collection_amount": _format_cr_amount(coll),
            "collection_amount_display": _format_cr_display(coll),
            "visits_count": obj.visits_target,
        }

    def get_achieved(self, obj):
        """
        Return the current achievement stats for this employee in this month/year.

        sales_tons          : total kg sold (non-pending/rejected orders) ÷ 1000 → tons
        collection_amount   : sum of approved (status='success') collections
        collection_count    : number of approved collection records
        visits_count        : total visits logged this calendar month
        """
        from tracking.models import Visit

        orders_qs      = Order.objects.filter(created_at__year=obj.year, created_at__month=obj.month)
        collections_qs = Collection.objects.filter(created_at__year=obj.year, created_at__month=obj.month)
        visits_qs      = Visit.objects.filter(created_at__year=obj.year, created_at__month=obj.month)

        emp_id = obj.employee_id
        if emp_id is None and self.context.get("request") and hasattr(self.context["request"], "user"):
            emp_id = getattr(self.context["request"].user, "id", None)

        return _build_achieved(emp_id, orders_qs, collections_qs, visits_qs)


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

        # Duplicate PK check on create only
        if not self.instance:
            employee = attrs.get("employee")   # may be None for common target
            year     = attrs.get("year")
            month    = attrs.get("month")
            if year and month:
                # Build the PK the same way the model's save() will
                if employee is None:
                    target_id = f"{int(year):04d}-{int(month):02d}"
                    label     = "common"
                    scope     = f"{month}/{year}"
                else:
                    target_id = f"{int(year):04d}-{int(month):02d}-{employee.employeeidnum}"
                    label     = "individual"
                    scope     = f"employee '{employee.username}' for {month}/{year}"

                if MonthlyTarget.objects.filter(id=target_id).exists():
                    raise serializers.ValidationError(
                        {"non_field_errors": [
                            f"A {label} monthly target already exists for {scope}. "
                            "Use PATCH to update the existing target."
                        ]}
                    )

        return attrs


class SpecialTargetSerializer(serializers.ModelSerializer):
    """Serializer used for reading SpecialTarget (both admin and employee GET)."""
    employee_details = SimpleEmployeeSummarySerializer(source="employee", read_only=True)
    target_setby_details = SimpleEmployeeSummarySerializer(source="target_setby", read_only=True)
    target = serializers.SerializerMethodField()
    achieved = serializers.SerializerMethodField()

    class Meta:
        model = SpecialTarget
        fields = [
            "id",
            "employee",
            "employee_details",
            "title",
            "from_date",
            "to_date",
            "target",
            "achieved",
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

    def get_target(self, obj):
        """
        Return the set targets in the same shape as `achieved` for easy comparison.

        sales_tons          : target in tons (3 decimal places, e.g. 1.250)
        collection_amount   : raw decimal amount string
        collection_amount_display: Indian short-scale (e.g. 10.58L, 2.5Cr)
        visits_count        : target visit count
        """
        coll = Decimal(str(obj.collection_target))
        return {
            "sales_tons": round(float(obj.sales_target), 3),
            "collection_amount": _format_cr_amount(coll),
            "collection_amount_display": _format_cr_display(coll),
            "visits_count": obj.visits_target,
        }

    def get_achieved(self, obj):
        """
        Return the current achievement stats for this employee for the special
        event's date window (from_date … to_date, inclusive).

        sales_tons          : total kg sold (non-pending/rejected orders) ÷ 1000 → tons
        collection_amount   : sum of approved (status='success') collections
        collection_count    : number of approved collection records
        visits_count        : total visits logged within the event window
        """
        from tracking.models import Visit

        orders_qs = Order.objects.filter(
            created_at__date__gte=obj.from_date,
            created_at__date__lte=obj.to_date,
        )
        collections_qs = Collection.objects.filter(
            created_at__date__gte=obj.from_date,
            created_at__date__lte=obj.to_date,
        )
        visits_qs = Visit.objects.filter(
            created_at__date__gte=obj.from_date,
            created_at__date__lte=obj.to_date,
        )

        emp_id = obj.employee_id
        if emp_id is None and self.context.get("request") and hasattr(self.context["request"], "user"):
            emp_id = getattr(self.context["request"].user, "id", None)

        return _build_achieved(emp_id, orders_qs, collections_qs, visits_qs)


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


class TargetMetricSerializer(serializers.Serializer):
    sales_tons = serializers.FloatField(help_text="Target sales in tons (e.g. 1.25)")
    collection_amount = serializers.CharField(help_text="Target collection amount in Cr e.g. '1.50'")
    collection_amount_display = serializers.CharField(help_text="Formatted Cr notation e.g. '1.5Cr'")
    visits_count = serializers.IntegerField(help_text="Target visits count")


class TargetAchievedSerializer(serializers.Serializer):
    sales_tons = serializers.FloatField(help_text="Achieved sales in tons")
    collection_amount = serializers.CharField(help_text="Achieved approved collection amount in Cr e.g. '0.30'")
    collection_amount_display = serializers.CharField(help_text="Formatted Cr notation e.g. '0.3Cr'")
    collection_count = serializers.IntegerField(help_text="Number of approved collections")
    visits_count = serializers.IntegerField(help_text="Number of visits logged")


class EmployeeMonthlyTargetNestedSerializer(serializers.Serializer):
    employee = SimpleEmployeeSummarySerializer()
    target_type = serializers.ChoiceField(choices=["individual", "common", "none"])
    target_id = serializers.CharField(allow_null=True)
    is_custom = serializers.BooleanField()
    target = TargetMetricSerializer(allow_null=True)
    achieved = TargetAchievedSerializer()
    target_setby = serializers.UUIDField(allow_null=True)
    target_setby_details = SimpleEmployeeSummarySerializer(allow_null=True)
    created_at = serializers.DateTimeField(allow_null=True)
    updated_at = serializers.DateTimeField(allow_null=True)


class CommonTargetSummarySerializer(serializers.Serializer):
    id = serializers.CharField()
    sales_target = serializers.FloatField()
    collection_target = serializers.CharField()
    visits_target = serializers.IntegerField()
    target = TargetMetricSerializer()
    target_setby = serializers.UUIDField(allow_null=True)
    target_setby_details = SimpleEmployeeSummarySerializer(allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class MonthTargetNestedListSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Month ID e.g. '2026-09'")
    year = serializers.IntegerField()
    month = serializers.IntegerField()
    common_target = CommonTargetSummarySerializer(allow_null=True)
    total_employees = serializers.IntegerField()
    individual_targets_count = serializers.IntegerField()
    common_targets_count = serializers.IntegerField()
    employees = EmployeeMonthlyTargetNestedSerializer(many=True)

