import logging
from datetime import date, timedelta
from decimal import Decimal
from django.db import models
from django.db.models import Sum, F
from django.utils import timezone
from users.models import Employee
from sales.models import Order, OrderItem, Collection, MonthlyTarget
from tracking.models import Attendance, Visit, VisitPlan
from notifications.models import Notification
from notifications.services import NotificationService
from notifications.choices import NotificationType, NotificationPriority

logger = logging.getLogger(__name__)


class DuplicateReportError(Exception):
    """Raised when an employee attempts to confirm the same report twice on the same day."""
    pass


class ReportService:
    """
    Encapsulates dynamic calculation and notification delivery for
    Morning and EOD reports.
    """

    @staticmethod
    def get_target_date(date_str=None):
        """Parse date string YYYY-MM-DD or return today's local date (Asia/Kolkata)."""
        if date_str:
            if isinstance(date_str, date):
                return date_str
            try:
                from datetime import datetime
                return datetime.strptime(str(date_str), "%Y-%m-%d").date()
            except ValueError:
                pass
        return timezone.localdate()

    @staticmethod
    def calculate_delivered_sales(employee, target_date, mtd=False):
        """
        Calculate delivered sales using database aggregation on OrderItem:
        OrderItem.quantity * OrderItem.unit_price where Order.status == 'delivered'.
        Ignores soft-deleted orders and items.
        """
        year = target_date.year
        month = target_date.month

        qs = OrderItem.objects.filter(
            order__employee=employee,
            order__status="delivered",
            order__is_deleted=False,
            is_deleted=False,
        )

        if mtd:
            qs = qs.filter(
                order__created_at__year=year,
                order__created_at__month=month,
                order__created_at__date__lte=target_date,
            )
        else:
            qs = qs.filter(order__created_at__date=target_date)

        total = qs.aggregate(
            total=Sum(
                F("quantity") * F("unit_price"),
                output_field=models.DecimalField(max_digits=12, decimal_places=2),
            )
        )["total"]

        return total if total is not None else Decimal("0.00")

    @staticmethod
    def calculate_valid_collections(employee, target_date, mtd=False):
        """
        Calculate valid collections (status == 'success', is_deleted == False)
        using database aggregation.
        """
        year = target_date.year
        month = target_date.month

        qs = Collection.objects.filter(
            employee=employee,
            status="success",
            is_deleted=False,
        )

        if mtd:
            qs = qs.filter(
                created_at__year=year,
                created_at__month=month,
                created_at__date__lte=target_date,
            )
        else:
            qs = qs.filter(created_at__date=target_date)

        total = qs.aggregate(
            total=Sum("amount", output_field=models.DecimalField(max_digits=12, decimal_places=2))
        )["total"]

        return total if total is not None else Decimal("0.00")

    @staticmethod
    def calculate_visits(employee, target_date, mtd=False):
        """Calculate visit count using database count."""
        year = target_date.year
        month = target_date.month

        qs = Visit.objects.filter(employee=employee)

        if mtd:
            qs = qs.filter(
                created_at__year=year,
                created_at__month=month,
                created_at__date__lte=target_date,
            )
        else:
            qs = qs.filter(created_at__date=target_date)

        return qs.count()

    @staticmethod
    def calculate_mileage(attendance):
        """
        Strict mileage calculation using ONLY Attendance start_km and end_km.
        travel_km = end_km - start_km.
        """
        if not attendance:
            return {
                "status": "missing_attendance",
                "start_km": None,
                "end_km": None,
                "travel_km": None,
                "message": "No attendance record found for this date.",
            }

        start_km = attendance.start_km
        end_km = attendance.end_km

        if start_km is None or end_km is None:
            return {
                "status": "incomplete",
                "start_km": start_km,
                "end_km": end_km,
                "travel_km": None,
                "message": "Start KM or End KM missing. Please check out first.",
            }

        if end_km < start_km:
            return {
                "status": "invalid",
                "start_km": start_km,
                "end_km": end_km,
                "travel_km": None,
                "error": "End KM cannot be less than Start KM.",
            }

        travel_km = round(end_km - start_km, 2)
        return {
            "status": "complete",
            "start_km": start_km,
            "end_km": end_km,
            "travel_km": travel_km,
        }

    @staticmethod
    def get_morning_report_data(employee, target_date):
        """
        Dynamically calculate morning report data.
        Combines MonthlyTarget, Attendance targets/plan, MTD sales/collections/visits, and balances.
        """
        year = target_date.year
        month = target_date.month

        # 1. Monthly target
        monthly_target = MonthlyTarget.objects.filter(
            employee=employee, year=year, month=month
        ).first()

        monthly_sales_target = monthly_target.sales_target if monthly_target else Decimal("0.00")
        monthly_collection_target = (
            monthly_target.collection_target if monthly_target else Decimal("0.00")
        )
        monthly_visit_target = monthly_target.visit_target if monthly_target else 0

        # 2. Today's attendance & daily targets
        attendance = Attendance.objects.filter(employee=employee, date=target_date).first()

        today_sales_target = (
            attendance.daily_sales_target
            if attendance and attendance.daily_sales_target is not None
            else Decimal("0.00")
        )
        today_collection_target = (
            attendance.daily_collection_target
            if attendance and attendance.daily_collection_target is not None
            else Decimal("0.00")
        )
        today_visit_target = (
            attendance.daily_visit_target
            if attendance and attendance.daily_visit_target is not None
            else 0
        )
        today_visit_plan = attendance.today_visit_plan if attendance else ""

        # 3. MTD actuals
        mtd_delivered_sales = ReportService.calculate_delivered_sales(
            employee, target_date, mtd=True
        )
        mtd_valid_collection = ReportService.calculate_valid_collections(
            employee, target_date, mtd=True
        )
        mtd_visits = ReportService.calculate_visits(employee, target_date, mtd=True)

        # 4. Balances
        sales_balance = monthly_sales_target - mtd_delivered_sales
        collection_balance = monthly_collection_target - mtd_valid_collection
        visit_balance = monthly_visit_target - mtd_visits

        return {
            "employee_id": str(employee.id),
            "employee_name": employee.name or employee.username,
            "employeeidnum": employee.employeeidnum,
            "date": target_date.strftime("%Y-%m-%d"),
            "year": year,
            "month": month,
            "sales": {
                "monthly_target": f"{monthly_sales_target:.2f}",
                "mtd_delivered": f"{mtd_delivered_sales:.2f}",
                "balance": f"{sales_balance:.2f}",
                "today_target": f"{today_sales_target:.2f}",
            },
            "collection": {
                "monthly_target": f"{monthly_collection_target:.2f}",
                "mtd_valid": f"{mtd_valid_collection:.2f}",
                "balance": f"{collection_balance:.2f}",
                "today_target": f"{today_collection_target:.2f}",
            },
            "visit": {
                "monthly_target": monthly_visit_target,
                "mtd_visits": mtd_visits,
                "balance": visit_balance,
                "today_target": today_visit_target,
                "today_plan": today_visit_plan or "",
            },
            "attendance_status": "Checked-in" if attendance else "Not Checked-in",
        }

    @staticmethod
    def get_eod_report_data(employee, target_date):
        """
        Dynamically calculate EOD report data.
        Combines today's delivered sales, collections, visits, monthly progress,
        strict mileage from attendance, and tomorrow's plan.
        """
        year = target_date.year
        month = target_date.month
        tomorrow_date = target_date + timedelta(days=1)

        # 1. Monthly target
        monthly_target = MonthlyTarget.objects.filter(
            employee=employee, year=year, month=month
        ).first()

        monthly_sales_target = monthly_target.sales_target if monthly_target else Decimal("0.00")
        monthly_collection_target = (
            monthly_target.collection_target if monthly_target else Decimal("0.00")
        )
        monthly_visit_target = monthly_target.visit_target if monthly_target else 0

        # 2. Today's targets from attendance
        attendance = Attendance.objects.filter(employee=employee, date=target_date).first()

        today_sales_target = (
            attendance.daily_sales_target
            if attendance and attendance.daily_sales_target is not None
            else Decimal("0.00")
        )
        today_collection_target = (
            attendance.daily_collection_target
            if attendance and attendance.daily_collection_target is not None
            else Decimal("0.00")
        )
        today_visit_target = (
            attendance.daily_visit_target
            if attendance and attendance.daily_visit_target is not None
            else 0
        )

        # 3. Today's actuals
        today_delivered_sales = ReportService.calculate_delivered_sales(
            employee, target_date, mtd=False
        )
        today_valid_collection = ReportService.calculate_valid_collections(
            employee, target_date, mtd=False
        )
        today_visits = ReportService.calculate_visits(employee, target_date, mtd=False)

        # 4. MTD actuals
        mtd_delivered_sales = ReportService.calculate_delivered_sales(
            employee, target_date, mtd=True
        )
        mtd_valid_collection = ReportService.calculate_valid_collections(
            employee, target_date, mtd=True
        )
        mtd_visits = ReportService.calculate_visits(employee, target_date, mtd=True)

        # 5. Mileage (Strict)
        mileage = ReportService.calculate_mileage(attendance)

        # 6. Tomorrow's plan
        tomorrow_plan = VisitPlan.objects.filter(
            employee=employee, plan_date=tomorrow_date
        ).first()

        tomorrow_plan_data = {
            "plan_date": tomorrow_date.strftime("%Y-%m-%d"),
            "area": tomorrow_plan.area if tomorrow_plan else "",
            "visit_target": tomorrow_plan.visit_target if tomorrow_plan else 0,
        }

        # Progress percentages
        sales_progress_pct = (
            round(float(mtd_delivered_sales / monthly_sales_target) * 100, 2)
            if monthly_sales_target > 0
            else 0.0
        )
        collection_progress_pct = (
            round(float(mtd_valid_collection / monthly_collection_target) * 100, 2)
            if monthly_collection_target > 0
            else 0.0
        )
        visit_progress_pct = (
            round(float(mtd_visits / monthly_visit_target) * 100, 2)
            if monthly_visit_target > 0
            else 0.0
        )

        return {
            "employee_id": str(employee.id),
            "employee_name": employee.name or employee.username,
            "employeeidnum": employee.employeeidnum,
            "date": target_date.strftime("%Y-%m-%d"),
            "year": year,
            "month": month,
            "today_actuals": {
                "sales_target": f"{today_sales_target:.2f}",
                "delivered_sales": f"{today_delivered_sales:.2f}",
                "collection_target": f"{today_collection_target:.2f}",
                "valid_collection": f"{today_valid_collection:.2f}",
                "visit_target": today_visit_target,
                "visits": today_visits,
            },
            "monthly_progress": {
                "sales": {
                    "monthly_target": f"{monthly_sales_target:.2f}",
                    "mtd_delivered": f"{mtd_delivered_sales:.2f}",
                    "progress_percentage": sales_progress_pct,
                },
                "collection": {
                    "monthly_target": f"{monthly_collection_target:.2f}",
                    "mtd_valid": f"{mtd_valid_collection:.2f}",
                    "progress_percentage": collection_progress_pct,
                },
                "visit": {
                    "monthly_target": monthly_visit_target,
                    "mtd_visits": mtd_visits,
                    "progress_percentage": visit_progress_pct,
                },
            },
            "mileage": mileage,
            "tomorrow_plan": tomorrow_plan_data,
        }

    @staticmethod
    def get_managing_recipients(employee):
        """
        Find immediate managers authorized to manage this employee according to role hierarchy.
        Avoids spamming every level by finding the closest managerial tier above the employee.
        """
        all_users = Employee.objects.filter(is_active=True, is_deleted=False).exclude(pk=employee.pk)
        managers = [u for u in all_users if u.can_manage(employee)]

        if not managers:
            # Fallback: system superusers / owners
            managers = [u for u in all_users if u.is_owner]

        if not managers:
            return []

        # Find the immediate higher tier (maximum hierarchy_level strictly < employee.hierarchy_level)
        immediate_level = max(m.hierarchy_level for m in managers)
        direct_managers = [m for m in managers if m.hierarchy_level == immediate_level]
        return direct_managers

    @staticmethod
    def check_duplicate_submission(employee, report_type, target_date):
        """Check if report has already been confirmed today to prevent duplicate submissions."""
        date_str = target_date.strftime("%Y-%m-%d")
        return Notification.objects.filter(
            sender=employee,
            payload__report_type=report_type,
            payload__report_date=date_str,
        ).exists()

    @staticmethod
    def confirm_morning_report(employee, target_date):
        """
        Recalculates actual values from DB, ensures no duplicate submission,
        and delivers Morning Report to manager(s) via Notification.
        """
        if ReportService.check_duplicate_submission(employee, "morning_report", target_date):
            raise DuplicateReportError("Morning report has already been confirmed for this date.")

        report_data = ReportService.get_morning_report_data(employee, target_date)
        recipients = ReportService.get_managing_recipients(employee)

        title = f"Morning Report - {employee.name or employee.username} ({target_date.strftime('%Y-%m-%d')})"
        body = (
            f"Employee: {employee.name or employee.username} (ID: {employee.employeeidnum})\n"
            f"Date: {target_date.strftime('%Y-%m-%d')}\n"
            f"Sales Target Today: ₹{report_data['sales']['today_target']} (MTD Delivered: ₹{report_data['sales']['mtd_delivered']})\n"
            f"Collection Target Today: ₹{report_data['collection']['today_target']} (MTD Valid: ₹{report_data['collection']['mtd_valid']})\n"
            f"Visit Target Today: {report_data['visit']['today_target']} (MTD: {report_data['visit']['mtd_visits']})\n"
            f"Plan: {report_data['visit']['today_plan']}"
        )

        payload = {
            "report_type": "morning_report",
            "report_date": target_date.strftime("%Y-%m-%d"),
            "submitted_at": timezone.now().isoformat(),
            "report_data": report_data,
        }

        if recipients:
            NotificationService.send_bulk(
                recipients=recipients,
                title=title,
                body=body,
                notification_type=NotificationType.ATTENDANCE,
                sender=employee,
                priority=NotificationPriority.MEDIUM,
                payload=payload,
            )

        return report_data

    @staticmethod
    def confirm_eod_report(employee, target_date, tomorrow_area, tomorrow_visit_target):
        """
        Saves tomorrow's visit plan, recalculates actual values, ensures no duplicate submission,
        and delivers EOD Report to manager(s) via Notification.
        """
        if ReportService.check_duplicate_submission(employee, "eod_report", target_date):
            raise DuplicateReportError("EOD report has already been confirmed for this date.")

        # Save tomorrow's visit plan
        tomorrow_date = target_date + timedelta(days=1)
        VisitPlan.objects.update_or_create(
            employee=employee,
            plan_date=tomorrow_date,
            defaults={
                "area": tomorrow_area,
                "visit_target": tomorrow_visit_target,
            },
        )

        report_data = ReportService.get_eod_report_data(employee, target_date)
        recipients = ReportService.get_managing_recipients(employee)

        mileage_str = (
            f"{report_data['mileage']['travel_km']} km (Start: {report_data['mileage']['start_km']}, End: {report_data['mileage']['end_km']})"
            if report_data['mileage'].get('travel_km') is not None
            else report_data['mileage'].get('message') or report_data['mileage'].get('error') or "N/A"
        )

        title = f"EOD Report - {employee.name or employee.username} ({target_date.strftime('%Y-%m-%d')})"
        body = (
            f"Employee: {employee.name or employee.username} (ID: {employee.employeeidnum})\n"
            f"Date: {target_date.strftime('%Y-%m-%d')}\n"
            f"Delivered Sales Today: ₹{report_data['today_actuals']['delivered_sales']} (Target: ₹{report_data['today_actuals']['sales_target']})\n"
            f"Collections Today: ₹{report_data['today_actuals']['valid_collection']} (Target: ₹{report_data['today_actuals']['collection_target']})\n"
            f"Visits Today: {report_data['today_actuals']['visits']} (Target: {report_data['today_actuals']['visit_target']})\n"
            f"Mileage: {mileage_str}\n"
            f"Tomorrow Plan: {tomorrow_area} (Target: {tomorrow_visit_target} visits)"
        )

        payload = {
            "report_type": "eod_report",
            "report_date": target_date.strftime("%Y-%m-%d"),
            "submitted_at": timezone.now().isoformat(),
            "report_data": report_data,
        }

        if recipients:
            NotificationService.send_bulk(
                recipients=recipients,
                title=title,
                body=body,
                notification_type=NotificationType.ATTENDANCE,
                sender=employee,
                priority=NotificationPriority.MEDIUM,
                payload=payload,
            )

        return report_data
