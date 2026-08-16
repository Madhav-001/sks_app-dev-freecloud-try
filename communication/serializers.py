from rest_framework import serializers
from .models import Note, Message

class NoteSerializer(serializers.ModelSerializer):
    shared_to = serializers.PrimaryKeyRelatedField(
        many=True, 
        queryset=Note.shared_to.field.related_model.objects.filter(is_deleted=False), 
        required=False
    )
    categories = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True
    )

    class Meta:
        model = Note
        fields = [
            'id', 'employee', 'title', 'content', 'image', 'categories', 'shared_to',
            'archive', 'pinned', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'employee']

    def to_internal_value(self, data):
        # We need a mutable dictionary if we are going to modify the input values
        if hasattr(data, 'copy'):
            data = data.copy()

        def clean_list_values(values):
            cleaned = []
            if not isinstance(values, (list, tuple, set)):
                values = [values]
            for val in values:
                if val is None or val == '':
                    continue
                if isinstance(val, str):
                    val_stripped = val.strip()
                    # Filter out empty or placeholder representations
                    if not val_stripped or val_stripped in ('""', "''", '[]', '{}', 'null', 'None'):
                        continue
                    # Try parsing as JSON if it looks like a list
                    if val_stripped.startswith('[') and val_stripped.endswith(']'):
                        import json
                        try:
                            parsed = json.loads(val_stripped)
                            cleaned.extend(clean_list_values(parsed))
                            continue
                        except (json.JSONDecodeError, TypeError):
                            pass
                    # Try comma-separated split
                    if ',' in val_stripped:
                        cleaned.extend(clean_list_values(val_stripped.split(',')))
                        continue
                    cleaned.append(val_stripped)
                else:
                    cleaned.append(val)
            return cleaned

        for field_name in ['categories', 'shared_to']:
            if field_name in data:
                if hasattr(data, 'getlist'):
                    raw_values = data.getlist(field_name)
                    cleaned = clean_list_values(raw_values)
                    data.setlist(field_name, cleaned)
                else:
                    raw_values = data[field_name]
                    cleaned = clean_list_values(raw_values)
                    data[field_name] = cleaned

        return super().to_internal_value(data)

    def validate_categories(self, value):
        if not value:
            return ["note"]
        if not isinstance(value, list):
            raise serializers.ValidationError("Categories must be a list.")
        valid_keys = {key for key, _ in Note.CATEGORIES}
        for item in value:
            if item not in valid_keys:
                raise serializers.ValidationError(
                    f"'{item}' is not a valid category. Valid choices: {', '.join(sorted(valid_keys))}"
                )
        return value

class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = [
            'id', 'sender', 'receiver', 'message',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'sender']

    def validate(self, attrs):
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            if request.user == attrs.get('receiver'):
                raise serializers.ValidationError("Sender and receiver must be different.")
        return attrs




class NoteListItemSerializer(serializers.Serializer):
    notes_id = serializers.UUIDField(source='id')
    title = serializers.CharField(allow_null=True)
    content = serializers.SerializerMethodField()
    image = serializers.ImageField(allow_null=True)
    archive = serializers.BooleanField()
    pinned = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    def get_content(self, obj):
        if not obj.content:
            return ""
        return obj.content[:50] + "..." if len(obj.content) > 50 else obj.content


class NoteListResponseSerializer(serializers.Serializer):
    owned_notes = NoteListItemSerializer(many=True)
    shared_notes = NoteListItemSerializer(many=True)
