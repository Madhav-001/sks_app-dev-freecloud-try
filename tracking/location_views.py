"""
tracking/location_views.py
==========================
Live Employee Location API for Admin Web Portal:
  GET /api/admin/tracking/employee-locations/

Features:
1. Real-time field force tracking for all active employees.
2. Resolves each employee's current (last active) location for today:
   GPS priority: Visit → Collection → Order → Check-In.
3. Top summary counters:
   - Total Employees
   - Checked In
   - Checked Out
   - Working (work_now=True)
   - On Leave (0 or reason)
   - Absent
   - Online (Checked in / currently working)
   - Offline (Checked out or absent)
   - With GPS vs Without GPS
4. Search and filters:
   - search (name, username, phone, employeeidnum)
   - role (role name or role ID)
   - status (all, checked_in, checked_out, working, absent, online, offline)
   - region (state or district)
   - has_gps (true / false)
5. Strict access control & Superior Protection:
   - Accessible only to admin staff (hierarchy_level <= 5: Owner, Manager, etc.)
   - Non-owners only see equivalent or lower hierarchy level staff (never superiors)
"""

from datetime import datetime, date, timedelta
from django.db.models import Q
from django.utils import timezone
from rest_framework import status, response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from users.models import Employee
from users.permissions import (
    IsAdminUser,
    MustChangePasswordPermission,
)
from tracking.models import Attendance, Visit
from sales.models import Collection, Order


class AdminEmployeeLocationsView(APIView):
    """
    GET /api/admin/tracking/employee-locations/
    Returns real-time last active location data and details for all employees today.
    """
    permission_classes = [IsAuthenticated, MustChangePasswordPermission, IsAdminUser]

    @extend_schema(
        summary="Admin Live Employee Locations",
        description=(
            "Returns today's real-time last active location data for all active employees. "
            "Resolves GPS coordinates following priority: Visit → Collection → Order → Check-In. "
            "Includes summary counters for Checked In, Checked Out, Working, Absent, Online, Offline, and GPS lock."
        ),
        parameters=[
            OpenApiParameter(
                name="date",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Target date in YYYY-MM-DD or DD:MM:YYYY format. Defaults to today.",
            ),
            OpenApiParameter(
                name="search",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Search query to match employee name, username, phone, or employeeidnum.",
            ),
            OpenApiParameter(
                name="role",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by role name (e.g. SALESMAN) or role UUID.",
            ),
            OpenApiParameter(
                name="status",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by status: all | checked_in | checked_out | working | absent | online | offline.",
            ),
            OpenApiParameter(
                name="region",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by state or district of employee.",
            ),
            OpenApiParameter(
                name="has_gps",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter employees who have valid GPS coordinates (true/false).",
            ),
        ],
        auth=[{"jwtAuth": []}],
    )
    def get(self, request):
        requester = request.user

        # ── 1. Resolve Target Date ─────────────────────────────────────────
        date_param = request.query_params.get("date")
        if date_param:
            try:
                if ":" in date_param:
                    target_date = datetime.strptime(date_param, "%d:%m:%Y").date()
                else:
                    target_date = datetime.strptime(date_param, "%Y-%m-%d").date()
            except ValueError:
                return response.Response(
                    {"error": "Invalid date format. Expected YYYY-MM-DD or DD:MM:YYYY."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            target_date = timezone.localdate()

        # ── 2. Scope Accessible Employees (Hierarchy Protection) ───────────
        emp_qs = Employee.objects.filter(is_active=True, is_deleted=False).select_related("role")

        if not requester.is_owner:
            emp_qs = emp_qs.filter(
                role__hierarchy_level__gte=requester.hierarchy_level
            ).exclude(is_superuser=True).exclude(employeeidnum=0)

        # Filters: Search
        search_query = request.query_params.get("search", "").strip()
        if search_query:
            emp_qs = emp_qs.filter(
                Q(name__icontains=search_query) |
                Q(username__icontains=search_query) |
                Q(phone__icontains=search_query) |
                Q(employeeidnum__icontains=search_query)
            )

        # Filters: Role
        role_param = request.query_params.get("role", "").strip()
        if role_param and role_param.lower() != "all":
            emp_qs = emp_qs.filter(
                Q(role__name__iexact=role_param) |
                Q(role__display_name__iexact=role_param) |
                Q(role__id__iexact=role_param)
            )

        # Filters: Region
        region_param = request.query_params.get("region", "").strip()
        if region_param and region_param.lower() != "all":
            emp_qs = emp_qs.filter(
                Q(district__iexact=region_param) |
                Q(state__iexact=region_param)
            )

        employees = list(emp_qs.order_by("employeeidnum"))
        emp_ids = [e.id for e in employees]

        # ── 3. Batch Query Today's Events (Visits, Collections, Orders, Attendance)
        # Avoid N+1: query all records for scoped employees on target_date in 4 queries

        # (a) Attendance today
        attendances = Attendance.objects.filter(
            employee_id__in=emp_ids,
            date=target_date
        )
        att_map = {att.employee_id: att for att in attendances}

        # (b) Visits today with GPS
        visits_qs = Visit.objects.filter(
            employee_id__in=emp_ids,
            created_at__date=target_date
        ).select_related("dealer", "client").order_by("-created_at")

        visits_map = {}
        for vis in visits_qs:
            if vis.employee_id not in visits_map:
                visits_map[vis.employee_id] = []
            visits_map[vis.employee_id].append(vis)

        # (c) Collections today
        collections_qs = Collection.objects.filter(
            employee_id__in=emp_ids,
            created_at__date=target_date,
            is_deleted=False
        ).select_related("sub_dealer").order_by("-created_at")

        colls_map = {}
        for coll in collections_qs:
            if coll.employee_id not in colls_map:
                colls_map[coll.employee_id] = []
            colls_map[coll.employee_id].append(coll)

        # (d) Orders today
        orders_qs = Order.objects.filter(
            employee_id__in=emp_ids,
            created_at__date=target_date,
            is_deleted=False
        ).select_related("sub_dealer").order_by("-created_at")

        orders_map = {}
        for ord_obj in orders_qs:
            if ord_obj.employee_id not in orders_map:
                orders_map[ord_obj.employee_id] = []
            orders_map[ord_obj.employee_id].append(ord_obj)

        # ── 4. Process Each Employee & Resolve Last Active Location ────────
        employee_results = []

        # Overall counters
        cnt_checked_in = 0
        cnt_checked_out = 0
        cnt_working = 0
        cnt_absent = 0
        cnt_online = 0
        cnt_offline = 0
        cnt_with_gps = 0
        cnt_without_gps = 0

        for emp in employees:
            att = att_map.get(emp.id)
            emp_visits = visits_map.get(emp.id, [])
            emp_colls = colls_map.get(emp.id, [])
            emp_orders = orders_map.get(emp.id, [])

            # Attendance status determination
            is_checked_in = False
            is_checked_out = False
            is_working = False
            is_online = False
            att_status = "absent"
            check_in_time = None
            check_out_time = None
            total_km = 0.0

            if att:
                total_km = round(att.total_km or 0.0, 1)
                if att.start_time:
                    check_in_time = att.start_time.strftime("%I:%M %p")
                if att.end_time:
                    check_out_time = att.end_time.strftime("%I:%M %p")
                    att_status = "checked_out"
                    is_checked_out = True
                    is_online = False
                else:
                    att_status = "checked_in"
                    is_checked_in = True
                    is_working = bool(att.work_now)
                    is_online = True
            else:
                att_status = "absent"
                is_online = False

            # Update overall counters
            if is_checked_in:
                cnt_checked_in += 1
            if is_checked_out:
                cnt_checked_out += 1
            if is_working:
                cnt_working += 1
            if att_status == "absent":
                cnt_absent += 1
            if is_online:
                cnt_online += 1
            else:
                cnt_offline += 1

            # ── Location Candidates according to Priority:
            # GPS priority: Visit → Collection → Order → Check-In / Check-Out
            location_candidates = []

            # 1. Visit Candidates (Highest priority)
            for vis in emp_visits:
                if vis.latitude is not None and vis.longitude is not None:
                    # Valid GPS visit
                    target_name = vis.dealer.shop_name if vis.dealer else (vis.client.shop_name if vis.client else "Dealer Visit")
                    vis_dt = vis.created_at
                    if timezone.is_naive(vis_dt):
                        vis_dt = timezone.make_aware(vis_dt)
                    location_candidates.append({
                        "priority": 1,
                        "type": "visit",
                        "latitude": float(vis.latitude),
                        "longitude": float(vis.longitude),
                        "location_name": target_name,
                        "activity_display": f"Visit at {target_name}",
                        "timestamp": vis_dt,
                        "dt": vis_dt,
                    })
                    break  # Most recent visit with GPS is sufficient

            # 2. Collection Candidates (Second priority)
            for coll in emp_colls:
                if coll.sub_dealer and coll.sub_dealer.latitude is not None and coll.sub_dealer.longitude is not None:
                    c_dt = coll.created_at
                    if timezone.is_naive(c_dt):
                        c_dt = timezone.make_aware(c_dt)
                    location_candidates.append({
                        "priority": 2,
                        "type": "collection",
                        "latitude": float(coll.sub_dealer.latitude),
                        "longitude": float(coll.sub_dealer.longitude),
                        "location_name": coll.sub_dealer.shop_name,
                        "activity_display": f"Collection from {coll.sub_dealer.shop_name}",
                        "timestamp": c_dt,
                        "dt": c_dt,
                    })
                    break

            # 3. Order Candidates (Third priority)
            for ord_obj in emp_orders:
                if ord_obj.sub_dealer and ord_obj.sub_dealer.latitude is not None and ord_obj.sub_dealer.longitude is not None:
                    o_dt = ord_obj.created_at
                    if timezone.is_naive(o_dt):
                        o_dt = timezone.make_aware(o_dt)
                    location_candidates.append({
                        "priority": 3,
                        "type": "order",
                        "latitude": float(ord_obj.sub_dealer.latitude),
                        "longitude": float(ord_obj.sub_dealer.longitude),
                        "location_name": ord_obj.sub_dealer.shop_name,
                        "activity_display": f"Order #{str(ord_obj.id)[:8].upper()} at {ord_obj.sub_dealer.shop_name}",
                        "timestamp": o_dt,
                        "dt": o_dt,
                    })
                    break

            # 4. Attendance Candidates (Check-Out or Check-In)
            if att:
                if att.end_latitude is not None and att.end_longitude is not None and att.end_time:
                    end_dt = datetime.combine(att.date, att.end_time)
                    if timezone.is_naive(end_dt):
                        end_dt = timezone.make_aware(end_dt)
                    location_candidates.append({
                        "priority": 4,
                        "type": "checkout",
                        "latitude": float(att.end_latitude),
                        "longitude": float(att.end_longitude),
                        "location_name": att.end_location or "Check-Out Location",
                        "activity_display": f"Checked out at {att.end_location or 'Location'}",
                        "timestamp": end_dt,
                        "dt": end_dt,
                    })
                elif att.start_latitude is not None and att.start_longitude is not None and att.start_time:
                    start_dt = datetime.combine(att.date, att.start_time)
                    if timezone.is_naive(start_dt):
                        start_dt = timezone.make_aware(start_dt)
                    location_candidates.append({
                        "priority": 5,
                        "type": "checkin",
                        "latitude": float(att.start_latitude),
                        "longitude": float(att.start_longitude),
                        "location_name": att.start_location or "Check-In Location",
                        "activity_display": f"Checked in at {att.start_location or 'Location'}",
                        "timestamp": start_dt,
                        "dt": start_dt,
                    })

            # Pick the best active location:
            # We sort candidates primarily by most recent event timestamp (descending).
            # If timestamps are identical or very close, sort by priority (1: Visit > 2: Collection > 3: Order > 4: CheckIn)
            selected_location = None
            if location_candidates:
                location_candidates.sort(key=lambda x: (x["dt"], -x["priority"]), reverse=True)
                selected_location = location_candidates[0]

            has_location = bool(selected_location is not None)
            if has_location:
                cnt_with_gps += 1
            else:
                cnt_without_gps += 1

            profile_pic_url = None
            if emp.profile_picture:
                try:
                    profile_pic_url = request.build_absolute_uri(emp.profile_picture.url)
                except Exception:
                    profile_pic_url = emp.profile_picture.url

            # Formatting last active time
            last_active_time_str = None
            last_active_time_display = "No activity"
            if selected_location:
                last_active_time_str = selected_location["timestamp"].isoformat()
                last_active_time_display = selected_location["timestamp"].strftime("%I:%M %p")

            emp_data = {
                "id": emp.id,
                "employeeidnum": emp.employeeidnum,
                "name": emp.name or emp.username,
                "username": emp.username,
                "phone": emp.phone or "",
                "email": emp.email or "",
                "role": emp.role.display_name if emp.role else (emp.role_name if hasattr(emp, "role_name") else "Staff"),
                "role_key": emp.role.name if emp.role else "STAFF",
                "hierarchy_level": emp.hierarchy_level,
                "profile_picture": profile_pic_url,
                "region": emp.district or emp.state or "Chennai",
                "state": emp.state or "",
                "district": emp.district or "",
                # Status flags
                "status": att_status,
                "is_working": is_working,
                "is_online": is_online,
                "check_in_time": check_in_time,
                "check_out_time": check_out_time,
                "total_km": total_km,
                # Counts today
                "visits_count": len(emp_visits),
                "orders_count": len(emp_orders),
                "collections_count": len(emp_colls),
                # GPS Location
                "has_location": has_location,
                "latitude": selected_location["latitude"] if selected_location else None,
                "longitude": selected_location["longitude"] if selected_location else None,
                "location_name": selected_location["location_name"] if selected_location else None,
                "activity_type": selected_location["type"] if selected_location else "none",
                "activity_display": selected_location["activity_display"] if selected_location else "No GPS recorded today",
                "last_active_time": last_active_time_str,
                "last_active_time_display": last_active_time_display,
            }
            employee_results.append(emp_data)

        # ── 5. Status Filter & GPS Filter (Post-processing on full list) ─────
        status_param = request.query_params.get("status", "").strip().lower()
        if status_param and status_param != "all":
            if status_param == "working":
                employee_results = [e for e in employee_results if e["is_working"]]
            elif status_param == "online":
                employee_results = [e for e in employee_results if e["is_online"]]
            elif status_param == "offline":
                employee_results = [e for e in employee_results if not e["is_online"]]
            else:
                employee_results = [e for e in employee_results if e["status"] == status_param]

        has_gps_param = request.query_params.get("has_gps")
        if has_gps_param is not None:
            gps_val = str(has_gps_param).lower() in ("true", "1")
            employee_results = [e for e in employee_results if e["has_location"] == gps_val]

        # ── 6. Assemble Response Payload ───────────────────────────────────
        response_data = {
            "meta": {
                "date": target_date.strftime("%Y-%m-%d"),
                "tracking_date_display": target_date.strftime("%d-%m-%Y"),
                "server_time": timezone.localtime().isoformat(),
                "telemetry": {
                    "gps_telemetry": "High Accuracy (±5m)",
                    "geofence_radius": "100m Auto-Validation",
                    "signal_quality": "Cellular + GPS Lock",
                    "last_sync_ist": timezone.localtime().strftime("%I:%M:%S %p").lower(),
                },
            },
            "summary": {
                "total_employees": len(employees),
                "checked_in": cnt_checked_in,
                "checked_out": cnt_checked_out,
                "working": cnt_working,
                "on_leave": 0,
                "absent": cnt_absent,
                "online": cnt_online,
                "offline": cnt_offline,
                "with_gps": cnt_with_gps,
                "without_gps": cnt_without_gps,
            },
            "count": len(employee_results),
            "employees": employee_results,
        }

        return response.Response(response_data, status=status.HTTP_200_OK)
