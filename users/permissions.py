"""
users/permissions.py
====================
Centralised, hierarchy-based access-control for the entire application.

Architecture
------------
All role comparisons go through Employee.hierarchy_level or Employee.can_manage()
rather than hardcoded role-name lists.  The only place where "OWNER" is
referenced by name is in `is_admin_of()` as a fallback for historical callers;
the real check is always the level integer.

Public surface
--------------
Permission classes (for permission_classes=[...]):
    IsOwner
    IsAdminUser
    IsAdminManagerOrOwner     (kept for backward compat — same as IsAdminUser)
    CanCreateEmployee
    MustChangePasswordPermission
    IsOwnerOrOrdersManage
    IsOwnerOrCollectionManage
    RoleBasedPermission

Helper functions (importable by any view/serializer):
    is_admin_of(requester, target_employee=None)
    has_orders_manage_permission(user)
    has_collection_manage_permission(user)
"""

from rest_framework import permissions


# ---------------------------------------------------------------------------
# Constants — kept only for documentation; logic uses hierarchy_level, not names
# ---------------------------------------------------------------------------

# Admin-portal level: any role with hierarchy_level <= ADMIN_MAX_LEVEL is an admin
ADMIN_MAX_LEVEL = 5   # Owner(1) … Accountant(5)


# ---------------------------------------------------------------------------
# Module-level helpers — importable by all apps
# ---------------------------------------------------------------------------

def is_admin_of(requester, target_employee=None):
    """
    Returns True when `requester` has admin-level authority.

    If `target_employee` is provided the check is hierarchy-aware:
        requester.can_manage(target_employee) must be True.

    If no target is provided the check is a general "is this user an admin":
        hierarchy_level <= ADMIN_MAX_LEVEL  (Owner … Accountant)

    Always returns True for Owner / superuser.
    """
    if not requester or not requester.is_authenticated:
        return False
    if requester.is_owner:
        return True
    if target_employee is not None:
        return requester.can_manage(target_employee)
    return requester.hierarchy_level <= ADMIN_MAX_LEVEL


def has_orders_manage_permission(user):
    """True if user is Owner/superuser or has orders_manage=True in EmployeeRole."""
    if not user or not user.is_authenticated:
        return False
    if user.is_owner:
        return True
    return bool(user.role and user.role.orders_manage)


def has_collection_manage_permission(user):
    """True if user is Owner/superuser or has collection_manage=True in EmployeeRole."""
    if not user or not user.is_authenticated:
        return False
    if user.is_owner:
        return True
    return bool(user.role and user.role.collection_manage)


# ---------------------------------------------------------------------------
# Permission classes
# ---------------------------------------------------------------------------

class MustChangePasswordPermission(permissions.BasePermission):
    """
    Blocks all API access if the user must change their password first.
    The change-password endpoint itself is always allowed.
    """
    message = "Password change required. Please change your temporary password to access this API."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return True  # Let other permissions handle authentication

        # Always allow access to the change-password endpoint itself
        if view.__class__.__name__ == "ChangePasswordView":
            return True

        if request.user.must_change_password:
            return False

        return True


class IsOwner(permissions.BasePermission):
    """
    Allows access only to the Owner role or Django superuser.
    Used for role CRUD (POST/PATCH/DELETE /api/auth/roles/).
    """
    message = "Only an Owner or Superuser has access to this resource."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.is_owner


class IsAdminUser(permissions.BasePermission):
    """
    Permits any user whose hierarchy_level is <= ADMIN_MAX_LEVEL.
    That includes: Owner, Senior Manager, Manager, SysAdmin, Accountant.
    Denies: Salesman, Employee, Watchman, Driver.
    """
    message = "Access denied. This action is for admin staff only."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.hierarchy_level <= ADMIN_MAX_LEVEL


# Backward-compatible alias (older views reference IsAdminManagerOrOwner)
IsAdminManagerOrOwner = IsAdminUser


class CanCreateEmployee(permissions.BasePermission):
    """
    Allows any user with hierarchy_level <= ADMIN_MAX_LEVEL to reach the
    employee-create view.  The role-assignment validity (can the requester
    actually assign the chosen role?) is enforced in the serializer's
    validate() method via Employee.can_manage_role().
    """
    message = "Only admin-level staff can create employee accounts."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.hierarchy_level <= ADMIN_MAX_LEVEL


class IsOwnerOrOrdersManage(permissions.BasePermission):
    """
    Allows access only to Owner/superuser or roles with orders_manage=True.
    """
    message = "You do not have permission to perform this action. Contact your administrator."

    def has_permission(self, request, view):
        return has_orders_manage_permission(request.user)


class IsOwnerOrCollectionManage(permissions.BasePermission):
    """
    Allows access only to Owner/superuser or roles with collection_manage=True.
    """
    message = "You do not have permission to perform this action. Contact your administrator."

    def has_permission(self, request, view):
        return has_collection_manage_permission(request.user)


# ---------------------------------------------------------------------------
# RoleBasedPermission — dynamic per-view dispatcher
# ---------------------------------------------------------------------------

class RoleBasedPermission(permissions.BasePermission):
    """
    Hierarchy-aware permission enforcer used across multiple viewsets.

    The dispatcher works as follows:
    1. Owner / superuser → always permitted.
    2. Per-view / per-action allow-lists for "all authenticated employees".
    3. For mutating actions, delegates to the relevant permission flag on
       the employee's EmployeeRole row.
    4. Unknown views fall through to True (unknown = not yet covered, not blocked).
    """
    message = "You do not have permission to perform this action. Contact your administrator."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        # Owner always passes
        if user.is_owner:
            return True

        view_name = view.__class__.__name__
        action    = getattr(view, "action", None)

        # ── Views where ALL authenticated employees may operate ──────────

        # Orders & Collections: all authenticated users may list/create/retrieve/patch
        # (ownership scoping is enforced in get_queryset / _check_ownership)
        if view_name == "OrderViewSet":
            return True
        if view_name == "CollectionViewSet":
            return True

        # Leads: all authenticated employees may create; list/retrieve
        # are allowed here — queryset scoping (own-only for non-admins)
        # is handled inside LeadViewSet.get_queryset() and get_object().
        if view_name == "LeadViewSet" and action in ("create", "list", "retrieve"):
            return True

        # Attendance check-in / check-out / status / km-report: all employees
        if view_name == "AttendanceViewSet" and action in (
            "start", "end", "attendance_status", "employee_monthly_attendance", "km_report"
        ):
            return True

        # Attendance retrieve: all authenticated (ownership check is in the view)
        if view_name == "AttendanceViewSet" and action == "retrieve":
            return True

        # Visits: create / bulk-sync / retrieve_visit_detail / partial_update_visit: all
        if view_name == "VisitViewSet" and action in (
            "create_visit", "bulk_sync", "list", "retrieve_visit_detail", "partial_update_visit",
            "retrieve_dealer",
        ):
            return True

        # Mileage summary: all authenticated (ownership scoped in view)
        if view_name == "MilageViewSet":
            return True

        # ── Safe-method fallback for views not already handled ───────────
        if request.method in permissions.SAFE_METHODS:
            return True

        # ── Mutating actions — require specific permission flags ─────────
        rp = getattr(user, 'role', None)
        if rp is None:
            self.message = (
                f"No permission configuration found for user '{user.username}'. "
                "Please contact your administrator."
            )
            return False

        # 1. Employee management
        if view_name in ("EmployeeCreateView", "EmployeeDetailView", "AdminResetEmployeePasswordView"):
            return rp.employee_manage

        # 2. Dealers — PATCH / DELETE
        if view_name in ("SubDealerListCreateView", "SubDealerUpdateView"):
            return rp.dealers_manage

        # 3. Products — POST / PATCH
        if view_name == "ProductViewSet":
            return rp.products_manage

        # 4. Collections — admin approve/edit
        if view_name == "CollectionViewSet":
            return rp.collection_manage

        # 5. Orders — admin approve/edit
        if view_name == "OrderViewSet":
            return rp.orders_manage

        # 6. Attendance — admin mutations
        if view_name == "AttendanceViewSet":
            return rp.attendance_manage

        # 7. Visits — admin mutations
        if view_name == "VisitViewSet":
            return rp.visit_manage

        # 8. Leads — admin actions (PATCH / DELETE / convert)
        if view_name == "LeadViewSet":
            return rp.leads_manage

        # Default: allow (unknown view not yet covered; keeps non-listed views unblocked)
        return True
