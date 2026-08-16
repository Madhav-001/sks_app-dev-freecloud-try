import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from tracking.models import Attendance

class Command(BaseCommand):
    help = "Automatically check-out employees who forgot to check-out."

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help='Run auto-checkout for a specific date (YYYY-MM-DD).'
        )

    def handle(self, *args, **options):
        # Determine the target timezone-aware today
        local_now = timezone.localtime(timezone.now())
        local_date = local_now.date()
        local_time = local_now.time()

        # If a specific date is provided, use it
        date_str = options.get('date')
        if date_str:
            try:
                target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                attendances = Attendance.objects.filter(
                    work_now=True,
                    date=target_date
                )
                self.stdout.write(self.style.WARNING(f"Running auto-checkout for specific date: {target_date}"))
            except ValueError:
                self.stdout.write(self.style.ERROR(f"Invalid date format: {date_str}. Use YYYY-MM-DD."))
                return
        else:
            # Standard daily run:
            # 1. Past dates are always eligible (date < local_date).
            # 2. Today's date is eligible only if current local time is >= 23:59:59.
            cutoff_time = datetime.time(23, 59, 59)
            if local_time >= cutoff_time:
                attendances = Attendance.objects.filter(
                    work_now=True,
                    date__lte=local_date
                )
            else:
                attendances = Attendance.objects.filter(
                    work_now=True,
                    date__lt=local_date
                )

        count = attendances.count()
        self.stdout.write(f"Found {count} active check-ins eligible for auto-checkout.")

        checkout_time = datetime.time(23, 59, 59)
        updated_count = 0

        for attendance in attendances:
            attendance.work_now = False
            attendance.auto_checkout = True
            attendance.end_km = None
            attendance.end_image = None
            attendance.end_time = checkout_time
            attendance.end_latitude = 0.0
            attendance.end_longitude = 0.0
            attendance.end_location = None
            attendance.total_km = None
            attendance.total_time = None
            attendance.save()

            updated_count += 1
            employee_identifier = attendance.employee.name or attendance.employee.username
            self.stdout.write(
                self.style.SUCCESS(
                    f"Auto-checked out employee '{employee_identifier}' (ID: {attendance.employee.id}) for date {attendance.date}"
                )
            )

        self.stdout.write(self.style.SUCCESS(f"Successfully auto-checked out {updated_count} attendances."))
