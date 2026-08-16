# Walkthrough - Visit API Updates

We updated the `POST /api/tracking/visit/create/` API to support list-based (bulk) inputs and outputs, mapped custom fields (`visit_id`, `image`), and introduced a new `time` field to track visits precisely.

## Key Changes

### 1. Database Model
- **File**: [models.py](file:///d:/Mady/program/git/Anbu_anna/SKS_BE/sks_app-dev/tracking/models.py)
- **Change**: Added `time = models.TimeField(null=True, blank=True)` to store visit times.

### 2. Database Migration
- **File**: [0006_visit_time.py](file:///d:/Mady/program/git/Anbu_anna/SKS_BE/sks_app-dev/tracking/migrations/0006_visit_time.py)
- **Change**: Manually generated clean migration file to add the `time` field to the `tracking_visit` database table.

### 3. Serializer Customization
- **File**: [serializers.py](file:///d:/Mady/program/git/Anbu_anna/SKS_BE/sks_app-dev/tracking/serializers.py)
- **Change**: Customized `VisitSerializer` to format inputs and outputs precisely as specified:
  - `visit_id` maps to the database `id` field.
  - `image` maps to `gps_image`.
  - `time` formats to `'HH:MM:SS'`.
  - `latitude` and `longitude` are serialized as strings.
  - `created_at` and `updated_at` format to `'%Y-%m-%d %H:%M:%S'`.

### 4. Bulk/List View Handling
- **File**: [views.py](file:///d:/Mady/program/git/Anbu_anna/SKS_BE/sks_app-dev/tracking/views.py)
- **Change**: Updated the `create_visit` action in `VisitViewSet` to dynamically parse list inputs (both standard JSON arrays and multipart lists) and return bulk list output response bodies with status `HTTP_201_CREATED`.

### 5. Automated Tests
- **File**: [test_tracking_api.py](file:///d:/Mady/program/git/Anbu_anna/SKS_BE/sks_app-dev/tests/api/test_tracking_api.py)
- **Change**: Updated `test_create_visit` and added `test_create_visit_bulk` to ensure single and list-based visit uploads work exactly as expected.

### 6. List/GET View Filtering & Security
- **File**: [views.py](file:///d:/Mady/program/git/Anbu_anna/SKS_BE/sks_app-dev/tracking/views.py)
- **Change**: Configured `VisitViewSet.get_queryset` to default filtering to the current day if no date is specified. Extracted `date` from either query params or request payload, restricted queries to the currently authenticated employee's own records, and enforced `IsAuthenticated` access.
- **File**: [test_tracking_api.py](file:///d:/Mady/program/git/Anbu_anna/SKS_BE/sks_app-dev/tests/api/test_tracking_api.py)
- **Change**: Expanded `test_list_visits` to cover automatic defaulting to current day, matching query params explicitly, and asserting zero results for other dates.

### 7. Admin View Specific Employee's Visits (`GET /api/tracking/visit/{employee_id}/`)
- **File**: [views.py](file:///d:/Mady/program/git/Anbu_anna/SKS_BE/sks_app-dev/tracking/views.py)
- **Change**: Implemented the `retrieve` action in `VisitViewSet` to retrieve a list of all visits for a specific employee on a given date (defaults to the current day). Restricted this detail view using `IsAdminManagerOrOwner` permission class via dynamic `get_permissions(self)`.
- **Change**: Explicitly added `lookup_url_kwarg = 'employee_id'` on `VisitViewSet` so that the URL parameter is documented and routed as `{employee_id}` (lookup keyword argument name) rather than the generic `{id}` parameter.
- **File**: [test_tracking_api.py](file:///d:/Mady/program/git/Anbu_anna/SKS_BE/sks_app-dev/tests/api/test_tracking_api.py)
- **Change**: Added `test_admin_retrieve_employee_visits` (verifying formatted outputs and day filtering for admins) and `test_non_admin_retrieve_forbidden` (verifying employees are forbidden from accessing other employees' details).

### 8. Employee Retrieve Visits for a Dealer (`GET /api/tracking/visit/{dealers_id}/`)
- **File**: [views.py](file:///d:/Mady/program/git/Anbu_anna/SKS_BE/sks_app-dev/tracking/views.py)
- **Change**: Enhanced `VisitViewSet.retrieve` to dynamically recognize if the lookup ID is a `SubDealer` ID. If yes, it checks whether the authenticated employee has a connection to the dealer (i.e. `dealer.employee == request.user`), raising a `403 Forbidden` if not. If connected, it lists all visits for that dealer, supporting optional date filtering.
- **File**: [test_tracking_api.py](file:///d:/Mady/program/git/Anbu_anna/SKS_BE/sks_app-dev/tests/api/test_tracking_api.py)
- **Change**: Added `test_employee_retrieve_dealer_visits_connected` (confirming successful retrieval) and `test_employee_retrieve_dealer_visits_not_connected_forbidden` (confirming `403 Forbidden` on lack of connection).
