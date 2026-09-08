"""
sales/analytics_views.py
=========================
Two new, read-only Sales Analytics endpoints.

  GET /api/sales/order-analytics/          — EmployeeOrderAnalyticsView
  GET /api/admin/sales/order-analytics/    — AdminOrderAnalyticsView

RULES (strictly enforced):
  • Only "delivered" orders are included.
  • Soft-deleted Orders, OrderItems, Products are excluded via the
    normal SoftDeleteManager (objects.all() already filters is_deleted=False).
  • Historical sales use OrderItem.quantity × OrderItem.unit_price.
    Product.price is NEVER used in any calculation.
  • Date range defaults to today → today when no params are supplied.
  • Six-month data availability window is enforced; older requests → HTTP 400.
  • Employee endpoint is always scoped to the authenticated user.
  • Admin endpoint requires has_orders_manage_permission(user).
  • Admin endpoint supports optional employee_id filter (hierarchy-checked).
"""

from datetime import datetime
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from django.db.models import (
    Count, DecimalField, ExpressionWrapper, F, Prefetch, Q, Sum,
)
from django.db.models.functions import TruncDate
from django.utils import timezone

from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.models import Employee
from users.permissions import (
    IsOwnerOrOrdersManage,
    MustChangePasswordPermission,
)

from .analytics_serializers import OrderAnalyticsResponseSerializer
from .models import Order, OrderItem


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DELIVERED = "delivered"
DATE_FORMAT = "%d:%m:%Y"           # DD:MM:YYYY  — matches existing project convention
SIX_MONTHS = 6                     # calendar months


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _is_null(val):
    """Return True when a query-param value is absent / empty / 'null'."""
    return val is None or val == "" or str(val).lower() in ("null", "none")


def _parse_date(value, field_name):
    """Parse DD:MM:YYYY → date, or raise HTTP 400 ValidationError."""
    try:
        return datetime.strptime(value, DATE_FORMAT).date()
    except ValueError:
        raise ValidationError(
            {field_name: f"Invalid date format '{value}'. Expected DD:MM:YYYY (e.g. 10:08:2026)."}
        )


def _format_date(date_obj):
    """Format a date object as DD:MM:YYYY string."""
    return date_obj.strftime(DATE_FORMAT)


def _resolve_date_range(from_date_str, to_date_str):
    """
    Apply the project's six-month date rules and return (from_date, to_date).

    Rules:
      • No params           → today, today
      • from_date only      → from_date, today
      • to_date only        → (to_date − 6 months), to_date
      • Both                → from_date, to_date (validated)

    Raises HTTP 400 for:
      • Invalid date format
      • from_date > to_date
      • Either date is older than (today − 6 calendar months)
      • Requested range itself exceeds 6 calendar months
    """
    today = timezone.localdate()
    oldest_allowed = today - relativedelta(months=SIX_MONTHS)

    no_from = _is_null(from_date_str)
    no_to   = _is_null(to_date_str)

    if no_from and no_to:
        # Default: today only
        return today, today

    if not no_from and no_to:
        # Only from_date supplied → to_date = today
        from_date = _parse_date(from_date_str, "from_date")
        to_date   = today

    elif no_from and not no_to:
        # Only to_date supplied → from_date = to_date − 6 months (max window)
        to_date   = _parse_date(to_date_str, "to_date")
        from_date = to_date - relativedelta(months=SIX_MONTHS)
        # Clamp from_date to oldest_allowed (it may already equal it)
        if from_date < oldest_allowed:
            from_date = oldest_allowed

    else:
        # Both supplied
        from_date = _parse_date(from_date_str, "from_date")
        to_date   = _parse_date(to_date_str,   "to_date")

    # ── Validation ────────────────────────────────────────────────────────

    if from_date > to_date:
        raise ValidationError(
            {"date_range": "from_date cannot be later than to_date."}
        )

    if from_date < oldest_allowed:
        raise ValidationError(
            {
                "from_date": (
                    f"Date '{_format_date(from_date)}' is outside the 6-month data availability window. "
                    f"The oldest allowed date is '{_format_date(oldest_allowed)}'."
                )
            }
        )

    if to_date < oldest_allowed:
        raise ValidationError(
            {
                "to_date": (
                    f"Date '{_format_date(to_date)}' is outside the 6-month data availability window. "
                    f"The oldest allowed date is '{_format_date(oldest_allowed)}'."
                )
            }
        )

    # Range itself must not exceed 6 calendar months
    range_end_limit = from_date + relativedelta(months=SIX_MONTHS)
    if to_date > range_end_limit:
        raise ValidationError(
            {
                "date_range": (
                    f"The requested date range exceeds the maximum allowed 6-month window. "
                    f"from_date='{_format_date(from_date)}' allows a maximum to_date of "
                    f"'{_format_date(range_end_limit)}'."
                )
            }
        )

    return from_date, to_date


# ---------------------------------------------------------------------------
# Core analytics builder  (shared by both views)
# ---------------------------------------------------------------------------

def _build_analytics(order_qs, product_id_filter):
    """
    Given a pre-filtered Order queryset (already restricted to status=delivered,
    correct employee scope, and date range), build the full analytics payload.

    Args:
        order_qs        : QuerySet of Order (delivered, non-deleted, scoped)
        product_id_filter: UUID str or None

    Returns a dict ready for OrderAnalyticsResponseSerializer.
    """

    # ── Optional product filter ───────────────────────────────────────────
    # Applied to OrderItem-level queries, not to the order queryset itself,
    # so that order_count reflects orders containing the product (not all orders).
    item_filter = Q(items__is_deleted=False, items__product__is_deleted=False)
    if not _is_null(product_id_filter):
        item_filter &= Q(items__product_id=product_id_filter)

    # ── Line-total expression (Decimal-safe, uses historical unit_price) ──
    line_total_expr = ExpressionWrapper(
        F("items__quantity") * F("items__unit_price"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )

    # ── Summary ───────────────────────────────────────────────────────────
    # Count distinct orders first to avoid cartesian product inflation
    distinct_order_ids = order_qs.filter(item_filter).values("id").distinct()

    summary_agg = (
        OrderItem.objects
        .filter(
            order_id__in=distinct_order_ids,
            is_deleted=False,
            product__is_deleted=False,
        )
    )
    if not _is_null(product_id_filter):
        summary_agg = summary_agg.filter(product_id=product_id_filter)

    summary_data = summary_agg.aggregate(
        total_sales=Sum(
            ExpressionWrapper(
                F("quantity") * F("unit_price"),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        ),
        total_items_sold=Sum("quantity"),
        total_products=Count("product_id", distinct=True),
    )
    total_orders = distinct_order_ids.count()

    summary = {
        "total_sales":      summary_data["total_sales"]      or Decimal("0.00"),
        "total_orders":     total_orders,
        "total_items_sold": summary_data["total_items_sold"] or 0,
        "total_products":   summary_data["total_products"]   or 0,
    }

    # ── Product-wise aggregation ──────────────────────────────────────────
    # Uses OrderItem.quantity × OrderItem.unit_price — NOT Product.price
    product_qs = (
        OrderItem.objects
        .filter(
            order_id__in=distinct_order_ids,
            is_deleted=False,
            product__is_deleted=False,
        )
    )
    if not _is_null(product_id_filter):
        product_qs = product_qs.filter(product_id=product_id_filter)

    product_rows = (
        product_qs
        .values(
            "product__id",
            "product__name",
            "product__unit",
        )
        .annotate(
            total_quantity=Sum("quantity"),
            total_sales=Sum(
                ExpressionWrapper(
                    F("quantity") * F("unit_price"),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            ),
            order_count=Count("order_id", distinct=True),
        )
        .order_by("-total_sales")
    )

    product_sales = [
        {
            "product_id":     row["product__id"],
            "product_name":   row["product__name"],
            "unit":           row["product__unit"],
            "total_quantity": row["total_quantity"] or 0,
            "total_sales":    row["total_sales"]    or Decimal("0.00"),
            "order_count":    row["order_count"]    or 0,
        }
        for row in product_rows
    ]

    # ── Date-wise aggregation ─────────────────────────────────────────────
    date_item_qs = (
        OrderItem.objects
        .filter(
            order_id__in=distinct_order_ids,
            is_deleted=False,
            product__is_deleted=False,
        )
        .select_related("order")
    )
    if not _is_null(product_id_filter):
        date_item_qs = date_item_qs.filter(product_id=product_id_filter)

    date_rows = (
        date_item_qs
        .annotate(sale_date=TruncDate("order__created_at"))
        .values("sale_date")
        .annotate(
            total_sales=Sum(
                ExpressionWrapper(
                    F("quantity") * F("unit_price"),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            ),
            order_count=Count("order_id", distinct=True),
            items_sold=Sum("quantity"),
        )
        .order_by("sale_date")
    )

    sales_by_date = [
        {
            "date":        _format_date(row["sale_date"]),
            "total_sales": row["total_sales"] or Decimal("0.00"),
            "order_count": row["order_count"] or 0,
            "items_sold":  row["items_sold"]  or 0,
        }
        for row in date_rows
    ]

    # ── Order-level details ───────────────────────────────────────────────
    # Prefetch only non-deleted items (filtered by product if needed)
    item_prefetch_qs = (
        OrderItem.objects
        .filter(is_deleted=False, product__is_deleted=False)
        .select_related("product")
    )
    if not _is_null(product_id_filter):
        item_prefetch_qs = item_prefetch_qs.filter(product_id=product_id_filter)

    orders_db = (
        order_qs
        .filter(item_filter)
        .distinct()
        .select_related("employee", "sub_dealer")
        .prefetch_related(
            Prefetch("items", queryset=item_prefetch_qs, to_attr="prefetched_items")
        )
        .order_by("-created_at")
    )

    orders_out = []
    for order in orders_db:
        items_out = []
        for item in order.prefetched_items:
            items_out.append(
                {
                    "product_id":   item.product_id,
                    "product_name": item.product.name,
                    "quantity":     item.quantity,
                    "unit_price":   item.unit_price,
                    "line_total":   item.quantity * item.unit_price,  # Decimal × Decimal
                }
            )
        orders_out.append(
            {
                "order_id":     order.id,
                "date":         _format_date(
                                    timezone.localtime(order.created_at).date()
                                ),
                "employee":     {
                                    "id":   order.employee_id,
                                    "name": order.employee.name or order.employee.username,
                                },
                "sub_dealer":   order.sub_dealer.shop_name,
                "status":       order.status,
                "total_amount": order.total_amount,
                "items":        items_out,
            }
        )

    return {
        "summary":       summary,
        "product_sales": product_sales,
        "sales_by_date": sales_by_date,
        "orders":        orders_out,
    }


# ---------------------------------------------------------------------------
# Employee Analytics View
# ---------------------------------------------------------------------------

_EMPLOYEE_PARAMS = [
    OpenApiParameter(
        name="from_date",
        type=OpenApiTypes.STR,
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            "Start date — format: DD:MM:YYYY (e.g. 01:05:2026). "
            "Omit to default to today. Must be within the last 6 calendar months."
        ),
    ),
    OpenApiParameter(
        name="to_date",
        type=OpenApiTypes.STR,
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            "End date — format: DD:MM:YYYY (e.g. 31:05:2026). "
            "Omit to default to today (when from_date is also absent) or today (when only from_date is given). "
            "When only to_date is provided, from_date defaults to to_date − 6 months. "
            "Must be within the last 6 calendar months."
        ),
    ),
    OpenApiParameter(
        name="product_id",
        type=OpenApiTypes.UUID,
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            "Optional product UUID. Filters all analytics sections "
            "(product_sales, sales_by_date, orders) to the specified product only. "
            "Soft-deleted products are rejected."
        ),
    ),
]


class EmployeeOrderAnalyticsView(APIView):
    """
    GET /api/sales/order-analytics/

    Read-only sales analytics for the authenticated employee.

    Scope: ONLY the authenticated employee's own delivered orders.
    The employee_id is determined from the JWT token — not from query params.
    Passing employee_id as a query param is NOT supported on this endpoint.

    Data restrictions:
    - Only status=delivered orders are included.
    - Soft-deleted orders, order items, and products are excluded.
    - Sales figures use OrderItem.unit_price (historical), NOT Product.price.
    - Date range defaults to today→today when no params are supplied.
    - Maximum historical window: today − 6 calendar months.
    """

    permission_classes = [IsAuthenticated, MustChangePasswordPermission]

    @extend_schema(
        summary="Employee sales analytics (delivered orders only)",
        description=(
            "Returns delivered-order analytics scoped to the authenticated employee. "
            "Includes summary totals, per-product aggregation, daily sales, and order details. "
            "All figures use the historical unit_price stored on each OrderItem. "
            "Date range defaults to today when no params are given. "
            "Maximum allowed historical window is 6 calendar months."
        ),
        parameters=_EMPLOYEE_PARAMS,
        responses={200: OrderAnalyticsResponseSerializer},
        auth=[{"jwtAuth": []}],
    )
    def get(self, request):
        user = request.user

        # ── Date range resolution ─────────────────────────────────────────
        from_date, to_date = _resolve_date_range(
            request.query_params.get("from_date"),
            request.query_params.get("to_date"),
        )

        # ── Product filter ────────────────────────────────────────────────
        product_id = request.query_params.get("product_id") or None
        if not _is_null(product_id):
            from .models import Product
            try:
                Product.objects.get(pk=product_id)
            except (Product.DoesNotExist, Exception):
                raise ValidationError(
                    {"product_id": f"Product '{product_id}' does not exist or has been deleted."}
                )

        # ── Base queryset: employee-scoped, delivered, date-filtered ──────
        order_qs = (
            Order.objects.filter(
                employee=user,
                status=DELIVERED,
                created_at__date__gte=from_date,
                created_at__date__lte=to_date,
            )
        )

        # ── Build analytics ───────────────────────────────────────────────
        analytics = _build_analytics(order_qs, product_id)

        # ── Compose response ──────────────────────────────────────────────
        response_data = {
            "filters": {
                "from_date":   _format_date(from_date),
                "to_date":     _format_date(to_date),
                "product_id":  product_id,
                "employee_id": None,
            },
            **analytics,
        }

        return Response(response_data)


# ---------------------------------------------------------------------------
# Admin Analytics View
# ---------------------------------------------------------------------------

_ADMIN_PARAMS = _EMPLOYEE_PARAMS + [
    OpenApiParameter(
        name="employee_id",
        type=OpenApiTypes.UUID,
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            "Optional employee UUID. Filters analytics to a specific employee's delivered orders. "
            "The requesting admin must have hierarchy authority over the target employee "
            "(i.e., admin.can_manage(target) must be True). "
            "Owner can filter by any employee. "
            "If omitted, returns analytics across all employees."
        ),
    ),
]


class AdminOrderAnalyticsView(APIView):
    """
    GET /api/admin/sales/order-analytics/

    Read-only sales analytics for authorized admin users.

    Access: Owner or any role with orders_manage=True.

    Scope: All employees' delivered orders (optionally filtered by employee_id).
    The employee_id filter is hierarchy-checked — the admin must have
    authority over the target employee via the existing can_manage() system.

    Data restrictions: same as the employee endpoint.
      - Only status=delivered orders.
      - Soft-deleted data excluded.
      - Historical OrderItem.unit_price used for all sales figures.
      - Six-month data availability window enforced.
    """

    permission_classes = [IsAuthenticated, MustChangePasswordPermission, IsOwnerOrOrdersManage]

    @extend_schema(
        summary="Admin sales analytics (delivered orders only)",
        description=(
            "Returns delivered-order analytics for all employees or a specific employee. "
            "Requires Owner role or a role with orders_manage=True. "
            "The employee_id filter is validated against the admin's hierarchy authority. "
            "All figures use historical OrderItem.unit_price. "
            "Date range defaults to today when no params are given. "
            "Maximum allowed historical window is 6 calendar months."
        ),
        parameters=_ADMIN_PARAMS,
        responses={200: OrderAnalyticsResponseSerializer},
        auth=[{"jwtAuth": []}],
    )
    def get(self, request):
        user = request.user

        # ── Date range resolution ─────────────────────────────────────────
        from_date, to_date = _resolve_date_range(
            request.query_params.get("from_date"),
            request.query_params.get("to_date"),
        )

        # ── Product filter ────────────────────────────────────────────────
        product_id = request.query_params.get("product_id") or None
        if not _is_null(product_id):
            from .models import Product
            try:
                Product.objects.get(pk=product_id)
            except (Product.DoesNotExist, Exception):
                raise ValidationError(
                    {"product_id": f"Product '{product_id}' does not exist or has been deleted."}
                )

        # ── Employee filter ───────────────────────────────────────────────
        employee_id = request.query_params.get("employee_id") or None
        target_employee = None

        if not _is_null(employee_id):
            # Look up the target employee (exclude hard-deleted records)
            try:
                target_employee = Employee._base_manager.get(
                    pk=employee_id, is_deleted=False
                )
            except Employee.DoesNotExist:
                raise ValidationError(
                    {"employee_id": f"Employee '{employee_id}' does not exist or has been deleted."}
                )

            # Hierarchy check: owner bypasses; others must outrank the target
            if not user.is_owner and not user.can_manage(target_employee):
                raise PermissionDenied(
                    "You do not have authority to view analytics for this employee."
                )

        # ── Base queryset ─────────────────────────────────────────────────
        order_qs = Order.objects.filter(
            status=DELIVERED,
            created_at__date__gte=from_date,
            created_at__date__lte=to_date,
        )
        if target_employee is not None:
            order_qs = order_qs.filter(employee=target_employee)
        elif not user.is_owner:
            order_qs = order_qs.filter(
                employee__role__hierarchy_level__gte=user.hierarchy_level
            ).exclude(employee__is_superuser=True).exclude(employee__employeeidnum=0)

        # ── Build analytics ───────────────────────────────────────────────
        analytics = _build_analytics(order_qs, product_id)

        # ── Compose response ──────────────────────────────────────────────
        response_data = {
            "filters": {
                "from_date":   _format_date(from_date),
                "to_date":     _format_date(to_date),
                "product_id":  product_id,
                "employee_id": str(employee_id) if employee_id else None,
            },
            **analytics,
        }

        return Response(response_data)
