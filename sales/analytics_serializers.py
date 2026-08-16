"""
sales/analytics_serializers.py
================================
Dedicated, read-only serializers for the two Sales Analytics endpoints.

  GET /api/sales/order-analytics/          (employee)
  GET /api/admin/sales/order-analytics/    (admin)

These serializers are COMPLETELY SEPARATE from the existing order/collection
serializers and do NOT touch any existing API contracts.
"""

from rest_framework import serializers


# ---------------------------------------------------------------------------
# Nested: individual order-item in the orders list
# ---------------------------------------------------------------------------

class AnalyticsOrderItemSerializer(serializers.Serializer):
    """
    Represents a single OrderItem inside an analytics order record.
    Uses OrderItem.unit_price (historical) — never Product.price.
    line_total = quantity * unit_price  (computed in the view via annotation)
    """
    product_id   = serializers.UUIDField()
    product_name = serializers.CharField()
    quantity     = serializers.IntegerField()
    unit_price   = serializers.DecimalField(max_digits=12, decimal_places=2)
    line_total   = serializers.DecimalField(max_digits=12, decimal_places=2)


# ---------------------------------------------------------------------------
# Nested: minimal employee info inside order records
# ---------------------------------------------------------------------------

class AnalyticsEmployeeSerializer(serializers.Serializer):
    id   = serializers.UUIDField()
    name = serializers.CharField()


# ---------------------------------------------------------------------------
# Order-level record returned in the "orders" list
# ---------------------------------------------------------------------------

class AnalyticsOrderSerializer(serializers.Serializer):
    """
    One delivered order entry in the analytics response.
    """
    order_id     = serializers.UUIDField()
    date         = serializers.CharField()          # formatted as DD:MM:YYYY in the view
    employee     = AnalyticsEmployeeSerializer()
    sub_dealer   = serializers.CharField()          # shop_name string
    status       = serializers.CharField()
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    items        = AnalyticsOrderItemSerializer(many=True)


# ---------------------------------------------------------------------------
# Product-level aggregation
# ---------------------------------------------------------------------------

class ProductSalesSerializer(serializers.Serializer):
    """
    Per-product analytics row.
    total_sales = SUM(quantity * unit_price) using historical OrderItem prices.
    order_count = COUNT DISTINCT delivered orders containing this product.
    """
    product_id     = serializers.UUIDField()
    product_name   = serializers.CharField()
    unit           = serializers.CharField()
    total_quantity = serializers.IntegerField()
    total_sales    = serializers.DecimalField(max_digits=14, decimal_places=2)
    order_count    = serializers.IntegerField()


# ---------------------------------------------------------------------------
# Date-wise aggregation
# ---------------------------------------------------------------------------

class SalesByDateSerializer(serializers.Serializer):
    """
    Daily breakdown of delivered sales.
    """
    date         = serializers.CharField()          # formatted as DD:MM:YYYY
    total_sales  = serializers.DecimalField(max_digits=14, decimal_places=2)
    order_count  = serializers.IntegerField()
    items_sold   = serializers.IntegerField()


# ---------------------------------------------------------------------------
# Summary block
# ---------------------------------------------------------------------------

class AnalyticsSummarySerializer(serializers.Serializer):
    total_sales      = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_orders     = serializers.IntegerField()
    total_items_sold = serializers.IntegerField()
    total_products   = serializers.IntegerField()


# ---------------------------------------------------------------------------
# Filters block (echoes resolved filter values back to the caller)
# ---------------------------------------------------------------------------

class AnalyticsFiltersSerializer(serializers.Serializer):
    from_date   = serializers.CharField()
    to_date     = serializers.CharField()
    product_id  = serializers.UUIDField(allow_null=True)
    employee_id = serializers.UUIDField(allow_null=True)


# ---------------------------------------------------------------------------
# Top-level analytics response
# ---------------------------------------------------------------------------

class OrderAnalyticsResponseSerializer(serializers.Serializer):
    """
    Full response envelope for both analytics endpoints.
    """
    filters       = AnalyticsFiltersSerializer()
    summary       = AnalyticsSummarySerializer()
    product_sales = ProductSalesSerializer(many=True)
    sales_by_date = SalesByDateSerializer(many=True)
    orders        = AnalyticsOrderSerializer(many=True)
