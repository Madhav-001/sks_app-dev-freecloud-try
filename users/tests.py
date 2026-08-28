from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from users.models import Employee, EmployeeRole


class EmployeeListFilterTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.role_manager, _ = EmployeeRole.objects.get_or_create(
            name="MANAGER",
            defaults={"display_name": "Manager", "hierarchy_level": 3, "employee_manage": True},
        )
        self.role_salesman, _ = EmployeeRole.objects.get_or_create(
            name="SALESMAN",
            defaults={"display_name": "Sales Executive", "hierarchy_level": 6},
        )

        # Authenticated requesting user
        self.auth_user = Employee.objects.create_user(
            username="testauth",
            email="auth@example.com",
            password="Password@123",
            employeeidnum=1,
            role=self.role_manager,
            is_active=True,
            is_deleted=False,
        )
        self.client.force_authenticate(user=self.auth_user)

        # Active non-deleted employee
        self.emp_active = Employee.objects.create_user(
            username="emp_active",
            email="active@example.com",
            password="Password@123",
            employeeidnum=2,
            role=self.role_salesman,
            is_active=True,
            is_deleted=False,
        )

        # Inactive non-deleted employee
        self.emp_inactive = Employee.objects.create_user(
            username="emp_inactive",
            email="inactive@example.com",
            password="Password@123",
            employeeidnum=3,
            role=self.role_salesman,
            is_active=False,
            is_deleted=False,
        )

        # Soft-deleted active employee
        self.emp_deleted_active = Employee.objects.create_user(
            username="emp_deleted_active",
            email="deleted_active@example.com",
            password="Password@123",
            employeeidnum=4,
            role=self.role_salesman,
            is_active=True,
            is_deleted=True,
        )

        # Soft-deleted inactive employee
        self.emp_deleted_inactive = Employee.objects.create_user(
            username="emp_deleted_inactive",
            email="deleted_inactive@example.com",
            password="Password@123",
            employeeidnum=5,
            role=self.role_manager,
            is_active=False,
            is_deleted=True,
        )

        self.list_url = reverse("employee-list")

    def test_default_list_returns_non_deleted_employees(self):
        """Default request returns all non-deleted employees (active & inactive)."""
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data if isinstance(response.data, list) else response.data.get("results", [])
        usernames = [e["username"] for e in results]

        self.assertIn("testauth", usernames)
        self.assertIn("emp_active", usernames)
        self.assertIn("emp_inactive", usernames)
        self.assertNotIn("emp_deleted_active", usernames)
        self.assertNotIn("emp_deleted_inactive", usernames)

    def test_filter_is_active_true(self):
        """is_active=true returns only active, non-deleted employees."""
        response = self.client.get(self.list_url, {"is_active": "true"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data if isinstance(response.data, list) else response.data.get("results", [])
        usernames = [e["username"] for e in results]

        self.assertIn("testauth", usernames)
        self.assertIn("emp_active", usernames)
        self.assertNotIn("emp_inactive", usernames)
        self.assertNotIn("emp_deleted_active", usernames)

    def test_filter_is_active_false(self):
        """is_active=false returns only inactive, non-deleted employees."""
        response = self.client.get(self.list_url, {"is_active": "false"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data if isinstance(response.data, list) else response.data.get("results", [])
        usernames = [e["username"] for e in results]

        self.assertIn("emp_inactive", usernames)
        self.assertNotIn("emp_active", usernames)
        self.assertNotIn("testauth", usernames)
        self.assertNotIn("emp_deleted_inactive", usernames)

    def test_filter_is_deleted_true(self):
        """is_deleted=true returns only deleted employees."""
        response = self.client.get(self.list_url, {"is_deleted": "true"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data if isinstance(response.data, list) else response.data.get("results", [])
        usernames = [e["username"] for e in results]

        self.assertIn("emp_deleted_active", usernames)
        self.assertIn("emp_deleted_inactive", usernames)
        self.assertNotIn("emp_active", usernames)
        self.assertNotIn("emp_inactive", usernames)

    def test_filter_is_deleted_all(self):
        """is_deleted=all returns both deleted and non-deleted employees."""
        response = self.client.get(self.list_url, {"is_deleted": "all"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data if isinstance(response.data, list) else response.data.get("results", [])
        usernames = [e["username"] for e in results]

        self.assertIn("testauth", usernames)
        self.assertIn("emp_active", usernames)
        self.assertIn("emp_inactive", usernames)
        self.assertIn("emp_deleted_active", usernames)
        self.assertIn("emp_deleted_inactive", usernames)

    def test_status_shortcut_active(self):
        """status=active returns is_active=True and is_deleted=False."""
        response = self.client.get(self.list_url, {"status": "active"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data if isinstance(response.data, list) else response.data.get("results", [])
        usernames = [e["username"] for e in results]

        self.assertIn("emp_active", usernames)
        self.assertIn("testauth", usernames)
        self.assertNotIn("emp_inactive", usernames)
        self.assertNotIn("emp_deleted_active", usernames)

    def test_status_shortcut_inactive(self):
        """status=inactive returns is_active=False and is_deleted=False."""
        response = self.client.get(self.list_url, {"status": "inactive"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data if isinstance(response.data, list) else response.data.get("results", [])
        usernames = [e["username"] for e in results]

        self.assertIn("emp_inactive", usernames)
        self.assertNotIn("emp_active", usernames)
        self.assertNotIn("emp_deleted_inactive", usernames)

    def test_status_shortcut_deleted(self):
        """status=deleted returns is_deleted=True."""
        response = self.client.get(self.list_url, {"status": "deleted"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data if isinstance(response.data, list) else response.data.get("results", [])
        usernames = [e["username"] for e in results]

        self.assertIn("emp_deleted_active", usernames)
        self.assertIn("emp_deleted_inactive", usernames)
        self.assertNotIn("emp_active", usernames)

    def test_status_shortcut_all(self):
        """status=all returns all employees."""
        response = self.client.get(self.list_url, {"status": "all"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data if isinstance(response.data, list) else response.data.get("results", [])
        self.assertEqual(len(results), 5)

    def test_serializer_includes_is_active_and_is_deleted(self):
        """Check that is_active and is_deleted are present in the response object."""
        response = self.client.get(self.list_url)
        results = response.data if isinstance(response.data, list) else response.data.get("results", [])
        first_emp = results[0]
        self.assertIn("is_active", first_emp)
        self.assertIn("is_deleted", first_emp)
