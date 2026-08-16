from django.contrib import admin
from .models import Note, Message

@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ('id', 'employee', 'title', 'categories', 'content_summary', 'updated_at', 'is_deleted', 'deleted_at')
    
    def content_summary(self, obj):
        return obj.content[:50] + "..." if len(obj.content) > 50 else obj.content

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'sender', 'receiver', 'updated_at', 'created_at')
    list_filter = ('sender', 'receiver')
