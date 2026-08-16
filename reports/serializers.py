from rest_framework import serializers
from sales.models import MonthlyTarget
from users.models import Employee


class MonthlyTargetSerializer(serializers.ModelSerializer):
    employee_id = serializers.UUIDField(source="employee.id", read_only=True)
    employee_name = serializers.SerializerMethodField()
    employee = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.filter(is_active=True, is_deleted=False),
        required=True,
    )

    class Meta:
        model = MonthlyTarget
        fields = [
            "id",
            "employee",
            "employee_id",
            "employee_name",
            "year",
            "month",
            "sales_target",
            "collection_target",
            "visit_target",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_employee_name(self, obj):
        return obj.employee.name or obj.employee.username

    def validate_month(self, value):
        if value < 1 or value > 12:
            raise serializers.ValidationError("Month must be between 1 and 12.")
        return value

    def validate_year(self, value):
        if value < 2000 or value > 2100:
            raise serializers.ValidationError("Year must be a valid 4-digit year.")
        return value

    def validate_sales_target(self, value):
        if value < 0:
            raise serializers.ValidationError("Sales target cannot be negative.")
        return value

    def validate_collection_target(self, value):
        if value < 0:
            raise serializers.ValidationError("Collection target cannot be negative.")
        return value

    def validate_visit_target(self, value):
        if value < 0:
            raise serializers.ValidationError("Visit target cannot be negative.")
        return value

    def validate(self, attrs):
        employee = attrs.get("employee") or getattr(self.instance, "employee", None)
        year = attrs.get("year") or getattr(self.instance, "year", None)
        month = attrs.get("month") or getattr(self.instance, "month", None)

        if employee and year and month:
            qs = MonthlyTarget.objects.filter(employee=employee, year=year, month=month)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {"non_field_errors": [f"Monthly target already exists for {employee} for {year}-{month:02d}."]}
                )

        return attrs


class EODConfirmSerializer(serializers.Serializer):
    area = serializers.CharField(
        max_length=255, required=False, allow_blank=False,
        help_text="Tomorrow's planned visit area/market."
    )
    tomorrow_area = serializers.CharField(
        max_length=255, required=False, allow_blank=False
    )
    tomorrow_plan_area = serializers.CharField(
        max_length=255, required=False, allow_blank=False
    )

    visit_target = serializers.IntegerField(
        min_value=0, required=False,
        help_text="Tomorrow's planned visit count target."
    )
    tomorrow_visit_target = serializers.IntegerField(
        min_value=0, required=False
    )

    date = serializers.DateField(
        required=False,
        help_text="Date for the EOD report (YYYY-MM-DD). Defaults to today."
    )

    def validate(self, attrs):
        area = (
            attrs.get("area")
            or attrs.get("tomorrow_area")
            or attrs.get("tomorrow_plan_area")
        )
        if not area:
            raise serializers.ValidationError(
                {"area": "Tomorrow's visit plan area is required."}
            )

        visit_target = (
            attrs.get("visit_target")
            if attrs.get("visit_target") is not None
            else attrs.get("tomorrow_visit_target")
        )
        if visit_target is None:
            raise serializers.ValidationError(
                {"visit_target": "Tomorrow's visit target is required."}
            )

        attrs["resolved_area"] = area.strip()
        attrs["resolved_visit_target"] = int(visit_target)
        return attrs


class MorningConfirmSerializer(serializers.Serializer):
    date = serializers.DateField(
        required=False,
        help_text="Date for the morning report (YYYY-MM-DD). Defaults to today."
    )
