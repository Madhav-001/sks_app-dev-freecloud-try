---
trigger: always_on
glob:
description: Access control rules, hierarchy authority, and permission policies for SKS Backend
---

# SKS Backend Access Control Rules

Whenever implementing, modifying, or testing API endpoints, serializers, querysets, or permissions, ALWAYS strictly enforce the following access control policies:

1. **Hierarchy Authority (`hierarchy_level`)**:
   - Hierarchy rank is an integer: **Lower Number = Strictly Higher Authority**.
   - Built-in ranks: `OWNER` (1), `SENIOR_MANAGER` (2), `MANAGER` (3), `SYSADMIN` (4), `ACCOUNTANT` (5), `SALESMAN` / `EMPLOYEE` / `WATCHMAN` / `DRIVER` (6), Custom Roles (99).
   - `ADMIN_MAX_LEVEL = 5`: Roles with `hierarchy_level <= 5` are admin-portal staff. Roles with level > 5 are field/operational staff.
   - Hierarchy comparisons use strict inequality: `requester.hierarchy_level < target.hierarchy_level`. An employee can NEVER manage, edit, delete, or reset passwords of someone ranked equal to or higher than themselves.
   - When assigning a role to an employee, the requester may ONLY assign roles where `target_role.hierarchy_level > requester.hierarchy_level`.

2. **Single Superuser / Owner Exclusivity**:
   - Only ONE superuser exists (`employeeidnum=0` or `is_superuser=True`).
   - Owner bypasses permission flags (`user.is_owner == True`).
   - The `OWNER` role row in `EmployeeRole` is immutable: it cannot be modified or deleted.

3. **Mandatory Password Change Enforcement**:
   - `MustChangePasswordPermission` is part of DRF default permissions.
   - Any user with `must_change_password=True` is blocked from all endpoints (HTTP 403) except `ChangePasswordView`.

4. **The 9 Modular Permission Flags**:
   - Modules (`employee_manage`, `dealers_manage`, `products_manage`, `orders_manage`, `collection_manage`, `attendance_manage`, `visit_manage`, `leads_manage`, `milage_manage`) must be checked on mutating actions via `RoleBasedPermission` or module helpers.
   - Target Management (`IsTargetAdmin`) requires Owner OR at least one of `orders_manage`, `collection_manage`, `visit_manage`.

5. **Data Scoping, Object Ownership & Superior Data Protection**:
   - **Universal Hierarchy Constraint**: Every employee can **ONLY** access details/records of **equivalent and lower-level employees** (`target.hierarchy_level >= requester.hierarchy_level`). Access to any **higher-level employee's data** (`target.hierarchy_level < requester.hierarchy_level`) is **STRICTLY FORBIDDEN** across all endpoints (HTTP 403 Forbidden).
   - In **Attendance** (`/api/admin/tracking/attendance/date/`), non-owners only see attendance of equivalent and lower-level employees; superiors are strictly excluded from lists and summary counts. In monthly attendance (`<user_id>`), viewing superiors returns HTTP 403 Forbidden.
   - In **Mileage** and **SOD/EOD**, non-owners cannot view mileage or reports of higher-ranked employees.
   - In **Orders** and **Collections**, admins cannot view orders/collections of superiors.
   - Non-admin staff (field workers) must NEVER see other employees' data (orders, collections, visits, leads, mileage) unless explicitly permitted (e.g., shared notes).
   - In employee listing (`/api/auth/list/`), non-owners only see users with `role__hierarchy_level >= requester.hierarchy_level` (never superiors).
   - Delivered orders are permanently locked against any status change.

6. **Soft vs Hard Deletion**:
   - Superuser (`employeeidnum=0`, `is_superuser=True`) performs hard deletion.
   - All other staff perform soft deletion (`is_deleted=True`). Active queries must filter `is_deleted=False`.

For the complete endpoint-by-endpoint matrix and architectural documentation, refer to [access.md](file:///d:/Mady/program/git/Anbu_anna/SKS_BE/sks_app-dev-freecloud%20try/access.md).
