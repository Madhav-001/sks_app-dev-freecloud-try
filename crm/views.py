from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.exceptions import PermissionDenied, NotFound
from users.permissions import RoleBasedPermission, is_admin_of
from .models import Lead, Customer
from .serializers import LeadSerializer, CustomerSerializer
from dealers.models import SubDealer
from dealers.serializers import SubDealerSerializer


class LeadViewSet(viewsets.ModelViewSet):
    """CRUD API for Lead model.

    Access rules
    ------------
    POST   /leads/          — All authenticated employees
    GET    /leads/          — Admins: all leads  |  Others: own leads only
    GET    /leads/{id}/     — Admins: any lead   |  Others: own lead only
    PATCH  /leads/{id}/     — Admins only (leads_manage flag)
    DELETE /leads/{id}/     — Admins only (leads_manage flag)
    POST   /leads/{id}/convert/ — Admins only (leads_manage flag)
    """

    serializer_class = LeadSerializer
    permission_classes = [permissions.IsAuthenticated, RoleBasedPermission]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        """
        Admins see all non-deleted leads.
        Non-admin employees see ONLY their own leads.
        """
        user = self.request.user
        qs = Lead.objects.filter(is_deleted=False)
        if not is_admin_of(user):
            qs = qs.filter(employee=user)
        return qs

    def get_object(self):
        """
        Standard lookup, then ownership check for non-admins on retrieve.
        PATCH / DELETE / convert are already blocked at permission level via
        RoleBasedPermission → leads_manage flag, so only GET needs this
        extra check.
        """
        queryset = self.get_queryset()
        try:
            obj = queryset.get(pk=self.kwargs[self.lookup_field])
        except (Lead.DoesNotExist, ValueError, TypeError):
            raise NotFound("Lead not found.")

        self.check_object_permissions(self.request, obj)
        return obj

    def _strip_blank_fields(self, data):
        """Remove keys with blank/empty values so partial update ignores them."""
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v not in [None, '']}
        return data

    def update(self, request, *args, **kwargs):
        """Strip blank fields on partial (PATCH) updates so only
        fields with actual values are validated and saved."""
        if kwargs.get('partial', False):
            request._full_data = self._strip_blank_fields(request.data)
        return super().update(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        """Support both single object and bulk list creation."""
        is_many = isinstance(request.data, list)
        serializer = self.get_serializer(data=request.data, many=is_many)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        """Auto-assign employee from the authenticated user's access token."""
        serializer.save(employee=self.request.user)

    @action(detail=True, methods=['post'], url_path='convert')
    def convert(self, request, pk=None):
        """Convert a lead into a Customer or SubDealer.
        Expected payload: {"target": "customer"} or {"target": "dealer"}
        """
        lead = self.get_object()
        target = request.data.get('target')
        if target == 'customer':
            customer = Customer.objects.create(
                name=lead.name,
                phone=lead.phone,
                email=lead.email,
                address=lead.address,
                lead=lead,
            )
            serializer = CustomerSerializer(customer)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        elif target == 'dealer':
            subdealer = SubDealer.objects.create(
                shop_name=lead.company_name or lead.name,
                phone=lead.phone,
                address=lead.address,
                email=lead.email,
                employee=lead.employee,
                # Additional fields can be set as needed
            )
            serializer = SubDealerSerializer(subdealer)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            return Response({"detail": "Invalid target type"}, status=status.HTTP_400_BAD_REQUEST)

class CustomerViewSet(viewsets.ModelViewSet):
    """CRUD API for Customer model."""
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']
