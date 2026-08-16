from rest_framework import status, viewsets, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter
from users.models import Employee
from users.permissions import IsAdminUser, is_admin_of
from sales.models import MonthlyTarget
from .services import ReportService, DuplicateReportError
from .serializers import (
    MonthlyTargetSerializer,
    MorningConfirmSerializer,
    EODConfirmSerializer,
)


class MorningReportPreviewView(APIView):
    """
    GET /api/reports/morning/preview/
    Dynamically returns the morning report preview for the authenticated employee.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Morning Report Preview",
        description=(
            "Returns dynamic morning report preview for the authenticated salesperson. "
            "Combines Monthly targets, MTD actuals, Balances, and today's check-in targets."
        ),
        parameters=[
            OpenApiParameter(
                name="date",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Date format YYYY-MM-DD. Defaults to today.",
            )
        ],
    )
    def get(self, request):
        date_param = request.query_params.get("date")
        target_date = ReportService.get_target_date(date_param)
        report_data = ReportService.get_morning_report_data(request.user, target_date)
        return Response(report_data, status=status.HTTP_200_OK)


class MorningReportConfirmView(APIView):
    """
    POST /api/reports/morning/confirm/
    Recalculates values, prevents duplicate confirmation, and delivers Morning Report to manager.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Morning Report Confirm & Submit",
        request=MorningConfirmSerializer,
        description="Confirms morning report, recalculates actual values, and sends notification to manager.",
    )
    def post(self, request):
        serializer = MorningConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        date_param = serializer.validated_data.get("date") or request.query_params.get("date")
        target_date = ReportService.get_target_date(date_param)

        try:
            report_data = ReportService.confirm_morning_report(request.user, target_date)
        except DuplicateReportError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "message": "Morning report confirmed and delivered successfully.",
                "report": report_data,
            },
            status=status.HTTP_200_OK,
        )


class EODReportPreviewView(APIView):
    """
    GET /api/reports/eod/preview/
    Dynamically returns the EOD report preview for the authenticated employee.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="EOD Report Preview",
        description=(
            "Returns dynamic EOD report preview for the authenticated salesperson. "
            "Calculates today's delivered sales, collections, visits, strict mileage (end_km - start_km), "
            "and monthly progress."
        ),
        parameters=[
            OpenApiParameter(
                name="date",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Date format YYYY-MM-DD. Defaults to today.",
            )
        ],
    )
    def get(self, request):
        date_param = request.query_params.get("date")
        target_date = ReportService.get_target_date(date_param)
        report_data = ReportService.get_eod_report_data(request.user, target_date)
        return Response(report_data, status=status.HTTP_200_OK)


class EODReportConfirmView(APIView):
    """
    POST /api/reports/eod/confirm/
    Saves tomorrow's plan, recalculates actual values, and delivers EOD Report to manager.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="EOD Report Confirm & Submit",
        request=EODConfirmSerializer,
        description="Confirms EOD report with tomorrow's visit plan and sends notification to manager.",
    )
    def post(self, request):
        serializer = EODConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        date_param = serializer.validated_data.get("date") or request.query_params.get("date")
        target_date = ReportService.get_target_date(date_param)

        tomorrow_area = serializer.validated_data["resolved_area"]
        tomorrow_visit_target = serializer.validated_data["resolved_visit_target"]

        try:
            report_data = ReportService.confirm_eod_report(
                request.user, target_date, tomorrow_area, tomorrow_visit_target
            )
        except DuplicateReportError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "message": "EOD report confirmed and delivered successfully.",
                "report": report_data,
            },
            status=status.HTTP_200_OK,
        )


class AdminMorningReportView(APIView):
    """
    GET /api/admin/reports/morning/?employee_id=<id>&date=YYYY-MM-DD
    Admin/Manager API to view any subordinate employee's morning report.
    """
    permission_classes = [IsAdminUser]

    @extend_schema(
        summary="Admin: Morning Report by Employee and Date",
        parameters=[
            OpenApiParameter(
                name="employee_id",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
                description="UUID of employee",
            ),
            OpenApiParameter(
                name="date",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Date (YYYY-MM-DD). Defaults to today.",
            ),
        ],
    )
    def get(self, request):
        employee_id = request.query_params.get("employee_id")
        if not employee_id:
            return Response(
                {"error": "employee_id query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            target_employee = Employee.objects.get(id=employee_id, is_deleted=False)
        except (Employee.DoesNotExist, ValueError):
            return Response(
                {"error": "Employee not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Hierarchy permission check
        if not is_admin_of(request.user, target_employee) and target_employee.id != request.user.id:
            return Response(
                {"detail": "You do not have permission to access reports for this employee."},
                status=status.HTTP_403_FORBIDDEN,
            )

        date_param = request.query_params.get("date")
        target_date = ReportService.get_target_date(date_param)
        report_data = ReportService.get_morning_report_data(target_employee, target_date)
        return Response(report_data, status=status.HTTP_200_OK)


class AdminEODReportView(APIView):
    """
    GET /api/admin/reports/eod/?employee_id=<id>&date=YYYY-MM-DD
    Admin/Manager API to view any subordinate employee's EOD report.
    """
    permission_classes = [IsAdminUser]

    @extend_schema(
        summary="Admin: EOD Report by Employee and Date",
        parameters=[
            OpenApiParameter(
                name="employee_id",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
                description="UUID of employee",
            ),
            OpenApiParameter(
                name="date",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Date (YYYY-MM-DD). Defaults to today.",
            ),
        ],
    )
    def get(self, request):
        employee_id = request.query_params.get("employee_id")
        if not employee_id:
            return Response(
                {"error": "employee_id query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            target_employee = Employee.objects.get(id=employee_id, is_deleted=False)
        except (Employee.DoesNotExist, ValueError):
            return Response(
                {"error": "Employee not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Hierarchy permission check
        if not is_admin_of(request.user, target_employee) and target_employee.id != request.user.id:
            return Response(
                {"detail": "You do not have permission to access reports for this employee."},
                status=status.HTTP_403_FORBIDDEN,
            )

        date_param = request.query_params.get("date")
        target_date = ReportService.get_target_date(date_param)
        report_data = ReportService.get_eod_report_data(target_employee, target_date)
        return Response(report_data, status=status.HTTP_200_OK)


class MonthlyTargetViewSet(viewsets.ModelViewSet):
    """
    CRUD viewset for MonthlyTarget.
    - Owner/Managers can set/update targets for their subordinates.
    - Sales employees can view only their own targets (read-only).
    """
    serializer_class = MonthlyTargetSerializer
    queryset = MonthlyTarget.objects.all().select_related("employee")

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy"]:
            return [IsAdminUser()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        qs = MonthlyTarget.objects.all().select_related("employee")

        # Filters
        employee_id = self.request.query_params.get("employee_id")
        year = self.request.query_params.get("year")
        month = self.request.query_params.get("month")

        if employee_id:
            qs = qs.filter(employee_id=employee_id)
        if year:
            qs = qs.filter(year=year)
        if month:
            qs = qs.filter(month=month)

        if is_admin_of(user):
            if user.is_owner:
                return qs
            # Manager: only subordinate employees or own
            subordinate_ids = [
                e.id for e in Employee.objects.filter(is_active=True, is_deleted=False)
                if user.can_manage(e) or e.id == user.id
            ]
            return qs.filter(employee_id__in=subordinate_ids)

        # Non-admin sales employees see only their own targets
        return qs.filter(employee=user)

    def perform_create(self, serializer):
        target_employee = serializer.validated_data["employee"]
        if not is_admin_of(self.request.user, target_employee):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(
                f"You do not have permission to set targets for {target_employee.username}."
            )
        serializer.save()

    def perform_update(self, serializer):
        target_employee = serializer.instance.employee
        if not is_admin_of(self.request.user, target_employee):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(
                f"You do not have permission to update targets for {target_employee.username}."
            )
        serializer.save()

    def perform_destroy(self, instance):
        target_employee = instance.employee
        if not is_admin_of(self.request.user, target_employee):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(
                f"You do not have permission to delete targets for {target_employee.username}."
            )
        instance.delete()
