from rest_framework import generics, status, permissions, viewsets
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from django.utils import timezone
from django.http import Http404
from .models import Employee, LoginHistory, EmployeeRole
from .serializers import (
    EmployeeSerializer,
    CreateEmployeeSerializer,
    ChangePasswordSerializer,
    AdminResetPasswordSerializer,
    CustomTokenObtainPairSerializer,
    LoginHistorySerializer,
    LogoutSerializer,
    CustomTokenRefreshSerializer,
    EmployeeRoleSerializer,
    EmployeeRoleCreateSerializer,
)
from .permissions import IsAdminManagerOrOwner, IsAdminUser, CanCreateEmployee, IsOwner, RoleBasedPermission


class CustomLoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer


class CustomTokenRefreshView(TokenRefreshView):
    serializer_class = CustomTokenRefreshSerializer


class LogoutView(generics.GenericAPIView):
    serializer_class = LogoutSerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data["refresh"]
            token = RefreshToken(refresh_token)

            history_id = token.get('history_id')
            if history_id:
                try:
                    history = LoginHistory.objects.get(id=history_id)
                    history.logout_at = timezone.now()
                    history.status = 'inactive'
                    history.save()
                except LoginHistory.DoesNotExist:
                    pass

            token.blacklist()
            return Response({"message": "Successfully logged out."}, status=status.HTTP_205_RESET_CONTENT)
        except Exception:
            return Response({"error": "Invalid token."}, status=status.HTTP_400_BAD_REQUEST)


class LoginHistoryListView(generics.ListAPIView):
    serializer_class = LoginHistorySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return LoginHistory.objects.filter(employee=self.request.user)


class EmployeeCreateView(generics.CreateAPIView):
    queryset = Employee.objects.all()
    serializer_class = CreateEmployeeSerializer
    permission_classes = [CanCreateEmployee, RoleBasedPermission]


class ChangePasswordView(generics.GenericAPIView):
    serializer_class = ChangePasswordSerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user

        if not user.check_password(serializer.validated_data['old_password']):
            return Response({"old_password": ["Wrong password."]}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(serializer.validated_data['new_password'])
        user.must_change_password = False
        user.save()
        return Response({"message": "Password updated successfully."}, status=status.HTTP_200_OK)


class EmployeeListView(generics.ListAPIView):
    queryset = Employee.objects.filter(is_deleted=False)
    serializer_class = EmployeeSerializer
    permission_classes = [permissions.IsAuthenticated]


class EmployeeDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Employee.objects.filter(is_deleted=False)
    serializer_class = EmployeeSerializer
    permission_classes = [IsAdminManagerOrOwner, RoleBasedPermission]
    lookup_field = "id"
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_object(self):
        """
        Retrieves the target employee and enforces hierarchy:
        - Admins (level <= 5) may view any employee record (GET).
        - For PATCH / DELETE the requester must outrank the target.
        """
        obj = super().get_object()
        requester = self.request.user

        # Mutating methods require hierarchy authority over the target
        if self.request.method in ('PATCH', 'DELETE'):
            if not requester.can_manage(obj):
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied(
                    "You cannot edit or delete an employee who is ranked the same as or higher than you."
                )
        return obj

    def perform_destroy(self, instance):
        instance.is_deleted = True
        instance.save()


class UserProfileView(generics.RetrieveAPIView):
    serializer_class = EmployeeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class AdminResetEmployeePasswordView(generics.GenericAPIView):
    """
    POST /users/<uuid:id>/reset-password/

    Allows an admin (Owner / Manager / Sys-Admin) to reset any employee's
    password without knowing the current password.  After a successful reset
    the target employee's `must_change_password` flag is set to True so they
    are forced to choose a new password on next login.

    Access rules
    ------------
    * Only OWNER, MANAGER, and SYSADMIN may call this endpoint.
    * Only an OWNER (or superuser) can reset another OWNER's password.
    * An admin cannot reset their own password via this endpoint — they should
      use the regular change-password flow.
    """

    serializer_class = AdminResetPasswordSerializer
    permission_classes = [IsAdminManagerOrOwner, RoleBasedPermission]

    def post(self, request, id, *args, **kwargs):
        try:
            target = Employee.objects.get(id=id, is_deleted=False)
        except Employee.DoesNotExist:
            return Response({"error": "Employee not found."}, status=status.HTTP_404_NOT_FOUND)

        if target == request.user:
            return Response(
                {"error": "Use the change-password endpoint to update your own password."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Hierarchy check: requester must outrank target
        if not request.user.can_manage(target):
            return Response(
                {"error": "You cannot reset the password of an employee who is ranked the same as or higher than you."},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        target.set_password(serializer.validated_data['new_password'])
        target.must_change_password = True
        target.save()

        return Response(
            {"message": f"Password for '{target.username}' has been reset successfully."},
            status=status.HTTP_200_OK
        )


class EmployeeRoleViewSet(viewsets.ModelViewSet):
    """
    ViewSet for the role-based access control matrix.

    GET    /api/auth/roles/          → list all roles (Admin-portal users only)
    POST   /api/auth/roles/          → create a new custom role  (Owner only)
    GET    /api/auth/roles/<id>/     → retrieve one role (any authenticated user)
    PATCH  /api/auth/roles/<id>/     → toggle permission booleans (Owner only)
    DELETE /api/auth/roles/<id>/     → delete a custom role       (Owner only, not built-in)
    """
    # Ordered by hierarchy_level via model Meta — Owner appears first.
    queryset = EmployeeRole.objects.all()

    def get_permissions(self):
        if self.action == 'retrieve':
            # Any authenticated employee may look up a specific role by ID
            return [permissions.IsAuthenticated()]
        if self.action == 'list':
            # Only admin-portal staff (level 1–5) may see the full role list
            from .permissions import IsAdminUser
            return [permissions.IsAuthenticated(), IsAdminUser()]
        # create / partial_update / destroy → Owner only
        return [permissions.IsAuthenticated(), IsOwner()]

    def get_serializer_class(self):
        if self.action == 'create':
            return EmployeeRoleCreateSerializer
        return EmployeeRoleSerializer

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        # OWNER role is fully protected — its permissions are hardcoded in code.
        if instance.name == "OWNER":
            return Response(
                {"detail": "The Owner role is protected and cannot be modified."},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.name == "OWNER":
            return Response(
                {"detail": "The Owner role is protected and cannot be deleted."},
                status=status.HTTP_403_FORBIDDEN
            )
        if instance.is_builtin:
            return Response(
                {"detail": "Built-in roles cannot be deleted."},
                status=status.HTTP_400_BAD_REQUEST
            )
        # Check no employees currently use this role
        if Employee.objects.filter(role=instance, is_deleted=False).exists():
            return Response(
                {"detail": f"Cannot delete role '{instance.display_name}' while employees are assigned to it."},
                status=status.HTTP_400_BAD_REQUEST
            )
        return super().destroy(request, *args, **kwargs)

