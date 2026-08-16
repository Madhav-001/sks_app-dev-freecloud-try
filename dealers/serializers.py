from rest_framework import serializers
from .models import SubDealer


class SubDealerSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubDealer
        fields = [
            'id', 'shop_name', 'phone', 'card_image', 'owner_name', 'gst_no',
            'contact_person', 'contact_person_phone', 'shop_number', 'street',
            'district', 'state', 'country', 'pincode', 'store_picture',
            'landmark', 'secondary_address', 'secondary_pincode', 'latitude',
            'longitude', 'email', 'employee', 'rank', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class SubDealerListSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubDealer
        fields = [
            'id', 'shop_name', 'phone', 'contact_person', 'contact_person_phone',
            'shop_number', 'store_picture', 'employee', 'rank', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']



class SubDealerUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for PATCH /api/dealers/<id>/.

    - No mandatory fields in the request body; the dealer is identified solely
      by the <id> URL parameter.
    - Fields sent as empty string ("") or null are silently ignored — they are
      stripped before validation so DRF treats them as absent (not provided).
    - Only fields with actual values are validated and saved.
    - 'employee' field access control is enforced at the view level.
    """

    class Meta:
        model = SubDealer
        fields = [
            'shop_name', 'phone', 'card_image', 'owner_name', 'gst_no',
            'contact_person', 'contact_person_phone', 'shop_number', 'street',
            'district', 'state', 'country', 'pincode', 'store_picture',
            'landmark', 'secondary_address', 'secondary_pincode', 'latitude',
            'longitude', 'email', 'employee', 'rank'
        ]

    def to_internal_value(self, data):
        """
        Strip keys whose value is empty string or None before validation.
        This makes DRF treat those fields as absent, so partial=True skips them
        entirely — no "may not be blank / may not be null" errors are raised.
        """
        filtered_data = {
            key: value
            for key, value in data.items()
            if value not in ('', None)
        }
        return super().to_internal_value(filtered_data)
