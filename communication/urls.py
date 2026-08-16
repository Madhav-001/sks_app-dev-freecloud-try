from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import NoteViewSet, MessageViewSet

router = DefaultRouter()
router.register(r'notes', NoteViewSet, basename='note')
router.register(r'messages', MessageViewSet, basename='message')

urlpatterns = [
    path('notes/bin/', NoteViewSet.as_view({'get': 'bin_list'}), name='note-bin-list'),
    path('notes/bin/<uuid:pk>/', NoteViewSet.as_view({'get': 'recover'}), name='note-recover'),
    path('', include(router.urls)),
]
