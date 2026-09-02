import datetime
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from users.models import Employee, EmployeeRole
from tracking.models import Attendance


class AttendanceAutoCheckoutTests(TestCase):
    def _get_dummy_image(self, name="test_image.jpg"):
        return SimpleUploadedFile(
            name=name,
            content=b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b",
            content_type="image/jpeg"
        )

    def setUp(self):
        self.client = APIClient()
        self.role, _ = EmployeeRole.objects.get_or_create(
            name="EMPLOYEE",
            defaults={
                "display_name": "Employee",
                "hierarchy_level": 6,
                "attendance_manage": True,
                "visit_manage": True,
            }
        )
        self.employee = Employee.objects.create_user(
            username="employee1",
            password="testpassword123",
            employeeidnum=101,
            must_change_password=False,
            is_active=True,
            role=self.role
        )
        self.client.force_authenticate(user=self.employee)

    def test_status_before_checkin(self):
        """When user has not checked in today and has no unclosed past records."""
        response = self.client.get("/api/tracking/attendance/status/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "Not check-in yet")
        self.assertEqual(response.data["date"], timezone.localdate().strftime("%Y-%m-%d"))
        self.assertIn("last_attendance", response.data)

    def test_status_with_unclosed_previous_day(self):
        """When user checked in on a previous day and forgot to check out."""
        yesterday = timezone.localdate() - datetime.timedelta(days=1)
        Attendance.objects.create(
            employee=self.employee,
            date=yesterday,
            start_km=100.0,
            start_time=datetime.time(9, 0, 0),
            start_image=self._get_dummy_image("start1.jpg"),
            work_now=True,
            end_time=None,
        )

        response = self.client.get("/api/tracking/attendance/status/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "Check-in")
        self.assertEqual(response.data["date"], yesterday.strftime("%Y-%m-%d"))
        self.assertEqual(response.data["start_time"], "09:00:00")
        self.assertEqual(response.data["detail"], "your not properly check-out previous working day")

    def test_start_blocked_when_unclosed_previous_day_exists(self):
        """User cannot start a new check-in until previous unclosed day is checked out."""
        yesterday = timezone.localdate() - datetime.timedelta(days=1)
        Attendance.objects.create(
            employee=self.employee,
            date=yesterday,
            start_km=100.0,
            start_time=datetime.time(9, 0, 0),
            start_image=self._get_dummy_image("start1.jpg"),
            work_now=True,
            end_time=None,
        )

        response = self.client.post(
            "/api/tracking/attendance/check-in/",
            {
                "start_km": 110.0,
                "image": self._get_dummy_image("start2.jpg"),
                "date": timezone.localdate().strftime("%Y-%m-%d"),
                "time": "09:00:00",
                "latitude": 13.0827,
                "longitude": 80.2707,
            },
            format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("your not properly check-out previous working day", response.data["detail"])

    def test_manual_checkout_of_previous_day(self):
        """Manual checkout of previous day marks auto_checkout=True, end_time=23:59:59, keeps original date."""
        yesterday = timezone.localdate() - datetime.timedelta(days=1)
        att = Attendance.objects.create(
            employee=self.employee,
            date=yesterday,
            start_km=100.0,
            start_time=datetime.time(9, 0, 0),
            start_image=self._get_dummy_image("start.jpg"),
            work_now=True,
            end_time=None,
        )

        response = self.client.post(
            "/api/tracking/attendance/check-out/",
            {
                "end_km": 150,
                "end_image": self._get_dummy_image("end.jpg"),
                "time": "18:00:00",
                "latitude": 13.0827,
                "longitude": 80.2707,
            },
            format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        att.refresh_from_db()
        self.assertFalse(att.work_now)
        self.assertTrue(att.auto_checkout)
        self.assertEqual(att.end_time, datetime.time(23, 59, 59))
        self.assertEqual(att.date, yesterday)
        self.assertEqual(att.total_km, 50.0)

        # Verify status endpoint now shows Not check-in yet with last_attendance auto_checkout=True
        status_res = self.client.get("/api/tracking/attendance/status/")
        self.assertEqual(status_res.status_code, status.HTTP_200_OK)
        self.assertEqual(status_res.data["status"], "Not check-in yet")
        self.assertEqual(status_res.data["last_attendance"]["date"], yesterday.strftime("%Y-%m-%d"))
        self.assertEqual(status_res.data["last_attendance"]["end_time"], "23:59:59")
        self.assertTrue(status_res.data["last_attendance"]["auto_checkout"])

    def test_normal_today_checkin_and_checkout(self):
        """Normal check-in and check-out on the same day sets auto_checkout=False."""
        today = timezone.localdate()

        # Check-in
        start_res = self.client.post(
            "/api/tracking/attendance/check-in/",
            {
                "start_km": 200.0,
                "image": self._get_dummy_image("start_today.jpg"),
                "date": today.strftime("%Y-%m-%d"),
                "time": "09:00:00",
                "latitude": 13.0827,
                "longitude": 80.2707,
            },
            format="multipart"
        )
        self.assertEqual(start_res.status_code, status.HTTP_201_CREATED)

        # Status after check-in
        status_res = self.client.get("/api/tracking/attendance/status/")
        self.assertEqual(status_res.status_code, status.HTTP_200_OK)
        self.assertEqual(status_res.data["status"], "Check-in")
        self.assertEqual(status_res.data["date"], today.strftime("%Y-%m-%d"))
        self.assertEqual(status_res.data["start_time"], "09:00:00")

        # Check-out
        end_res = self.client.post(
            "/api/tracking/attendance/check-out/",
            {
                "end_km": 250,
                "end_image": self._get_dummy_image("end_today.jpg"),
                "time": "18:00:00",
                "latitude": 13.0827,
                "longitude": 80.2707,
            },
            format="multipart"
        )
        self.assertEqual(end_res.status_code, status.HTTP_200_OK)

        # Status after check-out
        status_after_res = self.client.get("/api/tracking/attendance/status/")
        self.assertEqual(status_after_res.status_code, status.HTTP_200_OK)
        self.assertEqual(status_after_res.data["status"], "Check-out")
        self.assertEqual(status_after_res.data["start_time"], "09:00:00")
        self.assertEqual(status_after_res.data["end_time"], "18:00:00")
        self.assertFalse(status_after_res.data["auto_checkout"])
