from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from .models import Note, Message
from .serializers import NoteSerializer, MessageSerializer, NoteListResponseSerializer, NoteListItemSerializer
from django.db.models import Q

class IsOwnerOrManager(permissions.BasePermission):
    """
    Custom permission to only allow Owners and Managers to create/edit notifications.
    """
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        role_name = request.user.role.name if getattr(request.user, 'role', None) else ""
        return role_name in ['OWNER', 'MANAGER']



class IsNoteOwnerOrReadOnly(permissions.BasePermission):
    """
    Object-level permission to only allow owners of a note to edit or delete it.
    """
    def has_object_permission(self, request, view, obj):
        # Read-only operations are allowed for any note returned by the queryset
        if request.method in permissions.SAFE_METHODS:
            return True
        # Write operations are only allowed for the creator of the note
        return obj.employee == request.user

class NoteViewSet(viewsets.ModelViewSet):
    """
    API for Notes. Users can see their own notes and notes shared with them.
    Notes can be shared to other employees (like managers).
    """
    serializer_class = NoteSerializer
    permission_classes = [permissions.IsAuthenticated, IsNoteOwnerOrReadOnly]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def purge_expired_notes(self):
        from django.utils import timezone
        from datetime import timedelta
        cutoff = timezone.now() - timedelta(days=30)
        Note.objects.filter(is_deleted=True, deleted_at__lt=cutoff).delete()

    def get_queryset(self):
        self.purge_expired_notes()
        user = self.request.user
        # Active notes (is_deleted=False) are visible to creator and shared users.
        # Soft-deleted notes (is_deleted=True) are visible ONLY to the creator (owner).
        return Note.objects.filter(
            Q(is_deleted=False, employee=user) |
            Q(is_deleted=False, shared_to=user) |
            Q(is_deleted=True, employee=user)
        ).distinct()

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="archive",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Pass true to list archived notes. Defaults to false.",
            )
        ],
        responses={200: NoteListResponseSerializer}
    )
    def list(self, request, *args, **kwargs):
        self.purge_expired_notes()
        user = request.user
        show_archive = request.query_params.get("archive", "false").lower() == "true"

        owned_qs = Note.objects.filter(
            employee=user, 
            is_deleted=False, 
            archive=show_archive
        ).order_by("-pinned", "-created_at")

        shared_qs = Note.objects.filter(
            shared_to=user, 
            is_deleted=False, 
            archive=show_archive
        ).exclude(employee=user).distinct().order_by("-pinned", "-created_at")

        serializer = NoteListResponseSerializer(
            {
                "owned_notes": owned_qs,
                "shared_notes": shared_qs
            },
            context={"request": request}
        )
        return Response(serializer.data)

    def bin_list(self, request):
        self.purge_expired_notes()
        user = request.user
        deleted_notes = Note.objects.filter(employee=user, is_deleted=True).order_by("-deleted_at")
        serializer = NoteListItemSerializer(deleted_notes, many=True, context={'request': request})
        return Response(serializer.data)

    def recover(self, request, pk=None):
        self.purge_expired_notes()
        try:
            # Only the owner is allowed to recover the note
            note = Note.objects.get(id=pk, employee=request.user, is_deleted=True)
        except Note.DoesNotExist:
            return Response({"detail": "No Note matches the given query."}, status=status.HTTP_404_NOT_FOUND)
        
        note.is_deleted = False
        note.deleted_at = None
        note.save(update_fields=['is_deleted', 'deleted_at'])
        return Response({"detail": "Note recovered successfully."}, status=status.HTTP_200_OK)

    def perform_destroy(self, instance):
        if instance.is_deleted:
            # Permanent delete if already soft-deleted
            instance.delete()
        else:
            # Soft delete
            from django.utils import timezone
            instance.is_deleted = True
            instance.deleted_at = timezone.now()
            instance.save(update_fields=['is_deleted', 'deleted_at'])

    def partial_update(self, request, *args, **kwargs):
        # Strip empty strings, None, and empty lists from data so unset fields are truly omitted
        if hasattr(request.data, 'copy'):
            data = request.data.copy()
            for key in list(data.keys()):
                vals = data.getlist(key)
                if not vals or all(v in ('', None) for v in vals):
                    data.pop(key, None)
        else:
            data = {k: v for k, v in request.data.items() if v not in ('', None, [])}

        instance = self.get_object()
        serializer = self.get_serializer(instance, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        is_many = isinstance(request.data, list)
        serializer = self.get_serializer(data=request.data, many=is_many)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        serializer.save(employee=self.request.user)

class MessageViewSet(viewsets.ModelViewSet):
    """
    API for Messages. Only sender and receiver can see the message.
    """
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return Message.objects.filter(Q(sender=user) | Q(receiver=user))

    def perform_create(self, serializer):
        serializer.save(sender=self.request.user)


