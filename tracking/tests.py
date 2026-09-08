import uuid
from datetime import date, timedelta
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from tracking.models import Attendance
from users.models import Employee, EmployeeRole


class AttendanceHierarchyAccessTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Create roles
        self.role_owner, _ = EmployeeRole.objects.get_or_create(
            name="OWNER",
            defaults={"display_name": "Owner", "hierarchy_level": 1, "attendance_manage": True},
        )
        self.role_senior_mgr, _ = EmployeeRole.objects.get_or_create(
            name="SENIOR_MANAGER",
            defaults={"display_name": "Senior Manager", "hierarchy_level": 2, "attendance_manage": True},
        )
        self.role_manager, _ = EmployeeRole.objects.get_or_create(
            name="MANAGER",
            defaults={"display_name": "Manager", "hierarchy_level": 3, "attendance_manage": True},
        )
        self.role_salesman, _ = EmployeeRole.objects.get_or_create(
            name="SALESMAN",
            defaults={"display_name": "Salesman", "hierarchy_level": 6, "attendance_manage": False},
        )

        # 1. Owner
        self.owner = Employee.objects.create_user(
            username="owner_user",
            email="owner@example.com",
            password="Password@123",
            employeeidnum=0,
            role=self.role_owner,
            is_superuser=True,
            must_change_password=False,
        )

        # 2. Senior Manager (level 2)
        self.senior_mgr = Employee.objects.create_user(
            username="snr_mgr_user",
            email="snr_mgr@example.com",
            password="Password@123",
            employeeidnum=2001,
            role=self.role_senior_mgr,
            must_change_password=False,
        )

        # 3. Requesting Manager (level 3)
        self.manager = Employee.objects.create_user(
            username="mgr_user",
            email="mgr@example.com",
            password="Password@123",
            employeeidnum=3001,
            role=self.role_manager,
            must_change_password=False,
        )

        # 4. Peer Manager (level 3)
        self.peer_manager = Employee.objects.create_user(
            username="peer_mgr_user",
            email="peer_mgr@example.com",
            password="Password@123",
            employeeidnum=3002,
            role=self.role_manager,
            must_change_password=False,
        )

        # 5. Salesman (level 6)
        self.salesman = Employee.objects.create_user(
            username="sales_user",
            email="sales@example.com",
            password="Password@123",
            employeeidnum=6001,
            role=self.role_salesman,
            must_change_password=False,
        )

        self.today = timezone.localdate()

        # Create attendance records for today
        self.att_owner = Attendance.objects.create(
            employee=self.owner,
            date=self.today,
            start_time=timezone.now().time(),
            start_km=10,
        )
        self.att_senior = Attendance.objects.create(
            employee=self.senior_mgr,
            date=self.today,
            start_time=timezone.now().time(),
            start_km=20,
        )
        self.att_manager = Attendance.objects.create(
            employee=self.manager,
            date=self.today,
            start_time=timezone.now().time(),
            start_km=30,
        )
        self.att_salesman = Attendance.objects.create(
            employee=self.salesman,
            date=self.today,
            start_time=timezone.now().time(),
            start_km=40,
        )
        # Peer manager has NO attendance record today -> should be marked Absent

    def test_admin_attendance_by_date_manager_cannot_see_superiors(self):
        """
        Manager (level 3) calling admin_attendance_by_date must ONLY see
        peers (level 3) and subordinates (level 6). Owner (level 1) and
        Senior Manager (level 2) must be excluded.
        """
        self.client.force_authenticate(user=self.manager)
        url = "/api/admin/tracking/attendance/date/"
        resp = self.client.get(url, {"date": self.today.strftime("%Y-%m-%d")})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        data = resp.data
        results = data["results"]
        returned_emp_ids = [
            r["employee_id"]
            for r in results.get("checked_in", []) + results.get("checked_out", []) + results.get("absent", [])
        ]

        # Manager, Peer Manager, and Salesman must be present
        self.assertIn(str(self.manager.id), returned_emp_ids)
        self.assertIn(str(self.peer_manager.id), returned_emp_ids)
        self.assertIn(str(self.salesman.id), returned_emp_ids)

        # Superiors (Owner & Senior Manager) must NOT be present
        self.assertNotIn(str(self.owner.id), returned_emp_ids)
        self.assertNotIn(str(self.senior_mgr.id), returned_emp_ids)

        # Total employees in summary should only count visible employees (3, not 5)
        self.assertEqual(data["summary"]["total_employees"], 3)

    def test_admin_attendance_by_date_owner_sees_all(self):
        """Owner sees all employees without restriction."""
        self.client.force_authenticate(user=self.owner)
        url = "/api/admin/tracking/attendance/date/"
        resp = self.client.get(url, {"date": self.today.strftime("%Y-%m-%d")})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        data = resp.data
        returned_emp_ids = [
            r["employee_id"]
            for r in data["results"]["checked_in"] + data["results"]["checked_out"] + data["results"]["absent"]
        ]

        self.assertIn(str(self.owner.id), returned_emp_ids)
        self.assertIn(str(self.senior_mgr.id), returned_emp_ids)
        self.assertIn(str(self.manager.id), returned_emp_ids)
        self.assertIn(str(self.peer_manager.id), returned_emp_ids)
        self.assertIn(str(self.salesman.id), returned_emp_ids)
        self.assertEqual(data["summary"]["total_employees"], 5)

    def test_admin_employee_attendance_manager_cannot_view_superior(self):
        """Manager cannot view full monthly attendance of Senior Manager or Owner."""
        self.client.force_authenticate(user=self.manager)

        # Attempt to view Senior Manager's attendance -> 403
        resp_snr = self.client.get(f"/api/admin/tracking/attendance/{self.senior_mgr.id}/")
        self.assertEqual(resp_snr.status_code, status.HTTP_403_FORBIDDEN)

        # Attempt to view Owner's attendance -> 403
        resp_owner = self.client.get(f"/api/admin/tracking/attendance/{self.owner.id}/")
        self.assertEqual(resp_owner.status_code, status.HTTP_403_FORBIDDEN)

        # Attempt to view Salesman's attendance -> 200 OK
        resp_sales = self.client.get(f"/api/admin/tracking/attendance/{self.salesman.id}/")
        self.assertEqual(resp_sales.status_code, status.HTTP_200_OK)

        # Attempt to view Peer Manager's attendance -> 200 OK
        resp_peer = self.client.get(f"/api/admin/tracking/attendance/{self.peer_manager.id}/")
        self.assertEqual(resp_peer.status_code, status.HTTP_200_OK)

    def test_attendance_retrieve_manager_cannot_view_superior_record(self):
        """Manager cannot retrieve single attendance record of a superior."""
        self.client.force_authenticate(user=self.manager)

        # Superior record -> 403
        resp = self.client.get(f"/api/tracking/attendance/{self.att_senior.id}/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        # Salesman record -> 200 OK
        resp_sales = self.client.get(f"/api/tracking/attendance/{self.att_salesman.id}/")
        self.assertEqual(resp_sales.status_code, status.HTTP_200_OK)

        # Own record -> 200 OK
        resp_own = self.client.get(f"/api/tracking/attendance/{self.att_manager.id}/")
        self.assertEqual(resp_own.status_code, status.HTTP_200_OK)

    def test_attendance_partial_update_manager_cannot_edit_equal_or_superior(self):
        """Manager cannot PATCH attendance of an equal or superior employee."""
        self.client.force_authenticate(user=self.manager)

        # Attempt to edit Senior Manager -> 403
        resp_snr = self.client.patch(
            f"/api/tracking/attendance/{self.att_senior.id}/",
            {"start_km": 999},
            format="json",
        )
        self.assertEqual(resp_snr.status_code, status.HTTP_403_FORBIDDEN)

        # Attempt to edit Salesman (subordinate) -> 200 OK
        resp_sales = self.client.patch(
            f"/api/tracking/attendance/{self.att_salesman.id}/",
            {"start_km": 999},
            format="json",
        )
        self.assertEqual(resp_sales.status_code, status.HTTP_200_OK)
