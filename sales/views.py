from datetime import datetime

from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from rest_framework import viewsets, status
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from users.permissions import (
    MustChangePasswordPermission,
    RoleBasedPermission,
    IsOwnerOrOrdersManage,
    IsOwnerOrCollectionManage,
)
from .models import Product, Order, Collection
from .serializers import (
    ProductSerializer,
    CollectionSerializer,
    OrderCreateSerializer,
    OrderUpdateSerializer,
    OrderCreatedResponseSerializer,
    OrderListSerializer,
    OrderSummarySerializer,
)


class ProductViewSet(viewsets.ModelViewSet):
    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated, MustChangePasswordPermission, RoleBasedPermission]
    queryset = Product.objects.all()
    serializer_class = ProductSerializer

    def partial_update(self, request, *args, **kwargs):
        # Strip empty strings from multipart data so unset fields are truly omitted
        filtered_data = {k: v for k, v in request.data.items() if v not in ('', None)}
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=filtered_data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)


class OrderViewSet(viewsets.ModelViewSet):
    """
    Order endpoint.

    GET /api/sales/orders/
    ──────────────────────
    Filters (all optional / nullable):
      • from_date=DD:MM:YYYY
      • to_date=DD:MM:YYYY
      • employee_id=<uuid>  (Admin only: OWNER / MANAGER / SYSADMIN)
      • deales_id=<uuid>

    Rules:
      • Admins : access all orders, can filter by employee_id.
      • Employees : access only their own orders.
      • No filters / all null : returns today's orders.
    """

    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    permission_classes = [IsAuthenticated, MustChangePasswordPermission, RoleBasedPermission]
    # Sentinel — real data always comes from get_queryset()
    queryset = Order.objects.none()

    def get_serializer_class(self):
        if self.action == "create":
            return OrderCreateSerializer
        if self.action == "list":
            return OrderListSerializer
        if self.action == "partial_update":
            return OrderUpdateSerializer
        return OrderSummarySerializer

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_admin(user):
        from users.permissions import has_orders_manage_permission
        return has_orders_manage_permission(user)

    def _check_ownership(self, instance):
        """
        Allow access if user created this order, is Owner/superuser, or has 'orders_manage' permission.
        """
        user = self.request.user
        if not (str(instance.employee_id) == str(user.pk) or self._is_admin(user)):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(
                "Access denied. Only the order creator, Owner, or users with 'Orders manage' permission can access this order."
            )

    @staticmethod
    def _is_null(val):
        """Return True when a query-param value is absent / empty / 'null'."""
        return val is None or val == "" or str(val).lower() in ("null", "none")

    @staticmethod
    def _parse_date(value, field_name):
        """Parse DD:MM:YYYY → date, or raise a 400 ValidationError."""
        try:
            return datetime.strptime(value, "%d:%m:%Y").date()
        except ValueError:
            raise ValidationError(
                {field_name: f"Invalid date format '{value}'. Expected DD:MM:YYYY."}
            )

    # ------------------------------------------------------------------
    # Queryset — filtering + ownership scoping
    # ------------------------------------------------------------------

    def get_queryset(self):
        user = self.request.user
        queryset = Order.objects.all().order_by("-created_at")

        # ── Role check ────────────────────────────────────────────────
        is_admin = self._is_admin(user)

        # ── Read query-params ─────────────────────────────────────────
        from_date_str = self.request.query_params.get("from_date")
        to_date_str   = self.request.query_params.get("to_date")
        employee_id   = self.request.query_params.get("employee_id")
        deales_id     = self.request.query_params.get("deales_id")

        null = self._is_null
        all_null = all(null(v) for v in [from_date_str, to_date_str, employee_id, deales_id])

        # ── Default: no filters on LIST → today's orders ──────────────
        # Non-list actions (retrieve, patch, delete) must find any record,
        # not just today's, so we skip this shortcut for them.
        if all_null and self.action == "list":
            qs = queryset.filter(created_at__date=timezone.localdate())
            if not is_admin:
                qs = qs.filter(employee=user)
            return qs

        # ── employee_id guard ──────────────────────────────────────────
        # Non-admins MUST NOT filter by another employee's ID.
        # If they pass employee_id at all, it must match their own token identity.
        if not is_admin and not null(employee_id):
            from rest_framework.exceptions import PermissionDenied
            if str(user.pk) != str(employee_id):
                raise PermissionDenied(
                    "Access denied. You can only access your own orders."
                )

        # ── Ownership scoping ─────────────────────────────────────────
        if not is_admin:
            queryset = queryset.filter(employee=user)
        elif not null(employee_id):
            queryset = queryset.filter(employee_id=employee_id)

        # ── Date-range filter ─────────────────────────────────────────
        if not null(from_date_str):
            queryset = queryset.filter(
                created_at__date__gte=self._parse_date(from_date_str, "from_date")
            )
        if not null(to_date_str):
            queryset = queryset.filter(
                created_at__date__lte=self._parse_date(to_date_str, "to_date")
            )

        # ── Sub-dealer filter ─────────────────────────────────────────
        if not null(deales_id):
            queryset = queryset.filter(sub_dealer_id=deales_id)

        return queryset

    # ------------------------------------------------------------------
    # List — documented with OpenAPI params
    # ------------------------------------------------------------------

    @extend_schema(
        summary="List orders with optional filters",
        description=(
            "Returns a filtered list of Orders. "
            "When all filter params are absent / null, today's orders are returned. "
            "Non-admin employees always receive only their own orders. "
            "Admins may additionally filter by employee_id."
        ),
        parameters=[
            OpenApiParameter(
                name="from_date",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Start date — format: DD:MM:YYYY (e.g. 01:06:2026). Pass null or omit to skip.",
            ),
            OpenApiParameter(
                name="to_date",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="End date — format: DD:MM:YYYY (e.g. 30:06:2026). Pass null or omit to skip.",
            ),
            OpenApiParameter(
                name="employee_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by employee UUID. Admin roles only (OWNER / MANAGER / SYSADMIN); silently ignored for regular employees.",
            ),
            OpenApiParameter(
                name="deales_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by sub-dealer UUID.",
            ),
        ],
        responses={200: OrderListSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    # ------------------------------------------------------------------
    # Create / Destroy
    # ------------------------------------------------------------------

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Always set employee from the access token — never trust the request body
        order = serializer.save(employee=request.user)
        return Response(
            OrderCreatedResponseSerializer(order).data, status=status.HTTP_201_CREATED
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        self._check_ownership(instance)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        self._check_ownership(instance)
        if instance.status == "delivered":
            return Response(
                {"detail": "Order has been delivered and is locked. No content edits are permitted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if instance.status != "pending":
            return Response(
                {"detail": f"Order content cannot be edited. Current status is '{instance.status}'. Content edits (products, quantities, prices, etc.) are only permitted when the order is in 'pending' status."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if "status" in request.data:
            return Response(
                {"detail": "Status cannot be modified via this endpoint. Status changes are strictly managed via the admin approval API (/api/admin/sales/orders/{id}/)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated_order = serializer.save()
        # Return full detail view so caller sees the updated state
        return Response(OrderSummarySerializer(updated_order).data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self._check_ownership(instance)
        if instance.status == "delivered":
            return Response(
                {"detail": "Order has been delivered and is locked. Deletion is not permitted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if instance.status != "pending":
            return Response(
                {"detail": f"Order cannot be deleted. Current status is '{instance.status}'. Only 'pending' orders can be deleted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        instance.is_deleted = True
        instance.save(update_fields=["is_deleted"])
        return Response({"detail": "Order deleted successfully."}, status=status.HTTP_200_OK)


class CollectionViewSet(viewsets.ModelViewSet):
    """
    Collection endpoint — always validates the JWT access token.

    GET /api/sales/collections/
    ──────────────────────────
    Filters:
      • from_date=DD:MM:YYYY & to_date=DD:MM:YYYY (Date range)
      • employee_id=<uuid> (Admin only, ignored if non-admin)
      • deales_id=<uuid> (Sub-dealer ID)
      • reference_id=C|L|T (Amount type)

    Rules:
      • Admins: Access all collections, can filter by employee_id.
      • Employees: Access only own collections. No employee_id filtering.
      • No filters: Returns today's collections for the authenticated user.
    """

    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    serializer_class = CollectionSerializer
    permission_classes = [IsAuthenticated, MustChangePasswordPermission, RoleBasedPermission]
    # Sentinel — real data is always fetched inside get_queryset().
    # Using none() ensures no unfiltered data leaks through DRF's default list.
    queryset = Collection.objects.none()


    @extend_schema(
        summary="List collections for the authenticated employee",
        description=(
            "Returns a filtered list of Collection records. "
            "Token validation is compulsory (Bearer JWT). "
            "Non-admin callers always receive only their own records. "
            "If no filter params are provided, today's collections are returned."
        ),
        parameters=[
            OpenApiParameter(
                name="from_date",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Start date filter — format: DD:MM:YYYY (e.g. 01:06:2026). Pass null or omit to skip.",
            ),
            OpenApiParameter(
                name="to_date",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="End date filter — format: DD:MM:YYYY (e.g. 30:06:2026). Pass null or omit to skip.",
            ),
            OpenApiParameter(
                name="employee_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by employee UUID. Admin roles only (OWNER / MANAGER / SYSADMIN); silently ignored for regular employees.",
            ),
            OpenApiParameter(
                name="deales_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by sub-dealer UUID (the dealer who made the payment).",
            ),
            OpenApiParameter(
                name="reference_id",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["C", "L", "T"],
                description="Filter by amount type: C = Crore, L = Lakh, T = Thousand.",
            ),
        ],
        responses={200: CollectionSerializer(many=True)},
        auth=[{"jwtAuth": []}],
    )
    def list(self, request, *args, **kwargs):
        """
        GET /api/sales/collections/

        Always requires a valid JWT access token (enforced by IsAuthenticated).
        Non-admin callers receive only their own collection records.
        If no filter params are provided, returns today's collections.

        Response:
          [
            {
              "id": "<uuid>",
              "sub_dealer": "<uuid>",       # dealer who paid
              "employee": "<uuid>",         # employee who received the money
              "order": "<uuid>" | null,
              "amount": <decimal>,
              "payment_type": "cash|bank|upi",
              "status": "pending|success|failed",
              "reference_id": "C|L|T" | null,
              "is_deleted": false,
              "created_at": "<datetime>",
              "updated_at": "<datetime>"
            },
            ...
          ]
        """
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_admin(user):
        from users.permissions import has_collection_manage_permission
        return has_collection_manage_permission(user)

    def _check_ownership(self, instance):
        """
        Allow access if user created this collection, is Owner/superuser, or has 'collection_manage' permission.
        """
        user = self.request.user
        if not (str(instance.employee_id) == str(user.pk) or self._is_admin(user)):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(
                "Access denied. Only the collection creator, Owner, or users with 'Collection manage' permission can access this collection."
            )

    @staticmethod
    def _is_null(val):
        """Return True when a query-param value is absent / empty / 'null'."""
        return val is None or val == "" or str(val).lower() in ("null", "none")

    @staticmethod
    def _parse_date(value, field_name):
        """Parse DD:MM:YYYY → date, or raise a 400 ValidationError."""
        try:
            return datetime.strptime(value, "%d:%m:%Y").date()
        except ValueError:
            raise ValidationError(
                {field_name: f"Invalid date format '{value}'. Expected DD:MM:YYYY."}
            )

    # ------------------------------------------------------------------
    # Queryset — all filtering and ownership scoping lives here
    # ------------------------------------------------------------------

    def get_queryset(self):
        user    = self.request.user
        # Always start from a fresh, non-deleted, newest-first queryset.
        queryset = Collection.objects.all().order_by("-created_at")

        # ── Role check ────────────────────────────────────────────────
        is_admin = self._is_admin(user)

        # ── Read query-params (all optional, all nullable) ─────────────
        from_date_str = self.request.query_params.get("from_date")
        to_date_str   = self.request.query_params.get("to_date")
        employee_id   = self.request.query_params.get("employee_id")
        deales_id     = self.request.query_params.get("deales_id")
        reference_id  = self.request.query_params.get("reference_id")

        null     = self._is_null
        all_null = all(
            null(v) for v in [from_date_str, to_date_str, employee_id, deales_id, reference_id]
        )

        # ── Default (no filters, list action only) ────────────────────
        # localdate() uses TIME_ZONE from settings (Asia/Kolkata).
        # IMPORTANT: only restrict to today on LIST — PATCH/DELETE/GET-by-id
        # also go through get_queryset(), and they must find any record, not
        # just today's, otherwise get_object() throws a 404.
        if all_null and self.action == "list":
            qs = queryset.filter(created_at__date=timezone.localdate())
            if not is_admin:
                qs = qs.filter(employee=user)
            return qs

        # ── employee_id guard ──────────────────────────────────────────
        # Non-admins MUST NOT filter by another employee's ID.
        # If they pass employee_id at all, it must match their own token identity.
        if not is_admin and not null(employee_id):
            from rest_framework.exceptions import PermissionDenied
            if str(user.pk) != str(employee_id):
                raise PermissionDenied(
                    "Access denied. You can only access your own collections."
                )

        # ── Ownership scoping ─────────────────────────────────────────
        # Non-admin employees are ALWAYS limited to their own records.
        if not is_admin:
            queryset = queryset.filter(employee=user)
        elif not null(employee_id):
            # Admins can optionally narrow to a specific employee.
            queryset = queryset.filter(employee_id=employee_id)

        # ── Date-range filter ─────────────────────────────────────────
        if not null(from_date_str):
            queryset = queryset.filter(
                created_at__date__gte=self._parse_date(from_date_str, "from_date")
            )
        if not null(to_date_str):
            queryset = queryset.filter(
                created_at__date__lte=self._parse_date(to_date_str, "to_date")
            )

        # ── Sub-dealer filter ─────────────────────────────────────────
        if not null(deales_id):
            queryset = queryset.filter(sub_dealer_id=deales_id)

        # ── Reference-id filter (C | L | T) ──────────────────────────
        if not null(reference_id):
            valid_refs = {c[0] for c in Collection.AMOUNT_TYPE_CHOICES}
            if reference_id not in valid_refs:
                raise ValidationError(
                    {"reference_id": (
                        f"Invalid value '{reference_id}'. "
                        f"Must be one of: {', '.join(sorted(valid_refs))}."
                    )}
                )
            queryset = queryset.filter(reference_id=reference_id)

        return queryset

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        # Always set employee from the access token — never trust the request body
        is_many = isinstance(request.data, list)
        serializer = self.get_serializer(data=request.data, many=is_many)
        serializer.is_valid(raise_exception=True)

        if is_many:
            collections = serializer.save(employee=request.user)
            for collection in collections:
                if collection.status == "success" and collection.order:
                    collection.order.update_status()
        else:
            collection = serializer.save(employee=request.user)
            if collection.status == "success" and collection.order:
                collection.order.update_status()

        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        self._check_ownership(instance)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        self._check_ownership(instance)
        if instance.status != "pending":
            return Response(
                {"detail": f"Collection cannot be edited. Current status is '{instance.status}'. Only 'pending' collections can be modified."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if "status" in request.data:
            return Response(
                {"detail": "Status cannot be modified via this endpoint. Status changes are strictly managed via the admin approval API (/api/admin/sales/collections/{id}/)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self._check_ownership(instance)
        if instance.status != "pending":
            return Response(
                {"detail": f"Collection cannot be deleted. Current status is '{instance.status}'. Only 'pending' collections can be deleted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        instance.is_deleted = True
        instance.save(update_fields=["is_deleted"])
        return Response({"detail": "Collection deleted successfully."}, status=status.HTTP_200_OK)

    @transaction.atomic
    def perform_update(self, serializer):
        collection = serializer.save()
        if collection.order:
            collection.order.update_status()


# Allowed status transition map for orders:
# pending <--> approve <--> in_transit -> delivered
# pending -> rejected (or rejected -> pending)
# delivered is terminal: no further status changes allowed for anyone.
ALLOWED_ORDER_TRANSITIONS = {
    "pending": ["approve", "rejected"],
    "approve": ["pending", "in_transit"],
    "in_transit": ["approve", "delivered"],
    "rejected": ["pending"],
    "delivered": [],  # Terminal state: once delivered, locked for everyone
}


class AdminOrderApproveView(APIView):
    """
    Admin endpoint to approve an order or update its status.
    PATCH /api/admin/sales/orders/{order_id}/

    Restricted to Owner role or users with 'orders_manage' permission.
    """
    permission_classes = [IsAuthenticated, MustChangePasswordPermission, IsOwnerOrOrdersManage]

    @extend_schema(
        summary="Approve or update order status (Admin)",
        description="Updates an order's status according to the status transition flow.",
        responses={200: OrderSummarySerializer},
    )
    def patch(self, request, pk):
        return self._update_order_status(request, pk)

    def _update_order_status(self, request, pk):
        order = get_object_or_404(Order, pk=pk)
        current_status = order.status

        # ── 1. Delivered state lock ────────────────────────────────────
        if current_status == "delivered":
            return Response(
                {"detail": "Order has been delivered and is locked. No further status changes are permitted for anyone, including admins."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_status = request.data.get("status", "approve") if request.data else "approve"
        valid_statuses = [choice[0] for choice in Order.STATUS_CHOICES]
        if new_status not in valid_statuses:
            raise ValidationError(
                {"status": f"Invalid status '{new_status}'. Must be one of: {', '.join(valid_statuses)}."}
            )

        if new_status == current_status:
            return Response(OrderSummarySerializer(order).data, status=status.HTTP_200_OK)

        # ── 2. Transition flow validation ──────────────────────────────
        allowed_next_statuses = ALLOWED_ORDER_TRANSITIONS.get(current_status, [])
        if new_status not in allowed_next_statuses:
            return Response(
                {
                    "status": (
                        f"Invalid status transition from '{current_status}' to '{new_status}'. "
                        f"Allowed next status from '{current_status}': {allowed_next_statuses}."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        order.status = new_status
        order.save(update_fields=["status", "updated_at"])
        return Response(OrderSummarySerializer(order).data, status=status.HTTP_200_OK)


class AdminCollectionApproveView(APIView):
    """
    Admin endpoint to approve a collection or update its status.
    PATCH /api/admin/sales/collections/{collection_id}/

    Restricted to Owner role or users with 'collection_manage' permission.
    """
    permission_classes = [IsAuthenticated, MustChangePasswordPermission, IsOwnerOrCollectionManage]

    @extend_schema(
        summary="Approve or update collection status (Admin)",
        description="Updates a collection's status. Defaults to 'success' if status is omitted.",
        responses={200: CollectionSerializer},
    )
    def patch(self, request, pk):
        return self._update_collection_status(request, pk)

    @transaction.atomic
    def _update_collection_status(self, request, pk):
        collection = get_object_or_404(Collection, pk=pk)
        new_status = request.data.get("status", "success") if request.data else "success"
        valid_statuses = [choice[0] for choice in Collection.STATUS_CHOICES]
        if new_status not in valid_statuses:
            raise ValidationError(
                {"status": f"Invalid status '{new_status}'. Must be one of: {', '.join(valid_statuses)}."}
            )
        collection.status = new_status
        collection.save(update_fields=["status", "updated_at"])
        if collection.order:
            collection.order.update_status()
        return Response(CollectionSerializer(collection).data, status=status.HTTP_200_OK)

