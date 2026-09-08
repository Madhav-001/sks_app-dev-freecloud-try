import uuid
from datetime import date, timedelta
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from tracking.models import Visit
from users.models import Employee, EmployeeRole


class AdminSalesmanVisitCountApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Create roles
        self.role_owner, _ = EmployeeRole.objects.get_or_create(
            name="OWNER",
            defaults={"display_name": "Owner", "hierarchy_level": 1},
        )
        self.role_manager_with_visit, _ = EmployeeRole.objects.get_or_create(
            name="VISIT_ADMIN",
            defaults={"display_name": "Visit Manager", "hierarchy_level": 3, "visit_manage": True},
        )
        self.role_manager_with_visit.visit_manage = True
        self.role_manager_with_visit.save()

        self.role_no_visit, _ = EmployeeRole.objects.get_or_create(
            name="NO_VISIT_ROLE",
            defaults={"display_name": "No Visit Role", "hierarchy_level": 5, "visit_manage": False},
        )
        self.role_no_visit.visit_manage = False
        self.role_no_visit.save()
        self.role_salesman, _ = EmployeeRole.objects.get_or_create(
            name="SALESMAN",
            defaults={"display_name": "Sales Executive", "hierarchy_level": 6},
        )
        self.role_driver, _ = EmployeeRole.objects.get_or_create(
            name="DRIVER",
            defaults={"display_name": "Driver", "hierarchy_level": 6},
        )

        # 1. Owner User
        self.owner = Employee.objects.create_user(
            username="owner_user",
            email="owner@example.com",
            password="Password@123",
            employeeidnum=1001,
            role=self.role_owner,
            must_change_password=False,
        )

        # 2. Manager with visit_manage = True
        self.manager_visit_admin = Employee.objects.create_user(
            username="manager_visit",
            email="manager_visit@example.com",
            password="Password@123",
            employeeidnum=1002,
            role=self.role_manager_with_visit,
            must_change_password=False,
        )

        # 3. Employee without visit_manage permission
        self.regular_manager = Employee.objects.create_user(
            username="reg_manager",
            email="reg_manager@example.com",
            password="Password@123",
            employeeidnum=1003,
            role=self.role_no_visit,
            must_change_password=False,
        )

        # 4. Salesman 1
        self.salesman1 = Employee.objects.create_user(
            username="salesman_1",
            name="Alice Sales",
            email="salesman1@example.com",
            password="Password@123",
            employeeidnum=2001,
            role=self.role_salesman,
            must_change_password=False,
        )

        # 5. Salesman 2
        self.salesman2 = Employee.objects.create_user(
            username="salesman_2",
            name="Bob Sales",
            email="salesman2@example.com",
            password="Password@123",
            employeeidnum=2002,
            role=self.role_salesman,
            must_change_password=False,
        )

        # 6. Driver (non-salesman)
        self.driver = Employee.objects.create_user(
            username="driver_user",
            name="Charlie Driver",
            email="driver@example.com",
            password="Password@123",
            employeeidnum=3001,
            role=self.role_driver,
            must_change_password=False,
        )

        self.url = "/api/admin/tracking/visit/"

    def test_unauthenticated_forbidden(self):
        """Unauthenticated user receives 401 Unauthorized."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unauthorized_role_forbidden(self):
        """User without visit_manage receives 403 Forbidden."""
        self.client.force_authenticate(user=self.regular_manager)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.salesman1)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_access_allowed(self):
        """Owner receives 200 OK."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_visit_manage_role_access_allowed(self):
        """User with visit_manage=True receives 200 OK."""
        self.client.force_authenticate(user=self.manager_visit_admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_only_salesmen_in_results(self):
        """Only salesmen are returned; drivers, managers, owners are not listed."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data

        emp_ids = [item["employee_id"] for item in data["results"]]
        self.assertIn(self.salesman1.id, emp_ids)
        self.assertIn(self.salesman2.id, emp_ids)
        self.assertNotIn(self.driver.id, emp_ids)
        self.assertNotIn(self.owner.id, emp_ids)
        self.assertNotIn(self.regular_manager.id, emp_ids)
        self.assertEqual(data["total_salesmen"], 2)

    def test_visit_counting_and_filtering(self):
        """Tests visit counts for day, week, month, and date range."""
        self.client.force_authenticate(user=self.owner)
        today = timezone.localdate()

        # Create sample visits for salesman 1:
        # 2 visits today (1 dealer, 1 client)
        v1 = Visit.objects.create(
            employee=self.salesman1,
            type="Dealer",
            gps_image="visits/images/v1.jpg",
        )
        v2 = Visit.objects.create(
            employee=self.salesman1,
            type="Client",
            gps_image="visits/images/v2.jpg",
        )

        # 1 visit 5 days ago for salesman 1
        past_date = today - timedelta(days=5)
        v3 = Visit.objects.create(
            employee=self.salesman1,
            type="Dealer",
            gps_image="visits/images/v3.jpg",
        )
        # Update created_at to past_date
        Visit.objects.filter(id=v3.id).update(created_at=timezone.now() - timedelta(days=5))

        # 1 visit today for salesman 2 (dealer)
        v4 = Visit.objects.create(
            employee=self.salesman2,
            type="Dealer",
            gps_image="visits/images/v4.jpg",
        )

        # --- Test 1: Day wise (today by default) ---
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data
        self.assertEqual(data["filter_type"], "day")
        self.assertEqual(data["start_date"], str(today))
        self.assertEqual(data["end_date"], str(today))
        self.assertEqual(data["total_visits"], 3)  # v1, v2, v4
        self.assertEqual(data["total_dealer_visits"], 2)  # v1, v4
        self.assertEqual(data["total_client_visits"], 1)  # v2

        s1_res = next(r for r in data["results"] if r["employee_id"] == self.salesman1.id)
        self.assertEqual(s1_res["total_visits"], 2)
        self.assertEqual(s1_res["dealer_visits"], 1)
        self.assertEqual(s1_res["client_visits"], 1)

        s2_res = next(r for r in data["results"] if r["employee_id"] == self.salesman2.id)
        self.assertEqual(s2_res["total_visits"], 1)

        # --- Test 2: Date Range wise ---
        from_str = str(today - timedelta(days=7))
        to_str = str(today)
        res_range = self.client.get(f"{self.url}?from_date={from_str}&to_date={to_str}")
        self.assertEqual(res_range.status_code, status.HTTP_200_OK)
        range_data = res_range.data
        self.assertEqual(range_data["filter_type"], "custom_range")
        self.assertEqual(range_data["total_visits"], 4)  # v1, v2, v3, v4

        s1_range = next(r for r in range_data["results"] if r["employee_id"] == self.salesman1.id)
        self.assertEqual(s1_range["total_visits"], 3)

        # --- Test 3: Specific Salesman Filter ---
        res_single = self.client.get(f"{self.url}?employee_id={self.salesman1.id}")
        self.assertEqual(res_single.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_single.data["results"]), 1)
        self.assertEqual(res_single.data["results"][0]["employee_id"], self.salesman1.id)

        # --- Test 4: Invalid date format validation ---
        res_invalid = self.client.get(f"{self.url}?date=not-a-date")
        self.assertEqual(res_invalid.status_code, status.HTTP_400_BAD_REQUEST)

        # --- Test 6: Week filter ---
        res_week = self.client.get(f"{self.url}?period=week&date={str(today)}")
        self.assertEqual(res_week.status_code, status.HTTP_200_OK)
        self.assertEqual(res_week.data["filter_type"], "week")

        # --- Test 7: Month filter ---
        res_month = self.client.get(f"{self.url}?period=month&month={today.month}&year={today.year}")
        self.assertEqual(res_month.status_code, status.HTTP_200_OK)
        self.assertEqual(res_month.data["filter_type"], "month")

        # --- Test 8: Filter for non-salesman employee returns 400 ---
        res_driver = self.client.get(f"{self.url}?employee_id={self.driver.id}")
        self.assertEqual(res_driver.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not 'SALESMAN'", res_driver.data["error"])

        # --- Test 9: Unknown employee_id returns 404 ---
        res_unknown = self.client.get(f"{self.url}?employee_id={uuid.uuid4()}")
        self.assertEqual(res_unknown.status_code, status.HTTP_404_NOT_FOUND)

        # --- Test 10: JSON body payload extraction ---
        res_body = self.client.generic("GET", self.url, data='{"period": "month"}', content_type="application/json")
        self.assertEqual(res_body.status_code, status.HTTP_200_OK)
        self.assertEqual(res_body.data["filter_type"], "month")
