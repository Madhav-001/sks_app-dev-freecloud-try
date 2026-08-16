from rest_framework import serializers
from .models import Lead, Customer


class LeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lead
        fields = [
            'id', 'name', 'phone', 'company_name',
            'email', 'address', 'source', 'card',
            'notes', 'employee',
            'category', 'rank', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'employee', 'created_at', 'updated_at']
        extra_kwargs = {
            'company_name': {'required': False, 'allow_blank': True},
            'email': {'required': False, 'allow_blank': True},
            'address': {'required': False, 'allow_blank': True},
            'rank': {'required': False, 'allow_blank': True},
            'card': {'required': False},
            'notes': {'required': False},
        }


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = [
            'id', 'name', 'phone', 'email',
            'address', 'lead', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
