import json
from datetime import datetime
from rest_framework import status, response, parsers, viewsets, mixins
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import CursorPagination
from .models import Attendance, Visit, Milage
from .serializers import (
    AttendanceSerializer,
    AttendanceMonthlySerializer,
    AttendanceStartSerializer,
    AttendanceEndSerializer,
    VisitSerializer,
    VisitBulkSyncSerializer,
    MilageSerializer,
    AdminDailyMilageSerializer,
)
from .distance_serializers import get_active_distance_serializer
from users.models import Employee
from users.permissions import IsAdminManagerOrOwner, RoleBasedPermission, is_admin_of
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiParameter


class AttendanceCursorPagination(CursorPagination):
    """Cursor-based pagination for admin attendance list."""
    page_size = 20
    ordering = "employee__employeeidnum"
    cursor_query_param = "cursor"
    page_size_query_param = "page_size"
    max_page_size = 100



class AttendanceViewSet(viewsets.GenericViewSet):
    """Handles employee attendance management."""

    serializer_class = AttendanceSerializer
    parser_classes = [parsers.MultiPartParser, parsers.FormParser, parsers.JSONParser]

    def get_permissions(self):
        if self.action in ("list", "admin_attendance_by_date", "admin_employee_attendance", "partial_update"):
            return [IsAdminManagerOrOwner(), RoleBasedPermission()]
        return [IsAuthenticated(), RoleBasedPermission()]

    def get_serializer_class(self):
        if self.action == "start":
            return AttendanceStartSerializer
        if self.action == "end":
            return AttendanceEndSerializer
        return AttendanceSerializer

    def _build_attendance_dict(self, att, request, id_value=None):
        """Build a standardised attendance response dictionary.

        Args:
            att: An Attendance model instance (with employee select_related).
            request: The current DRF request (used to build absolute URIs).
            id_value: Value for the top-level "id" key.  Defaults to ``att.id``.

        Returns:
            dict: A dictionary ready to be included in a DRF Response.
        """
        if id_value is None:
            id_value = att.id

        # Format total_time timedelta as HH:MM:SS
        total_time_str = None
        if att.total_time is not None:
            total_seconds = int(att.total_time.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            total_time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        # Normalise datetime strings (replace +00:00 suffix with Z)
        created_at_str = att.created_at.isoformat() if att.created_at else None
        if created_at_str and created_at_str.endswith("+00:00"):
            created_at_str = created_at_str[:-6] + "Z"

        updated_at_str = att.updated_at.isoformat() if att.updated_at else None
        if updated_at_str and updated_at_str.endswith("+00:00"):
            updated_at_str = updated_at_str[:-6] + "Z"

        return {
            "id": str(id_value),
            "employee_id": str(att.employee.id),
            "employeeidnum": att.employee.employeeidnum,
            "employee_name": att.employee.name or att.employee.username,
            "date": att.date.strftime("%Y-%m-%d") if att.date else None,
            "start_km": int(att.start_km) if att.start_km is not None else None,
            "start_image": request.build_absolute_uri(att.start_image.url) if att.start_image and att.start_image.name else None,
            "start_location": att.start_location,
            "start_latitude": att.start_latitude,
            "start_longitude": att.start_longitude,
            "start_time": att.start_time.strftime("%H:%M:%S") if att.start_time else None,
            "work_now": att.work_now,
            "status": "Check-out" if att.end_time else "Check-in",
            "end_km": int(att.end_km) if att.end_km is not None else None,
            "end_image": request.build_absolute_uri(att.end_image.url) if att.end_image and att.end_image.name else None,
            "end_location": att.end_location,
            "end_latitude": att.end_latitude,
            "end_longitude": att.end_longitude,
            "end_time": att.end_time.strftime("%H:%M:%S") if att.end_time else None,
            "total_km": int(att.total_km) if att.total_km is not None else None,
            "total_time": total_time_str,
            "daily_sales_target": float(att.daily_sales_target) if att.daily_sales_target is not None else 0.0,
            "daily_collection_target": float(att.daily_collection_target) if att.daily_collection_target is not None else 0.0,
            "daily_visit_target": att.daily_visit_target or 0,
            "today_visit_plan": att.today_visit_plan,
            "created_at": created_at_str,
            "updated_at": updated_at_str,
        }

    def list(self, request):
        """Admin-only: returns today's working employee attendance list."""
        today = timezone.now().date()
        attendances = Attendance.objects.filter(date=today).select_related("employee")

        results = [
            self._build_attendance_dict(att, request, id_value=att.employee.id)
            for att in attendances
        ]

        return response.Response(results, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Admin: attendance details by date (cursor-paginated)",
        description=(
            "Returns all employee attendance categories for a given date. "
            "Pass `date` (YYYY-MM-DD) as a query parameter, request body `[{\"date\": \"YYYY-MM-DD\"}]`, "
            "or omit it to default to today.\n\n"
            "**Response categories:**\n"
            "- `checked_in` — employees currently checked-in (no end_time)\n"
            "- `checked_out` — employees who completed their shift\n"
            "- `absent` — active employees with no attendance record for the date\n\n"
            "Supports cursor pagination via `cursor` and `page_size` query params."
        ),
        parameters=[
            OpenApiParameter(
                name="date",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Date to filter attendance (format: YYYY-MM-DD). Defaults to today.",
            ),
            OpenApiParameter(
                name="cursor",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Cursor for pagination (opaque token returned by the previous page).",
            ),
            OpenApiParameter(
                name="page_size",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Number of results per page (default 20, max 100).",
            ),
        ],
        responses={200: AttendanceSerializer(many=True)},
    )
    def admin_attendance_by_date(self, request):
        """Admin-only: returns all categories of employee attendance for a given date."""

        # --- Resolve date from query param, JSON body, or default to today ---
        date_param = request.query_params.get("date")

        if not date_param:
            # Try body: [{"date": "YYYY-MM-DD"}] or {"date": "YYYY-MM-DD"}
            body_data = None
            try:
                body_data = request.data
            except Exception:
                pass

            if not body_data and request.body:
                try:
                    body_data = json.loads(request.body)
                except Exception:
                    pass

            if isinstance(body_data, list) and len(body_data) > 0 and isinstance(body_data[0], dict):
                date_param = body_data[0].get("date")
            elif isinstance(body_data, dict):
                date_param = body_data.get("date")

        if date_param:
            try:
                target_date = datetime.strptime(str(date_param), "%Y-%m-%d").date()
            except ValueError:
                return response.Response(
                    {"error": "Invalid date format. Expected YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            target_date = timezone.localdate()

        # --- Fetch all attendance records for the target date ---
        attendances_qs = (
            Attendance.objects
            .filter(date=target_date)
            .select_related("employee")
            .order_by("employee__employeeidnum")
        )

        # Split into checked-in / checked-out
        checked_in = [att for att in attendances_qs if att.end_time is None]
        checked_out = [att for att in attendances_qs if att.end_time is not None]

        # --- Absent: active employees with NO attendance record for the date ---
        present_employee_ids = attendances_qs.values_list("employee_id", flat=True)
        absent_employees = (
            Employee.objects
            .filter(is_active=True, is_deleted=False)
            .exclude(id__in=present_employee_ids)
            .order_by("employeeidnum")
        )

        # Build response dictionaries
        def _build(att):
            return self._build_attendance_dict(att, request, id_value=att.employee.id)

        checked_in_data = [_build(att) for att in checked_in]
        checked_out_data = [_build(att) for att in checked_out]
        absent_data = [
            {
                "employee_id": str(emp.id),
                "employeeidnum": emp.employeeidnum,
                "employee_name": emp.name or emp.username,
                "role": emp.role,
                "date": target_date.strftime("%Y-%m-%d"),
                "status": "Absent",
            }
            for emp in absent_employees
        ]

        # --- Cursor-paginate the *full* combined flat list ---
        # Combine: checked_in first, then checked_out, then absent
        all_records = checked_in_data + checked_out_data + absent_data

        # Manual cursor pagination over the combined list (in-memory)
        page_size = int(request.query_params.get("page_size", 20))
        page_size = min(page_size, 100)
        cursor_raw = request.query_params.get("cursor")

        start_index = 0
        if cursor_raw:
            try:
                import base64
                decoded = base64.urlsafe_b64decode(cursor_raw.encode()).decode()
                start_index = int(decoded)
            except Exception:
                return response.Response(
                    {"error": "Invalid cursor."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        end_index = start_index + page_size
        page_records = all_records[start_index:end_index]

        # Build next/previous cursor tokens
        def _make_cursor(index):
            import base64
            return base64.urlsafe_b64encode(str(index).encode()).decode()

        next_cursor = _make_cursor(end_index) if end_index < len(all_records) else None
        previous_cursor = _make_cursor(max(0, start_index - page_size)) if start_index > 0 else None

        # Build absolute URL helpers for next/previous links
        def _build_url(cursor_token):
            if cursor_token is None:
                return None
            base_url = request.build_absolute_uri(request.path)
            params = request.query_params.copy()
            params["cursor"] = cursor_token
            params["page_size"] = str(page_size)
            return base_url + "?" + "&".join(f"{k}={v}" for k, v in params.items())

        return response.Response(
            {
                "date": target_date.strftime("%Y-%m-%d"),
                "summary": {
                    "total_employees": len(all_records),
                    "checked_in_count": len(checked_in_data),
                    "checked_out_count": len(checked_out_data),
                    "absent_count": len(absent_data),
                },
                "pagination": {
                    "count": len(all_records),
                    "page_size": page_size,
                    "next": _build_url(next_cursor),
                    "previous": _build_url(previous_cursor),
                },
                "results": {
                    "checked_in": [r for r in page_records if r.get("status") == "Check-in"],
                    "checked_out": [r for r in page_records if r.get("status") == "Check-out"],
                    "absent": [r for r in page_records if r.get("status") == "Absent"],
                },
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="Admin: all attendance details for one employee by month",
        description=(
            "Returns all attendance records for the specified employee for a given month/year.\n\n"
            "Pass `month` (1-12) and `year` (YYYY) as query params, or in the request body "
            "`[{\"month\": 7, \"year\": 2026}]`. Both default to the **current month/year** if omitted.\n\n"
            "Response includes a summary (total_days, present_days, absent_days, total_km, total_time) "
            "and a day-by-day `records` list ordered by date."
        ),
        parameters=[
            OpenApiParameter(
                name="month",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Month number (1-12). Defaults to current month.",
            ),
            OpenApiParameter(
                name="year",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Four-digit year (e.g. 2026). Defaults to current year.",
            ),
        ],
        responses={200: AttendanceMonthlySerializer(many=True)},
    )
    def admin_employee_attendance(self, request, user_id=None):
        """Admin-only: full monthly attendance details for a specific employee."""

        # --- Resolve employee ---
        try:
            employee = Employee.objects.get(id=user_id)
        except (Employee.DoesNotExist, ValueError):
            return response.Response(
                {"error": "Employee not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # --- Resolve month / year from query params or body ---
        month_param = request.query_params.get("month")
        year_param = request.query_params.get("year")

        if not month_param or not year_param:
            body_data = None
            try:
                body_data = request.data
            except Exception:
                pass
            if not body_data and request.body:
                try:
                    body_data = json.loads(request.body)
                except Exception:
                    pass

            if isinstance(body_data, list) and len(body_data) > 0 and isinstance(body_data[0], dict):
                src = body_data[0]
            elif isinstance(body_data, dict):
                src = body_data
            else:
                src = {}

            month_param = month_param or src.get("month")
            year_param = year_param or src.get("year")

        today = timezone.localdate()
        try:
            month = int(month_param) if month_param is not None else today.month
            if month < 1 or month > 12:
                raise ValueError
        except (TypeError, ValueError):
            return response.Response(
                {"error": "Invalid month. Must be an integer between 1 and 12."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            year = int(year_param) if year_param is not None else today.year
            if year < 2000 or year > 2100:
                raise ValueError
        except (TypeError, ValueError):
            return response.Response(
                {"error": "Invalid year. Must be a four-digit year (e.g. 2026)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --- Fetch attendance records ---
        attendances = (
            Attendance.objects
            .filter(employee=employee, date__year=year, date__month=month)
            .order_by("date", "start_time")
        )

        # --- Build per-record data ---
        records = []
        total_km_sum = 0
        total_seconds_sum = 0

        for att in attendances:
            # Format total_time
            total_time_str = None
            if att.total_time is not None:
                secs = int(att.total_time.total_seconds())
                total_seconds_sum += secs
                h, rem = divmod(secs, 3600)
                m, s = divmod(rem, 60)
                total_time_str = f"{h:02d}:{m:02d}:{s:02d}"

            if att.total_km is not None:
                total_km_sum += att.total_km

            records.append({
                "id": str(att.id),
                "date": att.date.strftime("%Y-%m-%d") if att.date else None,
                "status": "Check-out" if att.end_time else "Check-in",
                "start_time": att.start_time.strftime("%H:%M:%S") if att.start_time else None,
                "end_time": att.end_time.strftime("%H:%M:%S") if att.end_time else None,
                "start_km": int(att.start_km) if att.start_km is not None else None,
                "end_km": int(att.end_km) if att.end_km is not None else None,
                "total_km": int(att.total_km) if att.total_km is not None else None,
                "total_time": total_time_str,
                "start_location": att.start_location,
                "end_location": att.end_location,
                "start_latitude": att.start_latitude,
                "start_longitude": att.start_longitude,
                "end_latitude": att.end_latitude,
                "end_longitude": att.end_longitude,
                "start_image": request.build_absolute_uri(att.start_image.url) if att.start_image and att.start_image.name else None,
                "end_image": request.build_absolute_uri(att.end_image.url) if att.end_image and att.end_image.name else None,
                "auto_checkout": att.auto_checkout,
                "work_now": att.work_now,
            })

        # --- Summary calculations ---
        import calendar
        total_days_in_month = calendar.monthrange(year, month)[1]
        present_days = attendances.values("date").distinct().count()
        absent_days = total_days_in_month - present_days

        # Format aggregated total_time
        agg_h, agg_rem = divmod(total_seconds_sum, 3600)
        agg_m, agg_s = divmod(agg_rem, 60)
        agg_total_time = f"{agg_h:02d}:{agg_m:02d}:{agg_s:02d}"

        return response.Response(
            {
                "employee_id": str(employee.id),
                "employeeidnum": employee.employeeidnum,
                "employee_name": employee.name or employee.username,
                "role": employee.role,
                "month": month,
                "year": year,
                "summary": {
                    "total_days_in_month": total_days_in_month,
                    "present_days": present_days,
                    "absent_days": absent_days,
                    "total_attendance_entries": len(records),
                    "total_km": int(total_km_sum),
                    "total_time": agg_total_time,
                },
                "records": records,
            },
            status=status.HTTP_200_OK,
        )

    def retrieve(self, request, pk=None):
        """Returns 1 full attendance details for that employee and admin."""
        try:
            att = Attendance.objects.select_related("employee").get(id=pk)
        except Attendance.DoesNotExist:
            return response.Response(
                {"error": "Attendance not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        user = request.user
        # Hierarchy-safe admin check: any role with level <= ADMIN_MAX_LEVEL
        # can view other employees' attendance records.
        if not is_admin_of(user) and att.employee_id != user.id:
            return response.Response(
                {"detail": "You do not have permission to access this attendance details."},
                status=status.HTTP_403_FORBIDDEN
            )

        entry = self._build_attendance_dict(att, request)
        return response.Response(entry, status=status.HTTP_200_OK)

    def partial_update(self, request, pk=None):
        """Allows updating attendance details (like check-in/out KM, times, or status)."""
        try:
            att = Attendance.objects.get(id=pk)
        except Attendance.DoesNotExist:
            return response.Response(
                {"error": "Attendance record not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = self.get_serializer(att, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        entry = self._build_attendance_dict(att, request)
        return response.Response(entry, status=status.HTTP_200_OK)




    @action(detail=False, methods=["post"], url_path="start", url_name="start")
    def start(self, request):
        """Handles employee attendance check-in."""

        # POST request — block if user already has an active (unclosed) check-in today
        active = Attendance.objects.filter(
            employee=request.user, date=timezone.now().date(), end_time__isnull=True
        ).exists()
        if active:
            return response.Response(
                {"detail": "You are already checked in. Please check-out first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Get values from request if provided, otherwise default to current date/time
        date_val = serializer.validated_data.get("date") or timezone.now().date()
        time_val = serializer.validated_data.get("start_time") or timezone.now().time()
        
        serializer.save(
            employee=request.user,
            date=date_val,
            start_time=time_val,
        )
        return response.Response(
            {"detail": "Check-In Successful"}, status=status.HTTP_201_CREATED
        )

    @action(detail=False, methods=["post"], url_path="end", url_name="end")
    def end(self, request):
        """Handles employee attendance check-out."""

        # POST request
        date_str = request.data.get("date")
        if date_str:
            try:
                from datetime import datetime
                date_val = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                return response.Response(
                    {"error": "Invalid date format. Expected YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            date_val = timezone.now().date()

        try:
            attendance = Attendance.objects.filter(
                employee=request.user, date=date_val, end_time__isnull=True
            ).latest("start_time")
        except Attendance.DoesNotExist:
            return response.Response(
                {"error": f"No active attendance found for date {date_val}."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = self.get_serializer(attendance, data=request.data)
        serializer.is_valid(raise_exception=True)

        end_km = serializer.validated_data["end_km"]
        time_val = serializer.validated_data.get("end_time") or timezone.now().time()

        # Calculate working time duration
        start_dt = timezone.datetime.combine(attendance.date, attendance.start_time)
        end_dt = timezone.datetime.combine(date_val, time_val)
        
        if timezone.is_aware(timezone.now()):
            start_dt = timezone.make_aware(start_dt)
            end_dt = timezone.make_aware(end_dt)

        duration = end_dt - start_dt
        total_seconds = max(0, int(duration.total_seconds()))

        # "if more then 30s consider as a 1 minute"
        minutes, seconds = divmod(total_seconds, 60)
        if seconds > 30:
            minutes += 1
        hours, minutes = divmod(minutes, 60)
        total_time_str = f"{hours:02d}:{minutes:02d}"

        # Total km calculation
        total_km = int(end_km - attendance.start_km)

        # Save to DB
        attendance = serializer.save(
            end_time=time_val,
            total_km=float(total_km),
            total_time=duration,
            work_now=False,
        )

        # ------------------------------------------------------------------
        # Return-to-home distance: last visited place → checkout location
        # ------------------------------------------------------------------
        end_lat = serializer.validated_data.get("end_latitude")
        end_lon = serializer.validated_data.get("end_longitude")

        return_km = 0.0
        if end_lat and end_lon:
            # Find the last visit for this attendance to use as origin
            last_visit = (
                Visit.objects
                .filter(attendance_id=attendance)
                .order_by("-created_at")
                .first()
            )
            if last_visit and last_visit.latitude and last_visit.longitude:
                ds = get_active_distance_serializer()
                return_km = ds.get_distance(
                    float(last_visit.latitude),
                    float(last_visit.longitude),
                    float(end_lat),
                    float(end_lon),
                )
            elif attendance.start_latitude and attendance.start_longitude:
                # No visits yet — measure from check-in location
                ds = get_active_distance_serializer()
                return_km = ds.get_distance(
                    float(attendance.start_latitude),
                    float(attendance.start_longitude),
                    float(end_lat),
                    float(end_lon),
                )

        # Update Milage record with return_to_home + add to cumulative total
        milage_record, _ = Milage.objects.get_or_create(
            employee=request.user,
            date=date_val,
            defaults={
                "attendance_id": attendance,
                "total_distance_travelled": 0.0,
                "return_to_home": 0.0,
            },
        )
        milage_record.return_to_home = return_km
        milage_record.total_distance_travelled = round(
            (milage_record.total_distance_travelled or 0.0) + return_km, 3
        )
        milage_record.save(update_fields=["return_to_home", "total_distance_travelled", "updated_at"])

        return response.Response(
            {
                "total_km": total_km,
                "total_time": total_time_str,
                "detail": "Check-out Successful"
            },
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=["get"], url_path="status", url_name="status")
    def attendance_status(self, request):
        """Returns today's attendance status for the authenticated employee."""
        today = timezone.localdate()
        today_str = today.strftime("%Y-%m-%d")

        try:
            attendance = Attendance.objects.filter(
                employee=request.user, date=today
            ).latest("start_time")
        except Attendance.DoesNotExist:
            # Return last check-out details. Also, indicate not check-in today like this "today(DD:MM:YYYY) not check-in yet".
            last_checkout = Attendance.objects.filter(
                employee=request.user, work_now=False
            ).order_by("-date", "-end_time").first()

            res_data = {
                "date": today_str,
                "status": "Not check-in yet",
                "last_attendance": {
                    "date": last_checkout.date.strftime("%Y-%m-%d") if last_checkout.date else None,
                    "start_time": last_checkout.start_time.strftime("%H:%M:%S") if last_checkout.start_time else None,
                    "end_time": last_checkout.end_time.strftime("%H:%M:%S") if last_checkout.end_time else None,
                    "auto_checkout": last_checkout.auto_checkout,
                }
            }
            return response.Response(res_data, status=status.HTTP_200_OK)

        if attendance.end_time is None:
            # Checked in but not checked out
            return response.Response(
                {
                    "date": today_str,
                    "status": "Check-in",
                    "start_time": attendance.start_time.strftime("%H:%M:%S") if attendance.start_time else None
                },
                status=status.HTTP_200_OK,
            )

        return response.Response(
            {
                "date": today_str,
                "status": "Check-out",
                "start_time": attendance.start_time.strftime("%H:%M:%S") if attendance.start_time else None,
                "end_time": attendance.end_time.strftime("%H:%M:%S"),
                "total_time": str(attendance.total_time),
                "auto_checkout": attendance.auto_checkout,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="Employee attendance history",
        description="Returns the authenticated employee's attendance details filtered by month. Pass `month` as a query parameter (e.g. `?month=7`) or as a JSON body `[{\"month\": 7}]`.",
        parameters=[
            OpenApiParameter(
                name="month",
                type=int,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Month in number (integer, e.g. 7)"
            )
        ],
        responses={200: AttendanceMonthlySerializer(many=True)},
    )
    def employee_monthly_attendance(self, request):
        """Returns the authenticated employee's attendance details filtered by month."""
        # Try to get month from query parameters
        month_val = request.query_params.get("month")

        # If not in query parameters, try to get from request body (e.g. [{"month": 7}] or {"month": 7})
        if not month_val:
            data = None
            try:
                data = request.data
            except Exception:
                pass
            
            # Fallback manual parsing if request.data is empty/failed
            if not data and request.body:
                try:
                    import json
                    data = json.loads(request.body)
                except Exception:
                    pass

            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                month_val = data[0].get("month")
            elif isinstance(data, dict):
                month_val = data.get("month")

        if not month_val:
            return response.Response(
                {"error": "Month parameter is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            month = int(month_val)
            if month < 1 or month > 12:
                raise ValueError
        except (TypeError, ValueError):
            return response.Response(
                {"error": "Invalid month. Must be an integer between 1 and 12."},
                status=status.HTTP_400_BAD_REQUEST
            )

        attendances = Attendance.objects.filter(
            employee=request.user,
            date__month=month
        ).order_by("-date")

        serializer = AttendanceMonthlySerializer(attendances, many=True)
        return response.Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Employee KM traveled report (7-day blocks, lazy loaded)",
        description=(
            "Returns a report of total KM traveled by the employee for a 7-day period. "
            "Supports pagination (lazy loading) via the `page` query parameter (default is 1). "
            "Page 1 returns the last 7 days, Page 2 returns the 7 days before that, etc."
        ),
        parameters=[
            OpenApiParameter(
                name="page",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Page number for the 7-day block (default 1).",
            ),
            OpenApiParameter(
                name="employee_id",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Employee UUID (Admin-only). Defaults to authenticated user.",
            ),
        ],
    )
    @action(detail=False, methods=["get"], url_path="km-report", url_name="km-report")
    def km_report(self, request):
        """Returns the KM traveled report for the last 7 days (paginated/lazy loaded)."""
        target_employee = request.user
        employee_id_param = request.query_params.get("employee_id")
        
        if employee_id_param:
            # Allow user to view their own report, or check if user has admin privileges
            if str(request.user.id) != str(employee_id_param):
                if not is_admin_of(request.user):
                    return response.Response(
                        {"detail": "You do not have permission to view other employee's KM report."},
                        status=status.HTTP_403_FORBIDDEN
                    )
            try:
                target_employee = Employee.objects.get(id=employee_id_param)
            except (Employee.DoesNotExist, ValueError):
                return response.Response(
                    {"error": "Employee not found."},
                    status=status.HTTP_404_NOT_FOUND
                )

        try:
            page = int(request.query_params.get("page", 1))
            if page < 1:
                raise ValueError
        except ValueError:
            return response.Response(
                {"error": "Invalid page. Must be a positive integer starting from 1."},
                status=status.HTTP_400_BAD_REQUEST
            )

        from datetime import timedelta
        # Reference date is local today
        today = timezone.localdate()
        
        # Calculate the 7-day window
        # page=1: today - 6 to today (i.e. shift = 0)
        # page=2: today - 13 to today - 7 (i.e. shift = 7)
        shift = (page - 1) * 7
        end_date = today - timedelta(days=shift)
        start_date = end_date - timedelta(days=6)

        attendances = Attendance.objects.filter(
            employee=target_employee,
            date__range=[start_date, end_date]
        )

        km_by_date = {}
        for att in attendances:
            d_str = att.date.strftime("%Y-%m-%d")
            km_val = att.total_km if att.total_km is not None else 0.0
            km_by_date[d_str] = km_by_date.get(d_str, 0.0) + km_val

        dates_list = []
        kms_list = []

        current_date = start_date
        while current_date <= end_date:
            d_str = current_date.strftime("%Y-%m-%d")
            dates_list.append(d_str)
            kms_list.append(round(km_by_date.get(d_str, 0.0), 2))
            current_date += timedelta(days=1)

        return response.Response(
            [
                {
                    "date": dates_list,
                    "km": kms_list
                }
            ],
            status=status.HTTP_200_OK
        )


class VisitViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Handles for each visit bulk sync and listing."""

    serializer_class = VisitSerializer
    parser_classes = [parsers.MultiPartParser, parsers.FormParser, parsers.JSONParser]
    lookup_url_kwarg = 'employee_id'

    def get_permissions(self):
        return [IsAuthenticated(), RoleBasedPermission()]

    @staticmethod
    def _is_null_param(val):
        """Return True when a param value is absent, empty, or string 'null'/'none'."""
        if val is None:
            return True
        if isinstance(val, str) and (val.strip() == "" or val.strip().lower() in ("null", "none")):
            return True
        return False

    @staticmethod
    def _parse_date_value(val, param_name="date"):
        """
        Parse DD:MM:YYYY, YYYY-MM-DD, DD-MM-YYYY, or DD/MM/YYYY to a date object.
        Returns None if value is null/empty.
        Raises rest_framework.exceptions.ValidationError (400 BAD REQUEST) if format is invalid.
        """
        if VisitViewSet._is_null_param(val):
            return None

        val_str = str(val).strip()
        formats = ["%d:%m:%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"]
        for fmt in formats:
            try:
                return datetime.strptime(val_str, fmt).date()
            except ValueError:
                continue

        from rest_framework.exceptions import ValidationError
        raise ValidationError(
            {param_name: f"Invalid date format '{val}'. Expected format DD:MM:YYYY or YYYY-MM-DD."}
        )

    def _extract_date_range_params(self, request):
        """
        Extract from_date, to_date, and date from query parameters or request body.
        Supports:
        - Query params: ?from_date=...&to_date=...&date=...
        - Request body JSON list: [{"from_date": ..., "to_date": ..., "date": ...}]
        - Request body JSON dict: {"from_date": ..., "to_date": ..., "date": ...}
        """
        from_date_raw = request.query_params.get("from_date")
        to_date_raw = request.query_params.get("to_date")
        date_raw = request.query_params.get("date")

        if self._is_null_param(from_date_raw) and self._is_null_param(to_date_raw) and self._is_null_param(date_raw):
            body_data = None
            try:
                body_data = request.data
            except Exception:
                pass

            if not body_data and getattr(request, "body", None):
                try:
                    body_data = json.loads(request.body)
                except Exception:
                    pass

            if isinstance(body_data, list) and len(body_data) > 0 and isinstance(body_data[0], dict):
                from_date_raw = body_data[0].get("from_date")
                to_date_raw = body_data[0].get("to_date")
                date_raw = body_data[0].get("date")
            elif isinstance(body_data, dict):
                from_date_raw = body_data.get("from_date")
                to_date_raw = body_data.get("to_date")
                date_raw = body_data.get("date")

        return from_date_raw, to_date_raw, date_raw

    def get_queryset(self):
        """Filter visits by authenticated employee for a specific date or date range."""
        queryset = Visit.objects.filter(employee=self.request.user).order_by("-created_at")

        from_date_raw, to_date_raw, date_raw = self._extract_date_range_params(self.request)

        from_date_obj = self._parse_date_value(from_date_raw, "from_date")
        to_date_obj = self._parse_date_value(to_date_raw, "to_date")

        if from_date_obj or to_date_obj:
            if from_date_obj:
                queryset = queryset.filter(created_at__date__gte=from_date_obj)
            if to_date_obj:
                queryset = queryset.filter(created_at__date__lte=to_date_obj)
        elif not self._is_null_param(date_raw):
            date_obj = self._parse_date_value(date_raw, "date")
            if date_obj:
                queryset = queryset.filter(created_at__date=date_obj)

        return queryset

    @extend_schema(
        summary="List authenticated employee's visits by date",
        description="Returns the authenticated employee's visit list for the given date. `date` (YYYY-MM-DD) is required.",
        parameters=[
            OpenApiParameter(
                name="date",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Date to filter visits (format: YYYY-MM-DD)",
            )
        ],
        responses={200: VisitSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        """Returns the authenticated employee's visit list for the given date."""
        from_date_raw, to_date_raw, date_param = self._extract_date_range_params(request)

        if self._is_null_param(from_date_raw) and self._is_null_param(to_date_raw) and self._is_null_param(date_param):
            return response.Response(
                {"error": "date is required. Provide it as a query parameter (e.g. ?date=2026-07-25)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return response.Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="List visits of a specific employee",
        description="Returns a list of visits of the specified employee for the specified date (Admin-only).",
        responses={200: VisitSerializer(many=True)},
    )
    def retrieve(self, request, employee_id=None):
        """Retrieve employee visits (Admin-only)."""
        if not is_admin_of(request.user):
            return response.Response(
                {"detail": "You do not have permission to view other employee's visits."},
                status=status.HTTP_403_FORBIDDEN
            )
            
        queryset = Visit.objects.filter(employee_id=employee_id).order_by("-created_at")

        from_date_raw, to_date_raw, date_param = self._extract_date_range_params(request)
        
        from_date_obj = self._parse_date_value(from_date_raw, "from_date")
        to_date_obj = self._parse_date_value(to_date_raw, "to_date")

        if from_date_obj or to_date_obj:
            if from_date_obj:
                queryset = queryset.filter(created_at__date__gte=from_date_obj)
            if to_date_obj:
                queryset = queryset.filter(created_at__date__lte=to_date_obj)
        elif not self._is_null_param(date_param):
            date_obj = self._parse_date_value(date_param, "date")
            if date_obj:
                queryset = queryset.filter(created_at__date=date_obj)
        else:
            from django.utils import timezone
            queryset = queryset.filter(created_at__date=timezone.now().date())
        
        serializer = self.get_serializer(queryset, many=True)
        return response.Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="List visits to a specific dealer",
        description=(
            "Returns a list of visits to the specified dealer for all employees, "
            "provided the authenticated employee is connected to this dealer.\n\n"
            "Supports date range filtering (`from_date` and `to_date`) in `DD:MM:YYYY` format "
            "(or `YYYY-MM-DD`). Inputs can be passed via query parameters or JSON body `[{\"from_date\": \"DD:MM:YYYY\", \"to_date\": \"DD:MM:YYYY\"}]`."
        ),
        parameters=[
            OpenApiParameter(
                name="from_date",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Start date for range filter (format: DD:MM:YYYY or YYYY-MM-DD)",
            ),
            OpenApiParameter(
                name="to_date",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="End date for range filter (format: DD:MM:YYYY or YYYY-MM-DD)",
            ),
            OpenApiParameter(
                name="date",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Single date filter (format: YYYY-MM-DD or DD:MM:YYYY)",
            ),
        ],
        responses={200: VisitSerializer(many=True)},
    )
    def retrieve_dealer(self, request, dealers_id=None):
        """
        Get visit data for a specific dealer.
        Available to all employees connected to the dealer.
        Supports date range filtering via from_date & to_date parameters (DD:MM:YYYY or YYYY-MM-DD).
        """
        from dealers.models import SubDealer
        from django.db.models import Q
        
        # Check if the lookup ID matches a SubDealer
        try:
            dealer_exists = SubDealer.objects.filter(id=dealers_id).exists()
        except (ValueError, TypeError):
            dealer_exists = False

        if dealer_exists:
            # Check connection: employee must be connected to this dealer
            has_connection = SubDealer.objects.filter(id=dealers_id, employee=request.user).exists()

            if not has_connection and not is_admin_of(request.user):
                return response.Response(
                    {"detail": "You do not have a connection with this dealer."},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # List only the visit data for that dealer
            queryset = Visit.objects.filter(Q(dealer_id=dealers_id) | Q(client_id=dealers_id)).order_by("-created_at")
            
            # Date range / date filtering
            from_date_raw, to_date_raw, date_raw = self._extract_date_range_params(request)

            from_date_obj = self._parse_date_value(from_date_raw, "from_date")
            to_date_obj = self._parse_date_value(to_date_raw, "to_date")

            if from_date_obj or to_date_obj:
                if from_date_obj:
                    queryset = queryset.filter(created_at__date__gte=from_date_obj)
                if to_date_obj:
                    queryset = queryset.filter(created_at__date__lte=to_date_obj)
            elif not self._is_null_param(date_raw):
                date_obj = self._parse_date_value(date_raw, "date")
                if date_obj:
                    queryset = queryset.filter(created_at__date=date_obj)
                
            serializer = self.get_serializer(queryset, many=True)
            return response.Response(serializer.data, status=status.HTTP_200_OK)

        else:
            # Fallback to standard retrieve action for employee's visits
            return self.retrieve(request, employee_id=dealers_id)

    @action(detail=False, methods=["post"], url_path="create", url_name="create")
    def create_visit(self, request):
        """Handles visit creation with automatic sequential distance calculation.

        For each new visit:
          1. Save the visit record.
          2. Determine the previous location:
             - If previous visits exist for this attendance → use the most
               recent visit's lat/lng.
             - Otherwise → use the check-in (Attendance.start_latitude/longitude).
          3. Calculate distance (prev → current) via the active distance provider.
          4. Save to Visit.travelled_km.
          5. Upsert Milage table with the new cumulative total (real-time).
        """
        data = request.data
        import re

        # Determine if input is a list or QueryDict list-like format
        is_list = False
        if isinstance(data, list):
            is_list = True
        elif hasattr(data, "keys"):
            for key in data.keys():
                if re.match(r"^\[\d+\]", str(key)) or re.match(r"^\d+\.", str(key)):
                    is_list = True
                    break

        if is_list:
            if isinstance(data, list):
                items = data
            else:
                # QueryDict representation of lists, e.g., [0]type, [0]image, [1]type, etc.
                list_indices = set()
                for key in data.keys():
                    match = re.match(r"^\[(\d+)\]", str(key))
                    if match:
                        list_indices.add(int(match.group(1)))
                    else:
                        match_dot = re.match(r"^(\d+)\.", str(key))
                        if match_dot:
                            list_indices.add(int(match_dot.group(1)))

                items = []
                for index in sorted(list_indices):
                    item = {}
                    prefix1 = f"[{index}]"
                    prefix2 = f"{index}."
                    for key in data.keys():
                        key_str = str(key)
                        if key_str.startswith(prefix1):
                            item_key = key_str[len(prefix1):]
                            if hasattr(data, "getlist"):
                                vals = data.getlist(key)
                                item[item_key] = vals[0] if len(vals) == 1 else vals
                            else:
                                item[item_key] = data[key]
                        elif key_str.startswith(prefix2):
                            item_key = key_str[len(prefix2):]
                            if hasattr(data, "getlist"):
                                vals = data.getlist(key)
                                item[item_key] = vals[0] if len(vals) == 1 else vals
                            else:
                                item[item_key] = data[key]
                    items.append(item)
        else:
            # Single dictionary (or dict-like object)
            items = [data]

        # Use serializer with many=True since we are processing a list of items
        serializer = self.get_serializer(data=items, many=True)
        serializer.is_valid(raise_exception=True)
        saved_visits = serializer.save(employee=request.user)

        # ------------------------------------------------------------------
        # Distance calculation + Milage real-time update for each saved visit
        # ------------------------------------------------------------------
        ds = get_active_distance_serializer()

        if not isinstance(saved_visits, list):
            saved_visits = [saved_visits]

        for visit in saved_visits:
            if not visit.latitude or not visit.longitude:
                continue

            attendance = visit.attendance_id  # FK object
            if attendance is None:
                continue

            # Find previous location: last visit for this attendance (excluding
            # the visit we just saved) or fall back to check-in coordinates.
            prev_visit = (
                Visit.objects
                .filter(attendance_id=attendance)
                .exclude(pk=visit.pk)
                .order_by("-created_at")
                .first()
            )

            if prev_visit and prev_visit.latitude and prev_visit.longitude:
                prev_lat = float(prev_visit.latitude)
                prev_lon = float(prev_visit.longitude)
            elif attendance.start_latitude and attendance.start_longitude:
                prev_lat = float(attendance.start_latitude)
                prev_lon = float(attendance.start_longitude)
            else:
                # Cannot determine origin — skip distance calc for this visit
                continue

            segment_km = ds.get_distance(
                prev_lat, prev_lon,
                float(visit.latitude), float(visit.longitude),
            )

            # Save segment distance back to the visit record
            visit.travelled_km = segment_km
            visit.save(update_fields=["travelled_km"])

            # Real-time upsert of the daily Milage record
            today = attendance.date
            milage_record, _ = Milage.objects.get_or_create(
                employee=request.user,
                date=today,
                defaults={
                    "attendance_id": attendance,
                    "total_distance_travelled": 0.0,
                    "return_to_home": 0.0,
                },
            )
            milage_record.total_distance_travelled = round(
                (milage_record.total_distance_travelled or 0.0) + segment_km, 3
            )
            milage_record.save(update_fields=["total_distance_travelled", "updated_at"])

        # Re-serialize to include the newly computed travelled_km in the response
        result_serializer = self.get_serializer(saved_visits, many=True)
        return response.Response(result_serializer.data, status=status.HTTP_201_CREATED)

    @action(
        detail=False,
        methods=["post"],
        url_path="bulk-sync",
        url_name="bulk-sync",
        parser_classes=[parsers.JSONParser],
    )
    def bulk_sync(self, request):
        """Handles bulk sync of visits with distance calculation.

        Each synced visit has its segment distance calculated and the daily
        Milage record updated, identical to the real-time create_visit flow.
        """
        visits_data = request.data
        if not isinstance(visits_data, list):
            return response.Response(
                {"error": "Expected a list of visits."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ds = get_active_distance_serializer()
        results = []

        for visit_data in visits_data:
            visit_data["employee"] = request.user.id

            visit_uuid = visit_data.get("id")

            if visit_uuid and Visit.objects.filter(id=visit_uuid).exists():
                visit = Visit.objects.get(id=visit_uuid)
                serializer = VisitBulkSyncSerializer(
                    visit, data=visit_data, partial=True
                )
                if serializer.is_valid():
                    visit = serializer.save(employee=request.user)
                    # Recalculate distance if coordinates changed
                    _update_visit_distance_and_milage(visit, ds, request.user)
                    results.append(
                        {
                            "local_id": visit_uuid,
                            "server_id": str(visit.id),
                            "travelled_km": visit.travelled_km,
                            "status": "updated",
                        }
                    )
                else:
                    results.append(
                        {
                            "local_id": visit_uuid,
                            "errors": serializer.errors,
                            "status": "failed",
                        }
                    )
                continue

            serializer = VisitBulkSyncSerializer(data=visit_data)
            if serializer.is_valid():
                visit = serializer.save(employee=request.user)
                _update_visit_distance_and_milage(visit, ds, request.user)
                results.append(
                    {
                        "local_id": visit_uuid,
                        "server_id": str(visit.id),
                        "travelled_km": visit.travelled_km,
                        "status": "synced",
                    }
                )
            else:
                results.append(
                    {
                        "local_id": visit_uuid,
                        "errors": serializer.errors,
                        "status": "failed",
                    }
                )

        return response.Response(results, status=status.HTTP_200_OK)

    def retrieve_visit_detail(self, request, pk=None):
        """Retrieve a specific visit record by its primary key ID."""
        try:
            visit = Visit.objects.get(id=pk)
        except Visit.DoesNotExist:
            return response.Response(
                {"error": "Visit record not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = self.get_serializer(visit)
        return response.Response(serializer.data, status=status.HTTP_200_OK)

    def partial_update_visit(self, request, pk=None):
        """Update a specific visit record by its primary key ID."""
        try:
            visit = Visit.objects.get(id=pk)
        except Visit.DoesNotExist:
            return response.Response(
                {"error": "Visit record not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = self.get_serializer(visit, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return response.Response(serializer.data, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Helper — shared distance + Milage logic used by both create_visit & bulk_sync
# ---------------------------------------------------------------------------

def _update_visit_distance_and_milage(visit, ds, employee):
    """
    Calculate the road-travel distance for a single Visit and update the
    real-time daily Milage record.

    Args:
        visit   : Saved Visit model instance (with attendance_id populated).
        ds      : Active distance serializer instance.
        employee: The Employee/User who owns this visit.
    """
    if not visit.latitude or not visit.longitude:
        return

    attendance = visit.attendance_id
    if attendance is None:
        return

    # Previous location: last other visit for this attendance, or check-in
    prev_visit = (
        Visit.objects
        .filter(attendance_id=attendance)
        .exclude(pk=visit.pk)
        .order_by("-created_at")
        .first()
    )

    if prev_visit and prev_visit.latitude and prev_visit.longitude:
        prev_lat = float(prev_visit.latitude)
        prev_lon = float(prev_visit.longitude)
    elif attendance.start_latitude and attendance.start_longitude:
        prev_lat = float(attendance.start_latitude)
        prev_lon = float(attendance.start_longitude)
    else:
        return

    segment_km = ds.get_distance(
        prev_lat, prev_lon,
        float(visit.latitude), float(visit.longitude),
    )

    visit.travelled_km = segment_km
    visit.save(update_fields=["travelled_km"])

    # Upsert Milage — one record per employee per day
    today = attendance.date
    milage_record, _ = Milage.objects.get_or_create(
        employee=employee,
        date=today,
        defaults={
            "attendance_id": attendance,
            "total_distance_travelled": 0.0,
            "return_to_home": 0.0,
        },
    )
    milage_record.total_distance_travelled = round(
        (milage_record.total_distance_travelled or 0.0) + segment_km, 3
    )
    milage_record.save(update_fields=["total_distance_travelled", "updated_at"])


# ---------------------------------------------------------------------------
# Milage ViewSet
# ---------------------------------------------------------------------------

class MilageViewSet(viewsets.GenericViewSet):
    """Read-only endpoints for the daily cumulative mileage summary."""

    serializer_class = MilageSerializer
    parser_classes = [parsers.JSONParser]

    def get_permissions(self):
        return [IsAuthenticated(), RoleBasedPermission()]

    @extend_schema(
        summary="Employee daily mileage summary",
        description=(
            "Returns the authenticated employee's cumulative mileage for a specific date. "
            "Pass `date` (YYYY-MM-DD) as a query parameter, or omit for today.\n\n"
            "Admins/Owners/Managers can additionally pass `employee_id` to view "
            "any employee's mileage data."
        ),
        parameters=[
            OpenApiParameter(
                name="date",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Date to query (format: YYYY-MM-DD). Defaults to today.",
            ),
            OpenApiParameter(
                name="employee_id",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Employee UUID (Admin/Owner/Manager only).",
            ),
        ],
        responses={200: MilageSerializer()},
    )
    @action(detail=False, methods=["get"], url_path="summary", url_name="summary")
    def milage_summary(self, request):
        """Returns the daily cumulative mileage summary for an employee."""

        # --- Resolve target employee ---
        employee_id_param = request.query_params.get("employee_id")
        target_employee = request.user

        if employee_id_param and str(request.user.id) != str(employee_id_param):
            # Check milage_manage permission via the EmployeeRole table
            user = request.user
            if user.is_owner:
                has_milage_manage = True
            else:
                has_milage_manage = bool(user.role and user.role.milage_manage)

            if not has_milage_manage:
                return response.Response(
                    {"detail": "You do not have permission to view other employees' mileage data."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            try:
                target_employee = Employee.objects.get(id=employee_id_param)
            except (Employee.DoesNotExist, ValueError):
                return response.Response(
                    {"error": "Employee not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        # --- Resolve date ---
        date_param = request.query_params.get("date")
        if date_param:
            try:
                target_date = datetime.strptime(str(date_param), "%Y-%m-%d").date()
            except ValueError:
                return response.Response(
                    {"error": "Invalid date format. Expected YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            target_date = timezone.localdate()

        try:
            milage = Milage.objects.select_related("employee", "attendance_id").get(
                employee=target_employee,
                date=target_date,
            )
        except Milage.DoesNotExist:
            return response.Response(
                {
                    "date": target_date.strftime("%Y-%m-%d"),
                    "detail": "No mileage record found for this date.",
                    "total_distance_travelled": 0.0,
                    "return_to_home": 0.0,
                },
                status=status.HTTP_200_OK,
            )

        serializer = self.get_serializer(milage)
        return response.Response(serializer.data, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Admin — daily mileage report for ALL employees
# ---------------------------------------------------------------------------

class AdminDailyMilageView(viewsets.GenericViewSet):
    """
    GET /api/admin/tracking/milage/<date>/

    Returns a list of every employee who has a mileage record for the given
    calendar day, including the odometer-based total_km from their Attendance
    record when available.

    Access: OWNER (always) or any role with milage_manage=True in EmployeeRole.
    """

    serializer_class = AdminDailyMilageSerializer

    def get_permissions(self):
        return [IsAuthenticated()]

    @staticmethod
    def _check_milage_manage(user):
        """Return True if user is Owner/superuser or has milage_manage=True."""
        if user.is_owner:
            return True
        return bool(user.role and user.role.milage_manage)

    @extend_schema(
        summary="Admin: all-employee daily mileage report",
        description=(
            "Returns the mileage summary for **every employee** who has a "
            "Mileage record on the specified date.\n\n"
            "Each entry includes:\n"
            "- GPS-route cumulative distance (`total_distance_travelled`)\n"
            "- Return-to-home leg (`return_to_home`)\n"
            "- Odometer total from the Attendance record (`attendance_total_km`) "
            "  — `null` if the employee hasn't checked out yet\n"
            "- `checked_out` boolean\n\n"
            "**Access:** OWNER only, or roles with *Milage Manage* enabled "
            "in the access control table."
        ),
        responses={200: AdminDailyMilageSerializer(many=True)},
    )
    def daily_milage(self, request, date=None):
        """GET /api/admin/tracking/milage/<YYYY-MM-DD>/"""

        # ---------- Permission check ----------
        if not self._check_milage_manage(request.user):
            return response.Response(
                {"detail": "You do not have permission to view mileage data for all employees."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ---------- Date validation ----------
        try:
            target_date = datetime.strptime(str(date).strip(), "%Y-%m-%d").date()
        except (ValueError, AttributeError):
            return response.Response(
                {"error": f"Invalid date format '{date}'. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ---------- Query ----------
        # Fetch all mileage records for that day, pre-loading employee and
        # linked attendance in a single query (no N+1).
        milage_qs = (
            Milage.objects
            .filter(date=target_date)
            .select_related("employee", "attendance_id")
            .order_by("employee__employeeidnum")
        )

        # ---------- Response ----------
        serializer = AdminDailyMilageSerializer(milage_qs, many=True)
        return response.Response(
            {
                "date": target_date.strftime("%Y-%m-%d"),
                "count": milage_qs.count(),
                "results": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Admin — per-employee weekly mileage scroll (cursor-based, 7-day pages)
# ---------------------------------------------------------------------------

class AdminEmployeeMilageSummaryView(viewsets.GenericViewSet):
    """
    GET /api/admin/tracking/milage/summary/<user_id>/

    Returns mileage records for ONE employee going backwards in time,
    one week (7 calendar days) per page — optimised for infinite scroll.

    Cursor design
    ─────────────
    • First request (no cursor): returns the 7 most recent days that have
      a mileage record, newest first.
    • The response includes `next_cursor` — the date of the oldest record
      in this batch (ISO string YYYY-MM-DD).
    • Next scroll: pass ?before=<next_cursor>.  The API returns the next
      7 days strictly BEFORE that date.
    • When `has_more` is False the client has reached the beginning of the
      employee's history.

    Access: OWNER (always) or any role with milage_manage=True in EmployeeRole.
    """

    PAGE_SIZE = 7  # days per scroll page

    serializer_class = AdminDailyMilageSerializer

    def get_permissions(self):
        return [IsAuthenticated()]

    # ── Shared permission helper (identical to AdminDailyMilageView) ──────

    @staticmethod
    def _check_milage_manage(user):
        if user.is_owner:
            return True
        return bool(user.role and user.role.milage_manage)

    # ── View ──────────────────────────────────────────────────────────────

    @extend_schema(
        summary="Admin: employee mileage history (weekly scroll)",
        description=(
            "Returns up to 7 days of mileage records for a single employee, "
            "going backwards in time. Designed for **infinite scroll**.\n\n"
            "**Cursor usage:**\n"
            "- First call: omit `before` — returns the 7 most recent days.\n"
            "- Next scroll: pass `?before=<next_cursor>` from the previous response.\n"
            "- Stop scrolling when `has_more` is `false`.\n\n"
            "Each result row is identical to the daily mileage report "
            "(GPS distance, return-to-home, odometer total, checked-out flag).\n\n"
            "**Access:** OWNER only, or roles with *Milage Manage* enabled "
            "in the access control table."
        ),
        parameters=[
            OpenApiParameter(
                name="before",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Cursor: fetch 7 days strictly before this date (YYYY-MM-DD). "
                    "Omit for the first page (defaults to tomorrow)."
                ),
            ),
        ],
        responses={200: AdminDailyMilageSerializer(many=True)},
    )
    def employee_milage_summary(self, request, user_id=None):
        """GET /api/admin/tracking/milage/summary/<user_id>/?before=YYYY-MM-DD"""

        # ── Permission check ───────────────────────────────────────────────
        if not self._check_milage_manage(request.user):
            return response.Response(
                {"detail": "You do not have permission to view this employee's mileage data."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ── Resolve employee ───────────────────────────────────────────────
        try:
            employee = Employee.objects.get(id=user_id)
        except (Employee.DoesNotExist, ValueError):
            return response.Response(
                {"error": "Employee not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # ── Parse cursor ───────────────────────────────────────────────────
        before_param = request.query_params.get("before")
        if before_param:
            try:
                before_date = datetime.strptime(str(before_param).strip(), "%Y-%m-%d").date()
            except ValueError:
                return response.Response(
                    {"error": f"Invalid 'before' date '{before_param}'. Use YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            # Default: include today → upper bound is tomorrow
            from datetime import timedelta
            before_date = timezone.localdate() + timedelta(days=1)

        # ── Query — fetch PAGE_SIZE + 1 to detect whether there are more ──
        # Ordered newest-first so the user sees most recent days at the top.
        milage_qs = (
            Milage.objects
            .filter(employee=employee, date__lt=before_date)
            .select_related("employee", "attendance_id")
            .order_by("-date")  # newest first
        )[: self.PAGE_SIZE + 1]

        # Force evaluation once
        records = list(milage_qs)

        has_more = len(records) > self.PAGE_SIZE
        page_records = records[: self.PAGE_SIZE]  # trim the extra probe row

        # next_cursor = date of the oldest record in this page
        next_cursor = page_records[-1].date.strftime("%Y-%m-%d") if (has_more and page_records) else None

        # ── Build week_range labels for the page ──────────────────────────
        if page_records:
            newest_in_page = page_records[0].date
            oldest_in_page = page_records[-1].date
        else:
            newest_in_page = oldest_in_page = None

        # ── Serialize ─────────────────────────────────────────────────────
        serializer = AdminDailyMilageSerializer(page_records, many=True)

        return response.Response(
            {
                "employee_id":   str(employee.id),
                "employee_name": employee.name if getattr(employee, "name", None) else employee.username,
                "employee_role": employee.role,
                "week_start":    oldest_in_page.strftime("%Y-%m-%d") if oldest_in_page else None,
                "week_end":      newest_in_page.strftime("%Y-%m-%d") if newest_in_page else None,
                "count":         len(page_records),
                "has_more":      has_more,
                "next_cursor":   next_cursor,
                "results":       serializer.data,
            },
            status=status.HTTP_200_OK,
        )
