from rest_framework import serializers


class SODInputSerializer(serializers.Serializer):
    date = serializers.DateField(required=False, help_text="Target date (defaults to today)")
    today_sales_target = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, min_value=0,
        help_text="Today's sales target in currency"
    )
    today_collection_target = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, min_value=0,
        help_text="Today's collection target in currency"
    )
    today_visits_target = serializers.IntegerField(
        required=False, min_value=0,
        help_text="Today's target number of counter visits"
    )
    today_market_plan = serializers.CharField(
        required=False, allow_blank=True,
        help_text="Market visit plan / meeting location"
    )


class SODReportResponseSerializer(serializers.Serializer):
    officer_name = serializers.CharField()
    date = serializers.CharField()
    month_name = serializers.CharField()
    month_sales_target = serializers.CharField()
    till_now_sales = serializers.CharField()
    balance_sales_target = serializers.CharField()
    today_sales_target = serializers.CharField()
    month_collection_target = serializers.CharField()
    till_now_collection = serializers.CharField()
    balance_collection_target = serializers.CharField()
    today_collection_target = serializers.CharField()
    month_visits_target = serializers.IntegerField()
    till_now_visits = serializers.IntegerField()
    balance_visits_target = serializers.IntegerField()
    today_visits_target = serializers.IntegerField()
    today_market_plan = serializers.CharField(allow_blank=True)
    formatted_report = serializers.CharField()


class EODInputSerializer(serializers.Serializer):
    date = serializers.DateField(required=False, help_text="Target date (defaults to today)")
    visited_areas = serializers.CharField(
        required=False, allow_blank=True,
        help_text="Areas visited today (e.g. Chetpet, Avalurpet, polur)"
    )
    tomorrow_plan = serializers.CharField(
        required=False, allow_blank=True,
        help_text="Tomorrow visit plan area"
    )


class EODReportResponseSerializer(serializers.Serializer):
    officer_name = serializers.CharField()
    date = serializers.CharField()
    month_name = serializers.CharField()
    visited_areas = serializers.CharField(allow_blank=True)
    opening_km = serializers.FloatField(allow_null=True)
    closing_km = serializers.FloatField(allow_null=True)
    travel_km = serializers.FloatField(allow_null=True)
    today_orders_amount = serializers.CharField()
    orders_summary = serializers.CharField()
    today_collection_amount = serializers.CharField()
    visited_counters_count = serializers.IntegerField()
    tomorrow_plan = serializers.CharField(allow_blank=True)
    formatted_report = serializers.CharField()
