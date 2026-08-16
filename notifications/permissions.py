from rest_framework import permissions


class IsNotificationRecipient(permissions.BasePermission):
    """
    Object-level permission to only allow recipients of a notification to view/edit it.
    """

    def has_object_permission(self, request, view, obj):
        # Admins (OWNER, MANAGER, SYSADMIN, Superuser) can access any notification.
        # But normal employees can only access their own notifications.
        user = request.user
        role_name = user.role.name if getattr(user, 'role', None) else ""
        is_admin = user.is_superuser or (role_name in ['OWNER', 'MANAGER', 'SYSADMIN'])
        if is_admin:
            return True
        return obj.recipient == user


class IsAdminOrManagerUser(permissions.BasePermission):
    """
    Permission to only allow Owners, Managers, and Sys-admins.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        role_name = request.user.role.name if getattr(request.user, 'role', None) else ""
        return (
            role_name in ["OWNER", "MANAGER", "SYSADMIN"]
            or request.user.is_superuser
        )

