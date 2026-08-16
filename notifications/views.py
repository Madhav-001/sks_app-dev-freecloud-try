from rest_framework import status, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from notifications.models import Notification
from notifications.selectors import NotificationSelector
from notifications.services import NotificationService
from notifications.repositories import DeviceRepository, PreferenceRepository
from notifications.permissions import IsNotificationRecipient, IsAdminOrManagerUser
from notifications.filters import filter_notifications
from notifications.serializers import (
    NotificationSerializer,
    DeviceRegisterSerializer,
    DeviceRemoveSerializer,
    NotificationPreferenceSerializer,
    BroadcastSerializer,
)


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class NotificationViewSet(viewsets.ViewSet):
    """
    API endpoints for Notifications.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.action in ['broadcast']:
            return [permissions.IsAuthenticated(), IsAdminOrManagerUser()]
        if self.action in ['destroy', 'read', 'archive']:
            return [permissions.IsAuthenticated(), IsNotificationRecipient()]
        return super().get_permissions()

    def list(self, request):
        """
        GET /api/notifications/
        List all notifications for the authenticated user (supports search, filter, pagination).
        """
        queryset = NotificationSelector.get_user_notifications(request.user)
        queryset = filter_notifications(queryset, request.query_params)
        
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(queryset, request)
        if page is not None:
            serializer = NotificationSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
            
        serializer = NotificationSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='unread', url_name='unread')
    def unread(self, request):
        """
        GET /api/notifications/unread/
        List all unread notifications for the authenticated user.
        """
        queryset = NotificationSelector.get_unread_notifications(request.user)
        queryset = filter_notifications(queryset, request.query_params)
        
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(queryset, request)
        if page is not None:
            serializer = NotificationSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
            
        serializer = NotificationSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='count', url_name='count')
    def count(self, request):
        """
        GET /api/notifications/count/
        Get count of unread notifications for the authenticated user.
        """
        count = NotificationService.get_unread_count(request.user)
        return Response({'unread_count': count}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['patch'], url_path='read', url_name='read')
    def read(self, request, pk=None):
        """
        PATCH /api/notifications/{id}/read/
        Mark a specific notification as read.
        """
        notification = NotificationService.mark_read(pk, request.user)
        if not notification:
            return Response({'detail': 'Notification not found or unauthorized.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = NotificationSerializer(notification)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['patch'], url_path='read-all', url_name='read-all')
    def read_all(self, request):
        """
        PATCH /api/notifications/read-all/
        Mark all unread notifications of the user as read.
        """
        updated_count = NotificationService.mark_all_read(request.user)
        return Response({'detail': f'All notifications marked as read. Count: {updated_count}'}, status=status.HTTP_200_OK)

    def destroy(self, request, pk=None):
        """
        DELETE /api/notifications/{id}/
        Delete a notification.
        """
        success = NotificationService.delete(pk, request.user)
        if not success:
            return Response({'detail': 'Notification not found or unauthorized.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'detail': 'Notification deleted successfully.'}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='test', url_name='test')
    def test_notification(self, request):
        """
        POST /api/notifications/test/
        Create a test notification for the authenticated user.
        """
        title = request.data.get('title', 'Test Notification')
        body = request.data.get('body', 'This is a test notification from the system.')
        notif_type = request.data.get('notification_type', 'system')
        priority = request.data.get('priority', 'MEDIUM')
        
        notification = NotificationService.send(
            recipient=request.user,
            title=title,
            body=body,
            notification_type=notif_type,
            sender=request.user,
            priority=priority,
            payload={'is_test': True}
        )
        if not notification:
            return Response({'detail': 'Notification failed to send. Check preference settings.'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = NotificationSerializer(notification)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='broadcast', url_name='broadcast')
    def broadcast(self, request):
        """
        POST /api/notifications/broadcast/
        Broadcast a notification based on roles/dealer/employee/region (Admin-only).
        """
        serializer = BroadcastSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        data = serializer.validated_data
        created_list = NotificationService.broadcast(
            title=data['title'],
            body=data['body'],
            notification_type=data['notification_type'],
            sender=request.user,
            priority=data['priority'],
            payload=data.get('payload', {}),
            target_role=data.get('target_role'),
            target_dealer=data.get('target_dealer'),
            target_employee=data.get('target_employee'),
            target_region=data.get('target_region')
        )
        
        return Response({
            'detail': f'Broadcast triggered. Dispatched to {len(created_list)} users.'
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'], url_path='sent', url_name='sent')
    def sent(self, request):
        """
        GET /api/notifications/sent/
        List all notifications sent by the authenticated user.
        """
        queryset = Notification.objects.filter(sender=request.user).select_related('recipient', 'sender')
        queryset = filter_notifications(queryset, request.query_params)
        
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(queryset, request)
        if page is not None:
            serializer = NotificationSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
            
        serializer = NotificationSerializer(queryset, many=True)
        return Response(serializer.data)


class DeviceViewSet(viewsets.ViewSet):
    """
    API endpoints for Device registration and removal.
    """
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=['post'], url_path='register', url_name='register')
    def register(self, request):
        """
        POST /api/notifications/device/register/
        Register a logged-in device.
        """
        serializer = DeviceRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        data = serializer.validated_data
        device = DeviceRepository.register_device(
            user=request.user,
            platform=data['platform'],
            device_id=data['device_id'],
            device_name=data['device_name'],
            app_version=data['app_version'],
            push_token=data.get('push_token')
        )
        return Response({
            'detail': 'Device registered successfully.',
            'device_id': device.device_id,
            'active': device.active
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='remove', url_name='remove')
    def remove(self, request):
        """
        POST /api/notifications/device/remove/
        Remove/deactivate a logged-in device.
        """
        serializer = DeviceRemoveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        DeviceRepository.deactivate_device(
            user=request.user,
            device_id=serializer.validated_data['device_id']
        )
        return Response({'detail': 'Device deactivated successfully.'}, status=status.HTTP_200_OK)


class PreferenceViewSet(viewsets.ViewSet):
    """
    API endpoints for Notification Preferences.
    """
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        """
        GET /api/notifications/preferences/
        Get notification preferences for the logged-in user.
        """
        prefs = PreferenceRepository.get_for_user(request.user)
        serializer = NotificationPreferenceSerializer(prefs)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def update(self, request, pk=None):
        """
        PUT /api/notifications/preferences/update/ or PATCH
        Update notification preferences for the logged-in user.
        """
        serializer = NotificationPreferenceSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        
        prefs = PreferenceRepository.update_preferences(request.user, **serializer.validated_data)
        return Response(NotificationPreferenceSerializer(prefs).data, status=status.HTTP_200_OK)
