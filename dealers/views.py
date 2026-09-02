from rest_framework import generics, permissions
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied, NotFound
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from users.permissions import MustChangePasswordPermission, RoleBasedPermission, is_admin_of

from .models import SubDealer
from .serializers import SubDealerSerializer, SubDealerUpdateSerializer, SubDealerListSerializer


class SubDealerListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, MustChangePasswordPermission, RoleBasedPermission]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        user = self.request.user
        queryset = SubDealer.objects.filter(is_deleted=False).select_related('employee')
        # Non-admins see only dealers they personally manage
        if not is_admin_of(user):
            queryset = queryset.filter(employee=user)
        return queryset

    def get_serializer_class(self):
        if self.request.method == "GET":
            return SubDealerListSerializer
        return SubDealerSerializer



class SubDealerUpdateView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET    /api/dealers/<id>/  — Admins or the associated employee
    PATCH  /api/dealers/<id>/  — Admins or the associated employee
                                 Only admins can update the 'employee' field
    DELETE /api/dealers/<id>/  — Soft delete (admins only)
    """

    permission_classes = [IsAuthenticated, MustChangePasswordPermission, RoleBasedPermission]
    serializer_class = SubDealerSerializer
    lookup_field = "id"
    http_method_names = ["get", "patch", "delete", "head", "options"]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        return SubDealer.objects.filter(is_deleted=False)

    def get_object(self):
        """Return dealer if the requester is admin or the associated employee."""
        try:
            dealer = SubDealer.objects.get(id=self.kwargs["id"], is_deleted=False)
        except SubDealer.DoesNotExist:
            raise NotFound("Dealer not found.")

        user = self.request.user
        if not is_admin_of(user) and dealer.employee_id != user.id:
            raise PermissionDenied(
                "You do not have permission to access this dealer."
            )
        return dealer

    def get_serializer_class(self):
        if self.request.method == "PATCH":
            return SubDealerUpdateSerializer
        return SubDealerSerializer

    def partial_update(self, request, *args, **kwargs):
        """
        PATCH — any provided field is updated.
        Only admins are allowed to change the 'employee' field.
        """
        if 'employee' in request.data and not is_admin_of(request.user):
            raise PermissionDenied(
                "Only admins can reassign the employee on a dealer."
            )
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)

    def perform_destroy(self, instance):
        """Soft delete — only admins can delete."""
        if not is_admin_of(self.request.user):
            raise PermissionDenied("Only admins can delete a dealer.")
        instance.is_deleted = True
        instance.save()
