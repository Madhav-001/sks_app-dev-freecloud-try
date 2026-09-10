"""
users/employee_360_views.py
===========================
Employee 360 Full Detail API for Admin Web Portal:
  GET /api/admin/auth/employee/{id}/

Provides the complete single-page overview for an individual employee:
1. Profile & Status Header:
   - Name, username, employeeidnum, role, email, phone, joined_on, blood_group
   - Reporting to, Base location, Department
   - Real-time Duty Status: ON DUTY / OFF DUTY / ABSENT
   - Check-in time, duration, live location preview

2. Top Metric Cards (Today & Month comparisons):
   - Today's Orders count & total amount
   - Today's Sales amount & This Month sales
   - Today's Collection amount & This Month collections
   - Today's Visits count & This Month visits
   - Distance Travelled (Odometer & GPS)
   - Active Dealers visited today vs assigned

3. Middle Section:
   - Live Location & Map data (Current Location, Visited Dealers, Pending Dealers, Route Travelled points)
   - Today's Activity Timeline (Check-in, Dealer Visits, Orders created, Collections received, Check-out)
   - Target Achievement (This Month): Sales & Collection progress bars and percentages
   - Activity Summary (This Month): Total visits, total orders, dealers visited, total km

4. Performance Charts:
   - Sales Performance (Day-by-day sales data for this month)
   - Collection Performance (Day-by-day collections data for this month)
   - Attendance Summary (Present, Absent, Half Day counts, Total Working Hours, Avg. Daily Hours)

5. Supplementary Details & Tabs:
   - Assigned Dealers list with visit status today
   - Personal and contact details

Access Control:
- Restricted to Admin staff (hierarchy_level <= 5: Owner, Manager, etc.)
- Strict Superior Protection: Non-owners cannot access profile of an employee ranked higher than themselves
"""

import calendar
import uuid
from datetime import datetime, date, timedelta
from decimal import Decimal

from django.db.models import (
    Case, Count, DecimalField, F, Q, Sum, Value, When,
)
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.models import Employee
from users.permissions import (
    IsAdminUser,
    MustChangePasswordPermission,
)
from tracking.models import Attendance, Visit
from sales.models import Order, Collection, MonthlyTarget
from dealers.models import SubDealer


# ---------------------------------------------------------------------------
# Formatting Helpers
# ---------------------------------------------------------------------------

def _format_indian_amount(amount) -> str:
    """Format decimal amount into Indian currency string (e.g. ₹4.80L, ₹1.24Cr, ₹4,80,500)."""
    if amount is None:
        amount = Decimal("0.00")
    try:
        amount = Decimal(str(amount))
    except Exception:
        amount = Decimal("0.00")

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
    """Convert Collection.amount into exact Rupees based on reference_id ('C', 'L', 'T')."""
    return Case(
        When(reference_id="C", then=F("amount") * Value(Decimal("10000000.0"))),
        When(reference_id="L", then=F("amount") * Value(Decimal("100000.0"))),
        When(reference_id="T", then=F("amount") * Value(Decimal("1000.0"))),
        default=F("amount"),
        output_field=DecimalField(max_digits=16, decimal_places=2),
    )


def _format_time_ago(dt) -> str:
    """Return friendly relative time like '2 mins ago', '1 hour ago'."""
    if not dt:
        return "N/A"
    now = timezone.now()
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    diff = now - dt
    seconds = int(diff.total_seconds())
    if seconds < 60:
        return "Just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min{'s' if minutes > 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days > 1 else ''} ago"


# ---------------------------------------------------------------------------
# Employee 360 Detail View
# ---------------------------------------------------------------------------

class AdminEmployee360DetailView(APIView):
    """
    GET /api/admin/auth/employee/{id}/
    Comprehensive 360-degree Employee Detail view for Admin Web Portal.
    """
    permission_classes = [IsAuthenticated, MustChangePasswordPermission, IsAdminUser]

    @extend_schema(
        summary="Admin Employee 360 Detail Overview",
        description=(
            "Returns a complete 360-degree overview of an individual employee for the admin detail page. "
            "Includes personal details, real-time duty status, today's KPIs vs monthly metrics, live location, "
            "interactive map markers (visited & pending dealers, route points), activity timeline, "
            "target achievement vs targets, sales/collection curves, and monthly attendance summary."
        ),
        parameters=[
            OpenApiParameter(
                name="date",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Selected operational date in YYYY-MM-DD or DD:MM:YYYY format. Defaults to today.",
            ),
            OpenApiParameter(
                name="month",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Target month for performance analytics (1-12). Defaults to current month.",
            ),
            OpenApiParameter(
                name="year",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Target year for performance analytics (e.g. 2026). Defaults to current year.",
            ),
        ],
        auth=[{"jwtAuth": []}],
    )
    def get(self, request, id):
        requester = request.user

        # ── 1. Locate Employee (By UUID or employeeidnum) ─────────────────
        emp = None
        # Try UUID first
        try:
            val_uuid = uuid.UUID(str(id))
            emp = Employee.objects.filter(id=val_uuid, is_deleted=False).select_related("role").first()
        except (ValueError, TypeError):
            pass

        # Try integer employeeidnum fallback
        if not emp and str(id).isdigit():
            emp = Employee.objects.filter(employeeidnum=int(id), is_deleted=False).select_related("role").first()

        # Try username fallback
        if not emp:
            emp = Employee.objects.filter(username__iexact=str(id), is_deleted=False).select_related("role").first()

        if not emp:
            raise NotFound(detail=f"Employee '{id}' does not exist or has been deleted.")

        # ── 2. Hierarchy Access Check (Rule 5) ────────────────────────────
        # Universal Hierarchy Constraint: non-owner cannot view a superior
        if not requester.is_owner and emp.hierarchy_level < requester.hierarchy_level:
            raise PermissionDenied("You do not have permission to view this employee's details.")

        # ── 3. Resolve Target Date & Month ────────────────────────────────
        today = timezone.localdate()
        date_param = request.query_params.get("date")
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

        # Month & Year for monthly analytics
        target_year = target_date.year
        target_month = target_date.month
        if request.query_params.get("year"):
            try:
                target_year = int(request.query_params.get("year"))
            except ValueError:
                pass
        if request.query_params.get("month"):
            try:
                target_month = int(request.query_params.get("month"))
            except ValueError:
                pass

        # ── 4. Header & Profile Data ──────────────────────────────────────
        profile_pic_url = None
        if emp.profile_picture:
            try:
                profile_pic_url = request.build_absolute_uri(emp.profile_picture.url)
            except Exception:
                profile_pic_url = emp.profile_picture.url

        # Superior / Reporting To resolution
        reporting_to_name = "—"
        if not emp.is_owner:
            owner_user = Employee.objects.filter(is_superuser=True, is_active=True).first()
            if not owner_user:
                owner_user = Employee.objects.filter(employeeidnum=0, is_active=True).first()
            if owner_user:
                reporting_to_name = owner_user.name or owner_user.username

        # ── 5. Today's Attendance & Duty Status ───────────────────────────
        att_today = Attendance.objects.filter(employee=emp, date=target_date).first()

        is_on_duty = False
        status_text = "ABSENT"
        check_in_time_str = "—"
        check_out_time_str = "—"
        duration_str = "—"
        today_total_km = 0.0

        if att_today:
            today_total_km = round(att_today.total_km or 0.0, 1)
            if att_today.start_time:
                check_in_time_str = att_today.start_time.strftime("%I:%M %p")
            if att_today.end_time:
                check_out_time_str = att_today.end_time.strftime("%I:%M %p")
                status_text = "OFF DUTY"
                is_on_duty = False
            else:
                status_text = "ON DUTY"
                is_on_duty = True

            if att_today.total_time:
                total_secs = int(att_today.total_time.total_seconds())
                h = total_secs // 3600
                m = (total_secs % 3600) // 60
                duration_str = f"{h}h {m:02d}m"
            elif att_today.start_time and not att_today.end_time and target_date == today:
                # Active today, compute current duration
                now_time = timezone.localtime().time()
                t1 = datetime.combine(today, att_today.start_time)
                t2 = datetime.combine(today, now_time)
                secs = max(0, int((t2 - t1).total_seconds()))
                h = secs // 3600
                m = (secs % 3600) // 60
                duration_str = f"{h}h {m:02d}m"

        # ── 6. Live Location & Route Data ─────────────────────────────────
        # Priority: Visit -> Collection -> Order -> Attendance Check-In / Check-Out
        visits_today = list(
            Visit.objects.filter(employee=emp, created_at__date=target_date)
            .select_related("dealer", "client")
            .order_by("created_at")
        )

        colls_today = list(
            Collection.objects.filter(employee=emp, created_at__date=target_date, is_deleted=False)
            .select_related("sub_dealer")
            .order_by("created_at")
        )

        orders_today = list(
            Order.objects.filter(employee=emp, created_at__date=target_date, is_deleted=False)
            .select_related("sub_dealer")
            .order_by("created_at")
        )

        # Collect candidate coordinates
        candidate_locs = []

        # From visits
        for vis in visits_today:
            if vis.latitude is not None and vis.longitude is not None:
                vis_name = vis.dealer.shop_name if vis.dealer else (vis.client.shop_name if vis.client else "Visit Point")
                candidate_locs.append({
                    "priority": 1,
                    "type": "visit",
                    "lat": float(vis.latitude),
                    "lng": float(vis.longitude),
                    "name": vis_name,
                    "dt": vis.created_at,
                })

        # From collections
        for coll in colls_today:
            if coll.sub_dealer and coll.sub_dealer.latitude is not None and coll.sub_dealer.longitude is not None:
                candidate_locs.append({
                    "priority": 2,
                    "type": "collection",
                    "lat": float(coll.sub_dealer.latitude),
                    "lng": float(coll.sub_dealer.longitude),
                    "name": coll.sub_dealer.shop_name,
                    "dt": coll.created_at,
                })

        # From orders
        for ord_obj in orders_today:
            if ord_obj.sub_dealer and ord_obj.sub_dealer.latitude is not None and ord_obj.sub_dealer.longitude is not None:
                candidate_locs.append({
                    "priority": 3,
                    "type": "order",
                    "lat": float(ord_obj.sub_dealer.latitude),
                    "lng": float(ord_obj.sub_dealer.longitude),
                    "name": ord_obj.sub_dealer.shop_name,
                    "dt": ord_obj.created_at,
                })

        # From attendance
        if att_today:
            if att_today.end_latitude and att_today.end_longitude and att_today.end_time:
                end_dt = datetime.combine(att_today.date, att_today.end_time)
                if timezone.is_naive(end_dt):
                    end_dt = timezone.make_aware(end_dt)
                candidate_locs.append({
                    "priority": 4,
                    "type": "checkout",
                    "lat": float(att_today.end_latitude),
                    "lng": float(att_today.end_longitude),
                    "name": att_today.end_location or "Check-Out Location",
                    "dt": end_dt,
                })
            elif att_today.start_latitude and att_today.start_longitude and att_today.start_time:
                start_dt = datetime.combine(att_today.date, att_today.start_time)
                if timezone.is_naive(start_dt):
                    start_dt = timezone.make_aware(start_dt)
                candidate_locs.append({
                    "priority": 5,
                    "type": "checkin",
                    "lat": float(att_today.start_latitude),
                    "lng": float(att_today.start_longitude),
                    "name": att_today.start_location or "Check-In Location",
                    "dt": start_dt,
                })

        # Determine current active location
        current_loc = None
        if candidate_locs:
            candidate_locs.sort(key=lambda x: (x["dt"], -x["priority"]), reverse=True)
            current_loc = candidate_locs[0]

        # Build route points for the map line (chronological order)
        route_points = []
        visited_points_chrono = sorted(
            [c for c in candidate_locs if c["lat"] and c["lng"]],
            key=lambda x: x["dt"]
        )
        for pt in visited_points_chrono:
            route_points.append([pt["lat"], pt["lng"]])

        # Assigned dealers vs visited dealers
        assigned_dealers_qs = SubDealer.objects.filter(employee=emp, is_deleted=False)
        assigned_dealers = list(assigned_dealers_qs)
        total_assigned_dealers = len(assigned_dealers)

        visited_dealer_ids = set()
        for vis in visits_today:
            if vis.dealer_id:
                visited_dealer_ids.add(vis.dealer_id)

        visited_dealers_list = []
        pending_dealers_list = []
        for d in assigned_dealers:
            d_item = {
                "id": str(d.id),
                "shop_name": d.shop_name,
                "owner_name": d.owner_name,
                "phone": d.phone or "",
                "district": d.district or "",
                "rank": d.rank,
                "latitude": float(d.latitude) if d.latitude is not None else None,
                "longitude": float(d.longitude) if d.longitude is not None else None,
                "visited_today": d.id in visited_dealer_ids,
            }
            if d.id in visited_dealer_ids:
                visited_dealers_list.append(d_item)
            else:
                pending_dealers_list.append(d_item)

        # ── 7. Today's Metric KPI Cards ───────────────────────────────────
        # (a) Orders
        orders_today_non_rejected = [o for o in orders_today if o.status not in ("rejected", "cancelled")]
        today_orders_count = len(orders_today_non_rejected)
        today_orders_amount = sum((o.total_amount or Decimal("0.00") for o in orders_today_non_rejected), Decimal("0.00"))

        # Month Orders & Sales
        orders_month_qs = Order.objects.filter(
            employee=emp,
            created_at__year=target_year,
            created_at__month=target_month,
            is_deleted=False
        ).exclude(status__in=["rejected", "cancelled"])
        month_orders_count = orders_month_qs.count()
        month_sales_amount = orders_month_qs.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")

        # (b) Collections
        colls_today_success = [c for c in colls_today if c.status == "success"]
        colls_today_agg = (
            Collection.objects.filter(
                id__in=[c.id for c in colls_today_success]
            ).aggregate(total=Sum(_get_collection_rupee_expr()))
        ) if colls_today_success else {"total": Decimal("0.00")}
        today_colls_amount = colls_today_agg["total"] or Decimal("0.00")

        # Month Collections
        colls_month_qs = Collection.objects.filter(
            employee=emp,
            created_at__year=target_year,
            created_at__month=target_month,
            status="success",
            is_deleted=False
        )
        month_colls_amount = colls_month_qs.aggregate(total=Sum(_get_collection_rupee_expr()))["total"] or Decimal("0.00")

        # (c) Visits
        today_visits_count = len(visits_today)
        month_visits_count = Visit.objects.filter(
            employee=emp,
            created_at__year=target_year,
            created_at__month=target_month
        ).count()

        # (d) Distance
        gps_distance_today = sum((float(v.travelled_km or 0.0) for v in visits_today))
        today_gps_km = round(gps_distance_today, 1)

        # ── 8. Today's Activity Timeline ──────────────────────────────────
        timeline_events = []

        if att_today and att_today.start_time:
            s_dt = datetime.combine(att_today.date, att_today.start_time)
            if timezone.is_naive(s_dt):
                s_dt = timezone.make_aware(s_dt)
            timeline_events.append({
                "time": att_today.start_time.strftime("%I:%M %p"),
                "dt": s_dt,
                "type": "checkin",
                "title": "Checked In",
                "description": f"Attendance marked (Start KM: {att_today.start_km})",
            })

        for vis in visits_today:
            target_name = vis.dealer.shop_name if vis.dealer else (vis.client.shop_name if vis.client else "Client")
            vis_dt = vis.created_at
            if timezone.is_naive(vis_dt):
                vis_dt = timezone.make_aware(vis_dt)
            timeline_events.append({
                "time": vis_dt.strftime("%I:%M %p"),
                "dt": vis_dt,
                "type": "visit",
                "title": "Visited Dealer",
                "description": target_name,
            })

        for ord_obj in orders_today:
            ord_dt = ord_obj.created_at
            if timezone.is_naive(ord_dt):
                ord_dt = timezone.make_aware(ord_dt)
            short_id = f"#{str(ord_obj.id)[:8].upper()}"
            timeline_events.append({
                "time": ord_dt.strftime("%I:%M %p"),
                "dt": ord_dt,
                "type": "order",
                "title": "Order Created",
                "description": f"Order {short_id} · {_format_indian_amount(ord_obj.total_amount)}",
            })

        for coll in colls_today:
            coll_dt = coll.created_at
            if timezone.is_naive(coll_dt):
                coll_dt = timezone.make_aware(coll_dt)
            timeline_events.append({
                "time": coll_dt.strftime("%I:%M %p"),
                "dt": coll_dt,
                "type": "collection",
                "title": "Collection",
                "description": f"{_format_indian_amount(coll.amount)} received ({coll.payment_type.upper()})",
            })

        if att_today and att_today.end_time:
            e_dt = datetime.combine(att_today.date, att_today.end_time)
            if timezone.is_naive(e_dt):
                e_dt = timezone.make_aware(e_dt)
            timeline_events.append({
                "time": att_today.end_time.strftime("%I:%M %p"),
                "dt": e_dt,
                "type": "checkout",
                "title": "Checked Out",
                "description": f"Duty ended (Total KM: {att_today.total_km})",
            })

        # Sort timeline chronologically
        timeline_events.sort(key=lambda x: x["dt"])
        final_timeline = []
        for ev in timeline_events:
            ev.pop("dt", None)
            final_timeline.append(ev)

        # ── 9. Target Achievement (This Month) ─────────────────────────────
        # MonthlyTarget: check individual target first, fallback to common
        month_target = MonthlyTarget.objects.filter(
            year=target_year,
            month=target_month,
            employee=emp
        ).first()
        if not month_target:
            month_target = MonthlyTarget.objects.filter(
                year=target_year,
                month=target_month,
                employee=None
            ).first()

        # Sales Target
        sales_target_val = Decimal(str(month_target.sales_target)) if month_target else Decimal("5000000.00")
        if sales_target_val < 1000:
            # Stored in tons, convert tons to approx rupee value benchmark (e.g. 50L) or use benchmark
            sales_target_val = Decimal("5000000.00")

        sales_pct = round(float((month_sales_amount / sales_target_val) * 100), 1) if sales_target_val > 0 else 0.0

        # Collection Target
        coll_target_val = Decimal(str(month_target.collection_target)) if month_target else Decimal("3000000.00")
        if coll_target_val < 1000:
            # Stored in Cr, convert to Rupees
            coll_target_val = coll_target_val * Decimal("10000000.0")

        coll_pct = round(float((month_colls_amount / coll_target_val) * 100), 1) if coll_target_val > 0 else 0.0

        # Activity summary this month
        month_dealers_visited = Visit.objects.filter(
            employee=emp,
            created_at__year=target_year,
            created_at__month=target_month
        ).values("dealer").distinct().count()

        month_distance_km = (
            Attendance.objects.filter(
                employee=emp,
                date__year=target_year,
                date__month=target_month
            ).aggregate(total=Sum("total_km"))["total"] or 0.0
        )

        # ── 10. Performance Curves (Daily Sales & Collections for Month) ───
        days_in_month = calendar.monthrange(target_year, target_month)[1]
        sales_performance_curve = []
        collection_performance_curve = []

        daily_orders_agg = {
            row["day"]: row["total"] or Decimal("0.00")
            for row in (
                Order.objects.filter(
                    employee=emp,
                    created_at__year=target_year,
                    created_at__month=target_month,
                    is_deleted=False
                ).exclude(status__in=["rejected", "cancelled"])
                .annotate(day=F("created_at__day"))
                .values("day")
                .annotate(total=Sum("total_amount"))
            )
        }

        daily_colls_agg = {
            row["day"]: row["total"] or Decimal("0.00")
            for row in (
                Collection.objects.filter(
                    employee=emp,
                    created_at__year=target_year,
                    created_at__month=target_month,
                    status="success",
                    is_deleted=False
                )
                .annotate(day=F("created_at__day"))
                .values("day")
                .annotate(total=Sum(_get_collection_rupee_expr()))
            )
        }

        for day in range(1, days_in_month + 1):
            s_val = daily_orders_agg.get(day, Decimal("0.00"))
            c_val = daily_colls_agg.get(day, Decimal("0.00"))
            d_str = f"{target_year}-{target_month:02d}-{day:02d}"

            sales_performance_curve.append({
                "day": day,
                "date": d_str,
                "amount": float(s_val),
                "amount_formatted": _format_indian_amount(s_val),
            })
            collection_performance_curve.append({
                "day": day,
                "date": d_str,
                "amount": float(c_val),
                "amount_formatted": _format_indian_amount(c_val),
            })

        # ── 11. Attendance Summary (This Month) ───────────────────────────
        att_month_qs = Attendance.objects.filter(
            employee=emp,
            date__year=target_year,
            date__month=target_month
        )
        present_days = att_month_qs.count()

        # Working days so far in month
        max_possible_days = min(today.day if target_year == today.year and target_month == today.month else days_in_month, days_in_month)
        absent_days = max(0, max_possible_days - present_days)

        # Half day: duration < 5 hours
        half_days = 0
        total_worked_seconds = 0
        for a in att_month_qs:
            if a.total_time:
                secs = int(a.total_time.total_seconds())
                total_worked_seconds += secs
                if secs < 18000:  # < 5 hrs
                    half_days += 1

        total_work_hours = total_worked_seconds // 3600
        avg_seconds = (total_worked_seconds // present_days) if present_days > 0 else 0
        avg_h = avg_seconds // 3600
        avg_m = (avg_seconds % 3600) // 60
        avg_daily_hours_str = f"{avg_h:02d}h {avg_m:02d}m"

        # ── 12. Compose Final Response ────────────────────────────────────
        response_data = {
            "employee": {
                "id": str(emp.id),
                "employeeidnum": emp.employeeidnum,
                "name": emp.name or emp.username,
                "username": emp.username,
                "role": emp.role.display_name if emp.role else "Salesman",
                "role_key": emp.role.name if emp.role else "SALESMAN",
                "hierarchy_level": emp.hierarchy_level,
                "email": emp.email or "",
                "phone": emp.phone or "—",
                "profile_picture": profile_pic_url,
                "joined_on": emp.date_of_join.strftime("%d %b %Y") if emp.date_of_join else "25 Aug 2026",
                "blood_group": emp.blood_group or "N/A",
                "reporting_to": reporting_to_name,
                "base_location": emp.district or emp.state or "Chennai",
                "department": "Sales",
            },
            "today_status": {
                "date": target_date.strftime("%Y-%m-%d"),
                "is_on_duty": is_on_duty,
                "status_text": status_text,
                "check_in_time": check_in_time_str,
                "check_out_time": check_out_time_str,
                "duration": duration_str,
                "live_location": {
                    "location_name": current_loc["name"] if current_loc else (emp.district or "Chennai"),
                    "latitude": current_loc["lat"] if current_loc else None,
                    "longitude": current_loc["lng"] if current_loc else None,
                    "last_updated": _format_time_ago(current_loc["dt"]) if current_loc else "Offline",
                },
            },
            "metrics": {
                "today_orders": {
                    "count": today_orders_count,
                    "amount": float(today_orders_amount),
                    "amount_formatted": _format_indian_amount(today_orders_amount),
                },
                "today_sales": {
                    "amount": float(today_orders_amount),
                    "amount_formatted": _format_indian_amount(today_orders_amount),
                    "month_amount": float(month_sales_amount),
                    "month_amount_formatted": _format_indian_amount(month_sales_amount),
                    "subtitle": f"This Month: {_format_indian_amount(month_sales_amount)}",
                },
                "today_collection": {
                    "amount": float(today_colls_amount),
                    "amount_formatted": _format_indian_amount(today_colls_amount),
                    "month_amount": float(month_colls_amount),
                    "month_amount_formatted": _format_indian_amount(month_colls_amount),
                    "subtitle": f"This Month: {_format_indian_amount(month_colls_amount)}",
                },
                "today_visits": {
                    "count": today_visits_count,
                    "month_count": month_visits_count,
                    "subtitle": f"This Month: {month_visits_count}",
                },
                "distance_travelled": {
                    "total_km": today_total_km,
                    "total_km_formatted": f"{int(today_total_km)} km" if today_total_km >= 1 else f"{today_total_km} km",
                    "gps_km": today_gps_km,
                    "subtitle": f"By GPS: {int(today_gps_km)} km",
                },
                "active_dealers": {
                    "visited_count": len(visited_dealer_ids),
                    "total_assigned": total_assigned_dealers,
                    "subtitle": "Visited",
                },
            },
            "live_location_map": {
                "current_location": {
                    "address": current_loc["name"] if current_loc else "No active location",
                    "latitude": current_loc["lat"] if current_loc else None,
                    "longitude": current_loc["lng"] if current_loc else None,
                    "last_updated": _format_time_ago(current_loc["dt"]) if current_loc else "Offline",
                },
                "visited_dealers": visited_dealers_list,
                "pending_dealers": pending_dealers_list,
                "route_points": route_points,
            },
            "today_activity_timeline": {
                "total_events": len(final_timeline),
                "timeline": final_timeline,
            },
            "target_achievement": {
                "month_name": calendar.month_name[target_month],
                "year": target_year,
                "sales_target": {
                    "achieved": float(month_sales_amount),
                    "achieved_formatted": _format_indian_amount(month_sales_amount),
                    "target": float(sales_target_val),
                    "target_formatted": _format_indian_amount(sales_target_val),
                    "percentage": sales_pct,
                    "display_text": f"{_format_indian_amount(month_sales_amount)} / {_format_indian_amount(sales_target_val)}  {int(sales_pct)}%",
                },
                "collection_target": {
                    "achieved": float(month_colls_amount),
                    "achieved_formatted": _format_indian_amount(month_colls_amount),
                    "target": float(coll_target_val),
                    "target_formatted": _format_indian_amount(coll_target_val),
                    "percentage": coll_pct,
                    "display_text": f"{_format_indian_amount(month_colls_amount)} / {_format_indian_amount(coll_target_val)}  {int(coll_pct)}%",
                },
                "activity_summary": {
                    "total_visits": month_visits_count,
                    "total_orders": month_orders_count,
                    "dealers_visited": month_dealers_visited,
                    "total_distance_km": round(month_distance_km, 1),
                },
            },
            "charts": {
                "sales_performance": {
                    "month_name": calendar.month_name[target_month],
                    "data": sales_performance_curve,
                },
                "collection_performance": {
                    "month_name": calendar.month_name[target_month],
                    "data": collection_performance_curve,
                },
                "attendance_summary": {
                    "month_name": calendar.month_name[target_month],
                    "present_days": present_days,
                    "absent_days": absent_days,
                    "half_days": half_days,
                    "total_working_hours": f"{total_work_hours}h",
                    "avg_daily_hours": avg_daily_hours_str,
                },
            },
            "assigned_dealers": [
                {
                    "id": str(d.id),
                    "shop_name": d.shop_name,
                    "owner_name": d.owner_name,
                    "phone": d.phone or "",
                    "district": d.district or "",
                    "rank": d.rank,
                    "visited_today": d.id in visited_dealer_ids,
                }
                for d in assigned_dealers
            ],
        }

        return Response(response_data, status=status.HTTP_200_OK)
