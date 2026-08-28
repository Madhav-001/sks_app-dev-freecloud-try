from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
import uuid


class EmployeeRole(models.Model):
    """
    Role-based access control table.
    One row per role (built-in or custom).
    The Owner can create new custom roles and toggle 9 permission groups per role.

    Hierarchy:
        hierarchy_level = 1  → Owner (highest authority)
        hierarchy_level = 2  → Senior Manager
        hierarchy_level = 3  → Manager
        hierarchy_level = 4  → SysAdmin
        hierarchy_level = 5  → Accountant
        hierarchy_level = 6  → Salesman / Employee / Watchman / Driver
        hierarchy_level = 99 → Default for new custom roles (lowest)

    Lower number = higher authority.
    A role may ONLY manage roles whose hierarchy_level is strictly GREATER
    than their own.  Never equal, never lower.
    """

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name         = models.CharField(max_length=50, unique=True, help_text="Internal key, e.g. 'MANAGER'")
    display_name = models.CharField(max_length=100, help_text="Human-readable label, e.g. 'Senior Manager'")
    is_builtin   = models.BooleanField(default=False, help_text="Built-in roles cannot be deleted.")

    # Hierarchy position — drives all access-control comparisons.
    # Owner = 1, Senior Manager = 2, ..., lowest workers = 6+.
    hierarchy_level = models.PositiveSmallIntegerField(
        default=99,
        help_text=(
            "Hierarchy rank. 1 = Owner (highest authority). "
            "Higher number = lower authority. "
            "A role can only manage roles whose level is strictly greater."
        ),
    )

    # 9 permission group toggles — True = role has manage-level access for that group
    employee_manage   = models.BooleanField(default=False)
    dealers_manage    = models.BooleanField(default=False)
    products_manage   = models.BooleanField(default=False)
    collection_manage = models.BooleanField(default=False)
    orders_manage     = models.BooleanField(default=False)
    attendance_manage = models.BooleanField(default=False)
    visit_manage      = models.BooleanField(default=False)
    leads_manage      = models.BooleanField(default=False)
    # Controls whether this role can view mileage data for ALL employees.
    # When False: the role can only see their own mileage (if any).
    # When True:  the role sees every employee's mileage records.
    # OWNER always has full mileage access regardless of this flag.
    milage_manage     = models.BooleanField(
        default=False,
        help_text="Allow this role to view mileage details of all employees.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Order by hierarchy_level so list APIs return roles top-to-bottom
        # (Owner first, lowest workers last).
        ordering = ['hierarchy_level', 'name']
        verbose_name = "Employee Role"
        verbose_name_plural = "Employee Roles"

    def __str__(self):
        return self.display_name


class Employee(AbstractUser):
    """
    Custom user model. `role` is a free-text field that matches EmployeeRole.name.
    Built-in role keys: OWNER, MANAGER, SYSADMIN, SALESMAN, ACCOUNTANT, DRIVER, WATCHMAN, EMPLOYEE.
    Owners can also create custom roles via the EmployeeRole table.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=255, default="")

    phone          = models.CharField(max_length=15)
    email          = models.EmailField(unique=True)
    address        = models.TextField()
    dob            = models.DateField(null=True, blank=True)
    date_of_join   = models.DateField(null=True, blank=True)
    blood_group    = models.CharField(max_length=10, blank=True)
    profile_picture= models.ImageField(upload_to='employee_profiles/', null=True, blank=True)
    house    = models.CharField(max_length=255, verbose_name="House No, House name, Road name", null=True, blank=True)
    street   = models.CharField(max_length=255, verbose_name="Village, Post Office, City", null=True, blank=True)
    district = models.CharField(max_length=255, verbose_name="District", null=True, blank=True)
    state    = models.CharField(max_length=255, verbose_name="State", null=True, blank=True)
    country  = models.CharField(max_length=255, verbose_name="Country", null=True, blank=True)
    pincode  = models.CharField(max_length=6, verbose_name="Pin code", null=True, blank=True)

    # Foreign key pointing to EmployeeRole (null for OWNER)
    role = models.ForeignKey(
        EmployeeRole,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
        verbose_name="Role",
        help_text="Foreign key referencing EmployeeRole (null for OWNER)."
    )

    @property
    def role_name(self):
        """String key of this employee's role. Always returns 'OWNER' for the superuser/null-role case."""
        if self.role:
            return self.role.name
        return "OWNER"

    # ------------------------------------------------------------------
    # Hierarchy helpers — centralised here so every app can use them
    # ------------------------------------------------------------------

    @property
    def is_owner(self):
        """
        True for:
        - Django superuser (is_superuser=True)
        - Superadmin account (employeeidnum=0)
        - Owner role (null role FK, role name 'OWNER', or hierarchy_level=1)
        """
        if self.is_superuser or getattr(self, 'employeeidnum', None) == 0 or self.role is None:
            return True
        if self.role:
            role_name = getattr(self.role, 'name', '') or ''
            if role_name.upper() == 'OWNER' or getattr(self.role, 'hierarchy_level', 99) == 1:
                return True
        return False

    @property
    def hierarchy_level(self):
        """
        Returns the integer hierarchy level of this employee's role.
        Owner = 1 (highest authority).  Larger number = lower authority.
        """
        if self.is_owner:
            return 1
        return getattr(self.role, 'hierarchy_level', 99)

    def can_manage(self, target_employee):
        """
        Returns True if this employee is authorised to create / edit / delete
        `target_employee` based on the role hierarchy.

        Rules:
          - Owner can manage everyone.
          - Any other role can ONLY manage employees whose hierarchy_level
            is strictly GREATER than their own.
          - No one can manage an equal or higher-ranked employee.
        """
        if self.is_owner:
            return True
        target_level = target_employee.hierarchy_level
        return self.hierarchy_level < target_level

    def can_manage_role(self, role_obj):
        """
        Returns True if this employee is authorised to assign `role_obj`
        to a new (or existing) employee.

        Rules:
          - Owner can assign any role.
          - role_obj=None means 'OWNER' role — only Owner may assign it.
          - Any other role can only assign roles whose hierarchy_level
            is strictly GREATER than their own.
        """
        if self.is_owner:
            return True
        if role_obj is None:
            # Assigning the Owner role (null FK) — only Owner may do this
            return False
        return self.hierarchy_level < role_obj.hierarchy_level



    must_change_password = models.BooleanField(default=True)

    date_of_leave = models.DateField(null=True, blank=True)
    is_deleted    = models.BooleanField(default=False)
    employeeidnum = models.IntegerField(unique=True, null=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ------------------------------------------------------------------
    # Single-superuser enforcement
    # ------------------------------------------------------------------

    def _superuser_already_exists(self):
        """Return True if a *different* employee is already the superuser."""
        return (
            Employee._base_manager
            .filter(is_superuser=True)
            .exclude(pk=self.pk)
            .exists()
        )

    def clean(self):
        """Called by Django admin forms — shows a friendly UI error."""
        super().clean()
        if self.is_superuser and self._superuser_already_exists():
            raise ValidationError(
                "Only one superuser is allowed in this application. "
                "Revoke the existing superuser first."
            )

    def save(self, *args, **kwargs):
        # Hard guard: also enforced outside admin (API, shell, management commands).
        if self.is_superuser and self._superuser_already_exists():
            raise ValidationError(
                "Only one superuser is allowed in this application. "
                "Revoke the existing superuser first."
            )

        if self.employeeidnum is None:
            if self.is_superuser:
                self.employeeidnum = 0
            else:
                existing_ids = set(
                    Employee._base_manager.values_list("employeeidnum", flat=True)
                )
                next_id = 1
                while next_id in existing_ids:
                    next_id += 1
                self.employeeidnum = next_id

        super().save(*args, **kwargs)

    def __str__(self):
        return self.username


class LoginHistory(models.Model):
    employee   = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="login_history")
    login_at   = models.DateTimeField(auto_now_add=True)
    logout_at  = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    status     = models.CharField(
        max_length=20,
        choices=[("active", "Active"), ("inactive", "Inactive")],
        default="active",
    )

    class Meta:
        ordering = ["-login_at"]
        verbose_name_plural = "Login Histories"

    def __str__(self):
        return f"{self.employee.username} logged in at {self.login_at}"
