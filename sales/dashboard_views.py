"""
sales/dashboard_views.py
========================
Executive Admin Dashboard API:
  GET /api/admin/dashboard/

Features:
1. Today's Key Metrics:
   - Today's Orders (Count, Total Value, vs Yesterday % Change)
   - Today's Collections (Total Collected, Today's SOD/Target, Achievement %)
   - Today's Visits (Completed visits, Pending vs Target)
   - Today's New Leads (Count, Converted Count)
   - Today's New Dealers (Count)
   - Attendance (Total Sales Reps, Checked In Reps, %, Currently Working)
   - Total Distance (Total km travelled today by field staff)
   - Outstanding Balance (Total unpaid order due amount across business)

2. Monthly Performance Trend ("This & Last Month"):
   - Last 6 months orders vs collections breakdown (for chart)
   - This Month vs Last Month comparison metrics & growth percentages

3. Live Activity Feed ("Recent"):
   - Top N real-time activities across Attendance, Orders, Collections, Visits, Leads
   - Beautifully formatted for the live activity feed UI widget

Access Control:
- Restricted to Admin staff: Owner (1) ... Accountant (5) (IsAdminUser)
- Superior Protection: Non-owners only see data from equivalent/lower hierarchy level staff
- Password change enforcement (MustChangePasswordPermission)
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.db.models import (
    Case, Count, DecimalField, F, Q, Sum, Value, When,
)
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.models import Employee
from users.permissions import (
    IsAdminUser,
    MustChangePasswordPermission,
)
from sales.models import Order, Collection, MonthlyTarget
from dealers.models import SubDealer
from tracking.models import Attendance, Visit
from crm.models import Lead


# ---------------------------------------------------------------------------
# Formatting Helpers
# ---------------------------------------------------------------------------

def _format_indian_amount(amount: Decimal) -> str:
    """Format decimal amount into Indian short-scale notation (e.g. ₹28.4L, ₹1.24Cr)."""
    if amount is None:
        amount = Decimal("0.00")
    amount = Decimal(str(amount))
    crore = Decimal("10000000")
    lakh = Decimal("100000")
    thousand = Decimal("1000")

    if amount >= crore:
        val = (amount / crore).quantize(Decimal("0.01"))
        return f"₹{val}Cr"
    elif amount >= lakh:
        val = (amount / lakh).quantize(Decimal("0.01"))
        return f"₹{val}L"
    elif amount >= thousand:
        val = (amount / thousand).quantize(Decimal("0.01"))
        return f"₹{val}k"
    else:
        return f"₹{amount.quantize(Decimal('0.01'))}"


def _get_collection_rupee_expr():
    """Convert Collection.amount based on reference_id ('C'=Crore, 'L'=Lakh, 'T'=Thousand) into Rupees."""
    return Case(
        When(reference_id="C", then=F("amount") * Value(Decimal("10000000.0"))),
        When(reference_id="L", then=F("amount") * Value(Decimal("100000.0"))),
        When(reference_id="T", then=F("amount") * Value(Decimal("1000.0"))),
        default=F("amount"),
        output_field=DecimalField(max_digits=16, decimal_places=2),
    )


# ---------------------------------------------------------------------------
# Executive Dashboard View
# ---------------------------------------------------------------------------

class AdminDashboardView(APIView):
    """
    GET /api/admin/dashboard/
    Executive Real-time Operational Overview for Admin Web Portal.
    """
    permission_classes = [IsAuthenticated, MustChangePasswordPermission, IsAdminUser]

    @extend_schema(
        summary="Admin Executive Dashboard Overview",
        description=(
            "Returns real-time operational overview data including: "
            "Today's Orders, Collections, Visits, Leads, Dealers, Attendance, Distance, Outstanding Balance, "
            "Monthly Performance Trend (This & Last Month, 6-Month Trend), and Live Activity Feed."
        ),
        parameters=[
            OpenApiParameter(
                name="date",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Dashboard target date (format: YYYY-MM-DD or DD:MM:YYYY). Defaults to today.",
            ),
            OpenApiParameter(
                name="activity_limit",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Number of recent activities to return (default: 10, max: 50).",
            ),
        ],
        auth=[{"jwtAuth": []}],
    )
    def get(self, request):
        user = request.user

        # ── 1. Parse Target Date ───────────────────────────────────────────
        date_param = request.query_params.get("date")
        today = timezone.localdate()
        if date_param:
            try:
                if ":" in date_param:
                    target_date = datetime.strptime(date_param, "%d:%m:%Y").date()
                else:
                    target_date = datetime.strptime(date_param, "%Y-%m-%d").date()
            except ValueError:
                raise ValidationError({"date": "Invalid date format. Expected YYYY-MM-DD or DD:MM:YYYY."})
        else:
            target_date = today

        yesterday = target_date - timedelta(days=1)

        activity_limit = 10
        if request.query_params.get("activity_limit"):
            try:
                activity_limit = min(50, max(1, int(request.query_params.get("activity_limit"))))
            except ValueError:
                activity_limit = 10

        # ── 2. Hierarchy-aware Employee Scoping ───────────────────────────
        # Universal Hierarchy Constraint: non-owner sees only equivalent or lower hierarchy level staff
        emp_filter = Q(is_active=True, is_deleted=False)
        if not user.is_owner:
            emp_filter &= Q(role__hierarchy_level__gte=user.hierarchy_level)
            emp_filter &= ~Q(is_superuser=True)
            emp_filter &= ~Q(employeeidnum=0)

        scoped_employee_ids = list(Employee.objects.filter(emp_filter).values_list("id", flat=True))

        # Helper to scope querysets to accessible employees
        def scope_qs(qs, emp_field="employee"):
            if user.is_owner:
                return qs
            return qs.filter(**{f"{emp_field}__in": scoped_employee_ids})

        # ── 3. TODAY'S METRICS ─────────────────────────────────────────────

        # (a) Today's Orders
        orders_today_qs = scope_qs(
            Order.objects.filter(
                created_at__date=target_date,
                is_deleted=False
            ).exclude(status__in=["rejected", "cancelled"])
        )
        orders_today_count = orders_today_qs.count()
        orders_today_total = orders_today_qs.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")

        # Yesterday's Orders for comparison
        orders_yesterday_qs = scope_qs(
            Order.objects.filter(
                created_at__date=yesterday,
                is_deleted=False
            ).exclude(status__in=["rejected", "cancelled"])
        )
        orders_yesterday_count = orders_yesterday_qs.count()

        if orders_yesterday_count > 0:
            change_pct = round(((orders_today_count - orders_yesterday_count) / orders_yesterday_count) * 100, 1)
            orders_change_text = f"{'+' if change_pct >= 0 else ''}{change_pct}% vs yesterday"
        elif orders_today_count > 0:
            orders_change_text = "+100% vs yesterday"
            change_pct = 100.0
        else:
            orders_change_text = "0% vs yesterday"
            change_pct = 0.0

        # (b) Today's Collections
        colls_today_qs = scope_qs(
            Collection.objects.filter(
                created_at__date=target_date,
                status="success",
                is_deleted=False
            )
        )
        coll_today_agg = colls_today_qs.aggregate(
            total_rupees=Sum(_get_collection_rupee_expr()),
            count=Count("id")
        )
        colls_today_amount = coll_today_agg["total_rupees"] or Decimal("0.00")
        colls_today_count = coll_today_agg["count"] or 0

        # Today's Collection Target (from SOD targets submitted today by reps, or pro-rated monthly target)
        att_today_qs = scope_qs(Attendance.objects.filter(date=target_date))
        sod_coll_target = att_today_qs.aggregate(total=Sum("sod_collection_target"))["total"] or Decimal("0.00")

        # Fallback to monthly target pro-rated per day if SOD target is 0
        if sod_coll_target == 0:
            month_target = MonthlyTarget.objects.filter(year=target_date.year, month=target_date.month, employee=None).first()
            if month_target and month_target.collection_target > 0:
                sod_coll_target = (Decimal(str(month_target.collection_target)) / Decimal("30")).quantize(Decimal("0.01"))
            else:
                sod_coll_target = Decimal("3500000.00")  # Default benchmark ₹35.0L if unset

        coll_achievement_pct = round(float((colls_today_amount / sod_coll_target) * 100), 1) if sod_coll_target > 0 else 0.0

        # (c) Today's Visits
        visits_today_qs = scope_qs(Visit.objects.filter(created_at__date=target_date))
        visits_completed_count = visits_today_qs.count()
        sod_visits_target = att_today_qs.aggregate(total=Sum("sod_visits_target"))["total"] or 0
        pending_visits = max(0, sod_visits_target - visits_completed_count)

        # (d) Today's New Leads
        leads_today_qs = scope_qs(Lead.objects.filter(created_at__date=target_date, is_deleted=False))
        leads_today_count = leads_today_qs.count()
        leads_converted_today = leads_today_qs.filter(category="converted").count()

        # (e) Today's New Dealers
        dealers_today_qs = scope_qs(SubDealer.objects.filter(created_at__date=target_date, is_deleted=False))
        dealers_today_count = dealers_today_qs.count()

        # (f) Attendance
        # Total active sales reps
        reps_filter = Q(is_active=True, is_deleted=False)
        if not user.is_owner:
            reps_filter &= Q(role__hierarchy_level__gte=user.hierarchy_level)
            reps_filter &= ~Q(is_superuser=True)
            reps_filter &= ~Q(employeeidnum=0)
        # Target field reps: sales staff or hierarchy_level > 5
        field_reps_qs = Employee.objects.filter(reps_filter).filter(
            Q(role__name__iexact="SALESMAN") | Q(role__hierarchy_level__gt=5)
        )
        total_reps_count = field_reps_qs.count()
        if total_reps_count == 0:
            # Fallback to all scoped employees if no specific salesman role
            total_reps_count = len(scoped_employee_ids)

        checked_in_count = att_today_qs.values("employee").distinct().count()
        currently_working_count = att_today_qs.filter(work_now=True).count()
        attendance_pct = round((checked_in_count / total_reps_count) * 100, 1) if total_reps_count > 0 else 0.0

        # (g) Total Distance
        total_distance = att_today_qs.aggregate(total=Sum("total_km"))["total"] or 0.0
        if total_distance == 0.0:
            # Alternative: sum from visit travelled_km
            total_distance = visits_today_qs.aggregate(total=Sum("travelled_km"))["total"] or 0.0

        # (h) Outstanding Balance
        # Total due amount on all orders across the business
        orders_all_active = scope_qs(
            Order.objects.filter(is_deleted=False).exclude(status__in=["rejected", "cancelled"])
        )
        total_orders_value = orders_all_active.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")

        # Total successful collections
        colls_all_active = scope_qs(
            Collection.objects.filter(is_deleted=False, status="success")
        )
        total_colls_value = colls_all_active.aggregate(total=Sum(_get_collection_rupee_expr()))["total"] or Decimal("0.00")

        total_outstanding = max(Decimal("0.00"), total_orders_value - total_colls_value)

        # ── 4. MONTHLY PERFORMANCE TREND (This & Last Month + 6 Months) ───
        months_trend = []
        now = timezone.localtime(timezone.now())

        for i in range(5, -1, -1):
            m_date = now - relativedelta(months=i)
            m_year = m_date.year
            m_month = m_date.month
            m_name = m_date.strftime("%b")

            m_orders_qs = scope_qs(
                Order.objects.filter(
                    created_at__year=m_year,
                    created_at__month=m_month,
                    is_deleted=False
                ).exclude(status__in=["rejected", "cancelled"])
            )
            m_orders_count = m_orders_qs.count()
            m_orders_total = m_orders_qs.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")

            m_colls_qs = scope_qs(
                Collection.objects.filter(
                    created_at__year=m_year,
                    created_at__month=m_month,
                    status="success",
                    is_deleted=False
                )
            )
            m_colls_total = m_colls_qs.aggregate(total=Sum(_get_collection_rupee_expr()))["total"] or Decimal("0.00")

            months_trend.append({
                "year": m_year,
                "month": m_month,
                "month_name": m_name,
                "orders_count": m_orders_count,
                "orders_amount": float(m_orders_total),
                "orders_amount_formatted": _format_indian_amount(m_orders_total),
                "collections_amount": float(m_colls_total),
                "collections_amount_formatted": _format_indian_amount(m_colls_total),
            })

        # This Month vs Last Month
        this_month_data = months_trend[-1]
        last_month_data = months_trend[-2] if len(months_trend) >= 2 else months_trend[-1]

        def calc_growth(curr, prev):
            if prev > 0:
                return round(((curr - prev) / prev) * 100, 1)
            return 100.0 if curr > 0 else 0.0

        orders_growth = calc_growth(this_month_data["orders_amount"], last_month_data["orders_amount"])
        colls_growth = calc_growth(this_month_data["collections_amount"], last_month_data["collections_amount"])

        # ── 5. LIVE ACTIVITY FEED ("Recent Events") ───────────────────────
        recent_events = []

        # (a) Recent Attendances (Check-in & Check-out)
        recent_attendances = scope_qs(
            Attendance.objects.select_related("employee").order_by("-updated_at")
        )[:activity_limit]
        for att in recent_attendances:
            emp_name = att.employee.name or att.employee.username
            if att.end_time:
                total_hrs = ""
                if att.total_time:
                    hrs = round(att.total_time.total_seconds() / 3600, 1)
                    total_hrs = f" after {hrs} hrs"
                recent_events.append({
                    "id": f"att-end-{att.id}",
                    "type": "checkout",
                    "title": f"{emp_name} checked out{total_hrs}",
                    "description": f"Check-out at {att.end_location or 'field'}",
                    "employee_name": emp_name,
                    "timestamp": datetime.combine(att.date, att.end_time).isoformat() if att.end_time else att.updated_at.isoformat(),
                    "dt": datetime.combine(att.date, att.end_time) if att.end_time else att.updated_at,
                })
            elif att.start_time:
                loc = f" at {att.start_location}" if att.start_location else ""
                recent_events.append({
                    "id": f"att-start-{att.id}",
                    "type": "checkin",
                    "title": f"{emp_name} checked in{loc}",
                    "description": f"Start KM: {att.start_km}",
                    "employee_name": emp_name,
                    "timestamp": datetime.combine(att.date, att.start_time).isoformat() if att.start_time else att.created_at.isoformat(),
                    "dt": datetime.combine(att.date, att.start_time) if att.start_time else att.created_at,
                })

        # (b) Recent Orders
        recent_orders = scope_qs(
            Order.objects.select_related("employee", "sub_dealer").order_by("-created_at")
        )[:activity_limit]
        for ord_obj in recent_orders:
            emp_name = ord_obj.employee.name or ord_obj.employee.username
            dealer_name = ord_obj.sub_dealer.shop_name if ord_obj.sub_dealer else "Dealer"
            short_id = f"ORD{str(ord_obj.id)[:8].upper()}"
            recent_events.append({
                "id": f"order-{ord_obj.id}",
                "type": "order",
                "title": f"Order {short_id} created by {emp_name}",
                "description": f"For {dealer_name} — {_format_indian_amount(ord_obj.total_amount)} ({ord_obj.status})",
                "employee_name": emp_name,
                "timestamp": ord_obj.created_at.isoformat(),
                "dt": ord_obj.created_at,
            })

        # (c) Recent Collections
        recent_colls = scope_qs(
            Collection.objects.select_related("employee", "sub_dealer").order_by("-created_at")
        )[:activity_limit]
        for coll in recent_colls:
            emp_name = coll.employee.name or coll.employee.username
            dealer_name = coll.sub_dealer.shop_name if coll.sub_dealer else "Dealer"
            amt_formatted = _format_indian_amount(coll.amount)
            recent_events.append({
                "id": f"coll-{coll.id}",
                "type": "collection",
                "title": f"Collection {amt_formatted} ({coll.payment_type.upper()}) collected by {emp_name}",
                "description": f"From {dealer_name} — Status: {coll.status}",
                "employee_name": emp_name,
                "timestamp": coll.created_at.isoformat(),
                "dt": coll.created_at,
            })

        # (d) Recent Visits
        recent_visits = scope_qs(
            Visit.objects.select_related("employee", "dealer", "client").order_by("-created_at")
        )[:activity_limit]
        for vis in recent_visits:
            emp_name = vis.employee.name or vis.employee.username
            target_name = vis.dealer.shop_name if vis.dealer else (vis.client.shop_name if vis.client else "Client")
            recent_events.append({
                "id": f"visit-{vis.id}",
                "type": "visit",
                "title": f"{emp_name} completed visit at {target_name}",
                "description": f"Visit type: {vis.type}",
                "employee_name": emp_name,
                "timestamp": vis.created_at.isoformat(),
                "dt": vis.created_at,
            })

        # (e) Recent Leads
        recent_leads = scope_qs(
            Lead.objects.select_related("employee").filter(is_deleted=False).order_by("-created_at")
        )[:activity_limit]
        for ld in recent_leads:
            emp_name = ld.employee.name or ld.employee.username
            recent_events.append({
                "id": f"lead-{ld.id}",
                "type": "lead",
                "title": f"New lead created: {ld.name} by {emp_name}",
                "description": f"Company: {ld.company_name or 'N/A'} (Category: {ld.category})",
                "employee_name": emp_name,
                "timestamp": ld.created_at.isoformat(),
                "dt": ld.created_at,
            })

        # Sort combined events by datetime descending
        # Ensure comparison works even if naive vs timezone aware
        def sort_key(item):
            d = item["dt"]
            if timezone.is_naive(d):
                return timezone.make_aware(d)
            return d

        recent_events.sort(key=sort_key, reverse=True)
        final_activities = []
        for event in recent_events[:activity_limit]:
            dt = event.pop("dt")
            time_display = dt.strftime("%I:%M %p")
            event["time_display"] = time_display
            final_activities.append(event)

        # ── 6. COMPOSE RESPONSE PAYLOAD ───────────────────────────────────
        response_data = {
            "meta": {
                "date": target_date.strftime("%Y-%m-%d"),
                "date_display": target_date.strftime("%A, %d %B %Y"),
                "subtitle": "Real-time operational overview",
                "server_time": timezone.localtime().isoformat(),
            },
            "today_metrics": {
                "orders": {
                    "count": orders_today_count,
                    "total_amount": float(orders_today_total),
                    "total_amount_formatted": _format_indian_amount(orders_today_total),
                    "yesterday_count": orders_yesterday_count,
                    "change_percentage": change_pct,
                    "change_text": orders_change_text,
                },
                "collections": {
                    "count": colls_today_count,
                    "total_amount": float(colls_today_amount),
                    "total_amount_formatted": _format_indian_amount(colls_today_amount),
                    "target_amount": float(sod_coll_target),
                    "target_amount_formatted": _format_indian_amount(sod_coll_target),
                    "achievement_percentage": coll_achievement_pct,
                },
                "visits": {
                    "completed_count": visits_completed_count,
                    "target_count": sod_visits_target,
                    "pending_count": pending_visits,
                    "pending_text": f"{pending_visits} pending",
                },
                "leads": {
                    "new_count": leads_today_count,
                    "converted_count": leads_converted_today,
                },
                "dealers": {
                    "new_count": dealers_today_count,
                },
                "attendance": {
                    "checked_in_reps": checked_in_count,
                    "total_reps": total_reps_count,
                    "currently_working": currently_working_count,
                    "percentage": attendance_pct,
                    "summary_text": f"{checked_in_count} / {total_reps_count} reps Checked In",
                },
                "distance": {
                    "total_km": round(total_distance, 1),
                    "total_km_formatted": f"{int(total_distance):,} km" if total_distance >= 1000 else f"{round(total_distance, 1)} km",
                },
                "outstanding": {
                    "total_balance": float(total_outstanding),
                    "total_balance_formatted": _format_indian_amount(total_outstanding),
                },
            },
            "monthly_performance_trend": {
                "chart_months": months_trend,
                "this_vs_last_month": {
                    "this_month": this_month_data,
                    "last_month": last_month_data,
                    "orders_growth_percentage": orders_growth,
                    "collections_growth_percentage": colls_growth,
                },
            },
            "live_activity_feed": {
                "total_events": len(final_activities),
                "activities": final_activities,
            },
        }

        return Response(response_data)
