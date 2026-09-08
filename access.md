# SKS Backend Access Control & Permission Architecture Documentation

This document provides a comprehensive specification of the access control system, role hierarchy, permission matrix, and endpoint-level security rules implemented in the SKS Backend (`sks_app-dev-freecloud try`).

---

## Table of Contents
1. [Core Security Principles & Authentication](#1-core-security-principles--authentication)
2. [Role Hierarchy Architecture (`hierarchy_level`)](#2-role-hierarchy-architecture-hierarchy_level)
3. [Granular Permission Flags (The 9 Modules)](#3-granular-permission-flags-the-9-modules)
4. [Built-in Roles & Default Permission Matrix](#4-built-in-roles--default-permission-matrix)
5. [Permission Classes & Helper Functions Reference](#5-permission-classes--helper-functions-reference)
6. [Data Scoping & Object-Level Permissions](#6-data-scoping--object-level-permissions)
7. [Comprehensive Endpoint Access Control Matrix](#7-comprehensive-endpoint-access-control-matrix)
8. [Admin Portal vs Field Worker Capabilities](#8-admin-portal-vs-field-worker-capabilities)
9. [Soft Delete vs Hard Delete Rules](#9-soft-delete-vs-hard-delete-rules)

---

## 1. Core Security Principles & Authentication

### 1.1 Authentication & Tokens
- **Transport & Format**: All requests (except login/refresh) require `Authorization: Bearer <access_token>`.
- **JWT Framework**: Implemented using `rest_framework_simplejwt`.
- **Token Lifetimes**:
  - `ACCESS_TOKEN_LIFETIME`: **3 Hours**
  - `REFRESH_TOKEN_LIFETIME`: **30 Days**
  - Algorithm: `HS256`
- **Session Tracking (`LoginHistory`)**:
  - Each login creates a `LoginHistory` record (`active` status).
  - Logout (`POST /api/auth/logout/`) blacklists the refresh token and sets `status = 'inactive'`, timestamping `logout_at`.

### 1.2 Mandatory Password Change (`MustChangePasswordPermission`)
- Integrated into `REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]`.
- Applies globally to all authenticated requests:
  - If `employee.must_change_password == True` (default on account creation or after an admin password reset), all API access is blocked with HTTP `403 Forbidden` (`"Password change required..."`).
  - The single exception is `ChangePasswordView` (`POST /api/auth/change-password/`), allowing users to update their password and clear the flag.

### 1.3 Single Superuser / Owner Invariant
- Identified by any of the following:
  - `employee.is_superuser == True`
  - `employee.employeeidnum == 0`
  - `employee.role is None`
  - `employee.role.name == "OWNER"`
  - `employee.role.hierarchy_level == 1`
- Only **one superuser account** is allowed in the database (`_superuser_already_exists` check in `Employee.clean()`).
- Owner bypasses all permission flag checks (`is_owner` property returns `True`).
- The `OWNER` role row in `EmployeeRole` is protected:
  - It cannot be modified (`PATCH /api/auth/roles/<id>/` returns HTTP `403 Forbidden`).
  - It cannot be deleted (`DELETE /api/auth/roles/<id>/` returns HTTP `403 Forbidden`).

---

## 2. Role Hierarchy Architecture (`hierarchy_level`)

### 2.1 The Hierarchy Rule
Authority is driven by an integer rank: **Lower Number = Strictly Higher Authority**.
- **Owner rank**: `1` (supreme authority).
- **Lowest default rank**: `99` (custom unranked roles).

```
Level 1: OWNER (Superuser)
   │
Level 2: SENIOR MANAGER
   │
Level 3: MANAGER
   │
Level 4: SYSADMIN
   │
Level 5: ACCOUNTANT
─────────────────────────── ADMIN_MAX_LEVEL = 5 (Admin Portal Threshold)
Level 6: SALESMAN / DRIVER / WATCHMAN / EMPLOYEE (Field Staff / Workers)
   │
Level 99: Custom Roles (Default)
```

### 2.2 Hierarchy Comparison Methods
1. **`Employee.can_manage(target_employee)`**:
   - Owner can manage all employees.
   - Any other role can **ONLY** manage employees whose `hierarchy_level` is **strictly greater** than their own (`self.hierarchy_level < target_employee.hierarchy_level`).
   - A manager **CANNOT** edit, delete, view detail, or reset passwords of peers (equal level) or superiors (lower level).

2. **`Employee.can_manage_role(role_obj)`**:
   - Enforced during employee creation (`CreateEmployeeSerializer.validate()`).
   - Owner can assign any role (including `OWNER`).
   - Requesters can only assign roles whose `hierarchy_level` is **strictly greater** than their own.
   - Non-owners can never create an Owner (`role_obj=None` or level 1).

### 2.3 Admin Portal Level Threshold (`ADMIN_MAX_LEVEL = 5`)
- Defined in `users/permissions.py`.
- Roles with `hierarchy_level <= 5` (Owner, Senior Manager, Manager, SysAdmin, Accountant) are classified as **Admin Staff**:
  - Authorized to access the admin portal and role definitions (`GET /api/auth/roles/`).
  - Permitted to access `EmployeeCreateView`.
- Roles with `hierarchy_level > 5` (Salesman, Employee, Driver, Watchman) are field/operational workers and blocked from management interfaces.

### 2.4 Universal Authority & Data Access Constraint
**Core Security Invariant**:
- Every employee can **ONLY** access details and records of **equivalent and lower-level employees** (`target.hierarchy_level >= requester.hierarchy_level`).
- Access to any **higher-level employee's data** (`target.hierarchy_level < requester.hierarchy_level`) is **STRICTLY FORBIDDEN** across all endpoints (HTTP `403 Forbidden`).
- For **mutating actions** (`PATCH`, `DELETE`, password resets, status overrides): The requester must **strictly outrank** the target (`requester.hierarchy_level < target.hierarchy_level`). No employee can edit or delete a peer (equal level) or superior (higher level).

---

## 3. Granular Permission Flags (The 9 Modules)

In addition to hierarchy rank, `EmployeeRole` features 9 independent boolean flags that govern operational modules:

| # | Permission Field | Managed Module | Actions Governed When `True` |
|---|---|---|---|
| 1 | `employee_manage` | Employees | Create employees, update profiles, soft-delete employees, and trigger admin password resets. |
| 2 | `dealers_manage` | Sub-Dealers | Update sub-dealer details (`PATCH`), delete dealers (`DELETE`), and reassign dealer to a different employee. |
| 3 | `products_manage` | Product Catalog | Create products (`POST`) and update product info, pricing, or catalog images (`PATCH`). |
| 4 | `orders_manage` | Orders & Analytics | Approve/reject orders, transition order lifecycle statuses, and view all-employee sales analytics. |
| 5 | `collection_manage` | Collections | Approve payment collections, verify bank/cash payments, and trigger order payment reconciliation. |
| 6 | `attendance_manage` | Attendance | Admin updates to attendance records and verification of work hours. |
| 7 | `visit_manage` | Visits | Access salesman visit count metrics and overview reports (`/api/admin/tracking/visit/`). |
| 8 | `leads_manage` | CRM Leads | Edit leads (`PATCH`), delete leads (`DELETE`), and convert leads into Customers or SubDealers. |
| 9 | `milage_manage` | Mileage & GPS | View all-employee daily mileage reports and per-employee infinite-scroll mileage logs. |

---

## 4. Permission Classes & Helper Functions Reference

### 4.1 Helper Functions (`users/permissions.py`)
- **`is_admin_of(requester, target_employee=None)`**:
  - Returns `True` if requester is Owner/superuser.
  - If `target_employee` is supplied: returns `requester.can_manage(target_employee)`.
  - If no target supplied: returns `requester.hierarchy_level <= 5` (Owner ... Accountant).
- **`has_orders_manage_permission(user)`**: `True` if Owner or `user.role.orders_manage == True`.
- **`has_collection_manage_permission(user)`**: `True` if Owner or `user.role.collection_manage == True`.
- **`has_visit_manage_permission(user)`**: `True` if Owner or `user.role.visit_manage == True`.
- **`has_any_target_manage_permission(user)`**: `True` if Owner or at least one of `orders_manage`, `collection_manage`, or `visit_manage` is `True`.

### 4.2 DRF Permission Classes
- **`MustChangePasswordPermission`**: Enforces mandatory password change before accessing any protected endpoint.
- **`IsOwner`**: Restricts access exclusively to Owner/superuser (`request.user.is_owner`).
- **`IsAdminUser` / `IsAdminManagerOrOwner`**: Restricts to `hierarchy_level <= 5`.
- **`CanCreateEmployee`**: Allows `hierarchy_level <= 5` to reach employee creation; role target checked via serializer.
- **`IsOwnerOrOrdersManage`**: Restricts to Owner or roles with `orders_manage=True`.
- **`IsOwnerOrCollectionManage`**: Restricts to Owner or roles with `collection_manage=True`.
- **`IsOwnerOrVisitManage`**: Restricts to Owner or roles with `visit_manage=True`.
- **`IsTargetAdmin`**: Restricts to Owner or roles with at least one target manage flag.
- **`RoleBasedPermission`**: Dynamic per-view dispatcher that routes action requests to corresponding `EmployeeRole` boolean flags for mutating actions while permitting read actions to authenticated employees.

---

## 5. Data Scoping & Object-Level Permissions

### 5.1 Employee Scoping (`GET /api/auth/list/`)
- **Owner**: Sees all registered employees.
- **Non-Owner**: Filtered by `role__hierarchy_level__gte = requester.hierarchy_level`. Can see users of equal and lower authority, but never superiors.

### 5.2 Orders Scoping (`OrderViewSet`)
- **Admins** (`hierarchy_level <= 5`): Can view all orders across the organization and filter by `employee_id`.
- **Field Staff**: Can only view orders where `order.employee == request.user`. Filter parameters for other employees are ignored.
- **Delivery Lock Invariant**: Once an order status is `delivered`, it is permanently locked. No updates (`PATCH`) are allowed by anyone, including Admins.

### 5.3 Collections Scoping (`CollectionViewSet`)
- **Admins**: Can view all collections and filter by `employee_id` or `sub_dealer`.
- **Field Staff**: Queryset strictly filtered to `collection.employee == request.user`.

### 5.4 Sub-Dealers Scoping (`SubDealerListCreateView`)
- **Admins**: Can view all dealers and reassign dealer `employee`.
- **Field Staff**: Can only view dealers assigned to them (`dealer.employee == request.user`). Cannot reassign the `employee` field.

### 5.5 Leads Scoping (`LeadViewSet`)
- **Admins**: Can view all leads across all staff members.
- **Field Staff**: Can only view leads where `lead.employee == request.user`.

### 5.6 Mileage Scoping (`MilageViewSet`, `AdminDailyMilageView`, `AdminEmployeeMilageSummaryView`)
- **Employees without `milage_manage`**: Can only view their own mileage (`target_employee = request.user`). Querying another employee returns HTTP `403 Forbidden`.
- **Roles with `milage_manage=True`**:
  - `daily_milage` (`GET /api/admin/tracking/milage/<date>/`): Non-owners ONLY see mileage records for employees with `role__hierarchy_level >= requester.hierarchy_level`. Superiors are filtered out.
  - `employee_milage_summary` (`GET /api/admin/tracking/milage/summary/<user_id>/`): Non-owners can only view history for employees with `target.hierarchy_level >= requester.hierarchy_level`. Attempting to view a superior returns HTTP `403 Forbidden`.
  - `milage_summary` (`GET /api/tracking/milage/summary/?employee_id=<uuid>`): Non-owners querying another employee's mileage cannot view superiors (HTTP `403 Forbidden`).
- **Owner**: Full unrestricted visibility of all employees' mileage.

### 5.7 Notes & Messages Scoping
- **Notes (`NoteViewSet`)**:
  - Active notes are visible to the creator (`employee == user`) and shared users (`shared_to == user`).
  - Edit/Delete permissions restricted strictly to the creator (`IsNoteOwnerOrReadOnly`).
  - Soft-deleted notes are visible only to the creator (in bin) and purged after 30 days.
- **Messages (`MessageViewSet`)**:
  - Filtered to `sender == user | receiver == user`.

### 5.8 Attendance & Daily Reports Scoping (`AttendanceViewSet`, SOD/EOD)
- **Daily Attendance Breakdown (`GET /api/admin/tracking/attendance/date/`)**:
  - Non-owners ONLY see attendance and absent entries for employees with `role__hierarchy_level >= requester.hierarchy_level` (peers and subordinates).
  - Superior employees (Owner, Senior Managers, or any role ranked higher than requester) are **completely excluded** from `checked_in`, `checked_out`, `absent`, and the summary counts (`total_employees`, etc.).
- **Monthly Attendance Details (`GET /api/admin/tracking/attendance/<user_id>/`)**:
  - Non-owners can only view monthly records for employees where `target.hierarchy_level >= requester.hierarchy_level`.
  - Attempting to view attendance for a higher-level employee returns HTTP `403 Forbidden`.
- **Single Record Retrieve (`GET /api/tracking/attendance/<pk>/`)**:
  - Non-owners can only view their own attendance record or (if admin) records belonging to equivalent or lower-level employees. Viewing a superior's record returns HTTP `403 Forbidden`.
- **Attendance Record Edit (`PATCH /api/tracking/attendance/<pk>/`)**:
  - Mutating an attendance record requires `requester.can_manage(target_employee)`. An employee can **never** edit attendance of a peer or superior (HTTP `403 Forbidden`).
- **SOD & EOD Reports (`/api/admin/tracking/sod/<id>/`, `/api/admin/tracking/eod/<id>/`)**:
  - Admins can only view SOD and EOD reports for equivalent or lower-level employees (`target.hierarchy_level >= requester.hierarchy_level`). Superiors' reports return HTTP `403 Forbidden`.

---

## 6. Comprehensive Endpoint Access Control Matrix

| Method | Endpoint | Primary Permission Class | Access Level / Constraints |
|:---|:---|:---|:---|
| **AUTH & USER MANAGEMENT** |
| `POST` | `/api/auth/login/` | `AllowAny` | Public token generation. |
| `POST` | `/api/auth/token/refresh/` | `AllowAny` | Refresh expired access token. |
| `POST` | `/api/auth/logout/` | `IsAuthenticated` | Blacklists token, updates `LoginHistory`. |
| `GET` | `/api/auth/login-history/` | `IsAuthenticated` | Scoped to authenticated employee's history. |
| `GET` | `/api/auth/profile/` | `IsAuthenticated` | Returns authenticated user's profile. |
| `POST` | `/api/auth/change-password/` | `IsAuthenticated` | Bypasses `must_change_password` check. |
| `GET` | `/api/auth/list/` | `IsAuthenticated` | Scoped by hierarchy: cannot see superiors. |
| `POST` | `/api/auth/create/` | `CanCreateEmployee` + `RoleBasedPermission` | `level <= 5` & `employee_manage=True`. Cannot assign equal or superior role. |
| `GET` | `/api/auth/<id>/` | `IsAdminManagerOrOwner` + `RoleBasedPermission` | Blocked if target outranks requester. |
| `PATCH` | `/api/auth/<id>/` | `IsAdminManagerOrOwner` + `RoleBasedPermission` | Requires `can_manage(target)` (strictly outranks target). |
| `DELETE`| `/api/auth/<id>/` | `IsAdminManagerOrOwner` + `RoleBasedPermission` | Soft-deletes. Requires `can_manage(target)`. |
| `POST` | `/api/auth/<id>/reset-password/` | `IsAdminManagerOrOwner` + `RoleBasedPermission` | Requires `can_manage(target)`. Sets `must_change_password=True`. |
| `GET` | `/api/auth/roles/` | `IsAdminUser` | Staff with `hierarchy_level <= 5` only. |
| `POST` | `/api/auth/roles/` | `IsOwner` | Owner / Superuser only. |
| `GET` | `/api/auth/roles/<id>/` | `IsAuthenticated` | Any authenticated employee. |
| `PATCH` | `/api/auth/roles/<id>/` | `IsOwner` | Owner only. `OWNER` role is protected from edit. |
| `DELETE`| `/api/auth/roles/<id>/` | `IsOwner` | Owner only. Built-in roles and assigned roles cannot be deleted. |
| **DEALERS** |
| `GET` | `/api/dealers/` | `IsAuthenticated` + `RoleBasedPermission` | Admins see all; Salesmen see assigned dealers. |
| `POST` | `/api/dealers/` | `IsAuthenticated` + `RoleBasedPermission` | Any authenticated employee. |
| `GET` | `/api/dealers/<id>/` | `IsAuthenticated` + `RoleBasedPermission` | Admin or assigned employee only. |
| `PATCH` | `/api/dealers/<id>/` | `IsAuthenticated` + `RoleBasedPermission` | Admin or assigned employee. Changing `employee` requires Admin. |
| `DELETE`| `/api/dealers/<id>/` | `IsAuthenticated` + `RoleBasedPermission` | Soft-delete. Admins with `dealers_manage=True` only. |
| **PRODUCTS** |
| `GET` | `/api/sales/products/` | `IsAuthenticated` | All authenticated employees. |
| `POST` | `/api/sales/products/` | `RoleBasedPermission` | Owner or roles with `products_manage=True`. |
| `PATCH` | `/api/sales/products/<id>/` | `RoleBasedPermission` | Owner or roles with `products_manage=True`. |
| **ORDERS** |
| `GET` | `/api/sales/orders/` | `IsAuthenticated` + `RoleBasedPermission` | Admins see all; Salesmen see own orders. |
| `POST` | `/api/sales/orders/` | `IsAuthenticated` + `RoleBasedPermission` | Auto-injected with requesting employee ID. |
| `PATCH` | `/api/sales/orders/<id>/` | `IsAuthenticated` + `RoleBasedPermission` | Allowed if not delivered. |
| `PATCH` | `/api/admin/sales/orders/<id>/` | `IsOwnerOrOrdersManage` | Owner or `orders_manage=True`. Enforces status workflow; locked once delivered. |
| **COLLECTIONS** |
| `GET` | `/api/sales/collections/` | `IsAuthenticated` + `RoleBasedPermission` | Admins see all; Salesmen see own collections. |
| `POST` | `/api/sales/collections/` | `IsAuthenticated` + `RoleBasedPermission` | Auto-injected with requesting employee ID. |
| `PATCH` | `/api/admin/sales/collections/<id>/` | `IsOwnerOrCollectionManage` | Owner or `collection_manage=True`. Reconciles order amount. |
| **SALES ANALYTICS** |
| `GET` | `/api/sales/order-analytics/` | `IsAuthenticated` | Delivered orders for authenticated user (max 6-month window). |
| `GET` | `/api/admin/sales/order-analytics/` | `IsOwnerOrOrdersManage` | Delivered orders for all or target employee (hierarchy checked). |
| **TARGETS** |
| `GET` | `/api/sales/monthly-targets/` | `IsAuthenticated` | Authenticated salesman: individual target or common fallback. |
| `GET` | `/api/sales/special-targets/` | `IsAuthenticated` | Authenticated salesman: individual target or common fallback. |
| `ALL` | `/api/admin/sales/monthly-targets/` | `IsTargetAdmin` | Owner or any of `orders_manage`/`collection_manage`/`visit_manage`. |
| `ALL` | `/api/admin/sales/special-targets/` | `IsTargetAdmin` | Owner or any of `orders_manage`/`collection_manage`/`visit_manage`. |
| **ATTENDANCE & DAY REPORTS** |
| `POST` | `/api/tracking/attendance/check-in/` | `IsAuthenticated` | Check in own attendance. |
| `POST` | `/api/tracking/attendance/check-out/` | `IsAuthenticated` | Check out own attendance. |
| `GET` | `/api/tracking/attendance/status/` | `IsAuthenticated` | Today's check-in status for requester. |
| `GET` | `/api/tracking/attendance/km-report/` | `IsAuthenticated` | Daily travel km for requester. |
| `GET` | `/api/tracking/attendance/` | `IsAuthenticated` | Monthly attendance for requester. |
| `GET` | `/api/tracking/attendance/<id>/` | `IsAuthenticated` | Own record, or admin viewing equivalent/lower-level staff. Superiors blocked (403). |
| `PATCH` | `/api/tracking/attendance/<id>/` | `RoleBasedPermission` | Owner or `attendance_manage=True`. Requires `can_manage(target)` (must strictly outrank). |
| `GET` | `/api/admin/tracking/attendance/date/` | `IsAdminManagerOrOwner` | All equivalent/lower-level employees on date (paginated). Superiors excluded. |
| `GET` | `/api/admin/tracking/attendance/<user_id>/` | `IsAdminManagerOrOwner` | Full monthly attendance details for target employee (equivalent/lower only, 403 on superior). |
| `GET/POST/PATCH` | `/api/tracking/sod/` & `/eod/` | `IsAuthenticated` | Start/End of Day report for requester. |
| `GET` | `/api/admin/tracking/sod/<id>/` & `/eod/<id>/`| `IsAdminManagerOrOwner` | View SOD/EOD report for target employee (equivalent/lower only, 403 on superior). |
| **VISITS** |
| `POST` | `/api/tracking/visit/` | `IsAuthenticated` | Create or bulk-sync visits for requester. |
| `GET` | `/api/tracking/visit/` | `IsAuthenticated` | List requester's visits (defaults to today). |
| `GET` | `/api/tracking/visit/<dealers_id>/` | `IsAuthenticated` | List visits for a dealer connected to requester. |
| `GET` | `/api/admin/tracking/visit/` | `IsOwnerOrVisitManage` | Owner or `visit_manage=True`. Aggregated salesman visit metrics. |
| **MILEAGE** |
| `GET` | `/api/tracking/milage/summary/` | `IsAuthenticated` | Requester's mileage. Viewing others requires `milage_manage=True` and target rank >= requester rank. |
| `GET` | `/api/admin/tracking/milage/<date>/` | `milage_manage` or Owner | Daily mileage records for equivalent and lower-level employees. Superiors excluded. |
| `GET` | `/api/admin/tracking/milage/summary/<user_id>/` | `milage_manage` or Owner | 7-day infinite scroll for target employee (equivalent/lower only, 403 on superior). |
| **CRM LEADS & CUSTOMERS** |
| `GET` | `/api/crm/leads/` | `IsAuthenticated` + `RoleBasedPermission` | Admins see all; others see own leads. |
| `POST` | `/api/crm/leads/` | `IsAuthenticated` + `RoleBasedPermission` | Auto-assigns authenticated employee. |
| `PATCH/DELETE`| `/api/crm/leads/<id>/` | `RoleBasedPermission` | Owner or `leads_manage=True`. |
| `POST` | `/api/crm/leads/<id>/convert/` | `RoleBasedPermission` | Owner or `leads_manage=True`. Converts to Customer/SubDealer. |
| `ALL` | `/api/crm/customers/` | `IsAuthenticated` | Authenticated access for CRM customers. |
| **COMMUNICATION & NOTIFICATIONS** |
| `GET/POST`| `/api/communication/notes/` | `IsAuthenticated` | Own notes + notes shared with user. |
| `PATCH/DELETE`| `/api/communication/notes/<id>/`| `IsNoteOwnerOrReadOnly` | Creator of note only. |
| `ALL` | `/api/communication/messages/` | `IsAuthenticated` | Filtered to sender or receiver. |
| `GET` | `/api/notifications/` | `IsAuthenticated` | User's own notifications. |
| `POST` | `/api/notifications/broadcast/` | `IsAdminOrManagerUser` | Owners, Managers, SysAdmins only. |
| `DELETE`| `/api/notifications/<id>/` | `IsNotificationRecipient` | Recipient or Admin only. |

---

## 7. Admin Portal vs Field Worker Capabilities

| Functional Domain | Field Workers (`level = 6`) *(Salesman, Employee, Driver)* | Admin Staff (`level <= 5`) *(Owner, Managers, Accountant)* |
|:---|:---|:---|
| **Employee Directory** | Cannot access admin list, create, edit, or reset passwords. | Full access according to strict hierarchy outranking rules. |
| **Role Permissions** | Cannot view or modify roles. | Can view roles list; Owner can create and toggle permissions. |
| **Orders & Invoices** | Can create orders and view their own submitted orders. | Can view all orders, approve, reject, and manage status transitions. |
| **Collections & Cash** | Can log collections from dealers for their own orders. | Can verify collections and mark them successful. |
| **Dealers** | Can view and create sub-dealers assigned to them. | Can reassign dealers to any employee and soft-delete dealers. |
| **Attendance & Reports** | Can check in/out, log daily SOD/EOD plans and view own km. | Can audit organization-wide attendance, inspect SOD/EOD, and edit records. |
| **Visits Tracking** | Can record visits and bulk sync offline visit data. | Can view aggregate visit metrics and performance indicators. |
| **Mileage Tracking** | Can only inspect their own GPS and odometer travel summary. | With `milage_manage=True`, can view all staff mileage and travel logs. |
| **CRM Leads** | Can capture leads and view their own pipeline. | Can convert leads into dealers/customers and edit lead details. |

---

## 8. Soft Delete vs Hard Delete Rules

The application implements dual deletion behavior configured in `admin_mixins.SoftDeleteAdminMixin`:

### 8.1 Superuser Hard Delete
- When an employee with `is_superuser == True` and `employeeidnum == 0` deletes an object via Django Admin:
  - The record is **permanently purged from the database** via `Model.delete()`.
  - Bypasses any soft-delete managers.

### 8.2 Standard Soft Delete
- For all other staff and API operations:
  - Deleting an object sets `is_deleted = True`.
  - The record remains in the database to preserve historical order, collection, and tracking integrity.
  - Active API querysets explicitly filter for `is_deleted=False`.
