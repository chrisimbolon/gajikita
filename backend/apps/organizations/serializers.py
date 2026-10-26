import re

from rest_framework import serializers

from .models import Organization


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Organization
        fields = ["id", "name", "invoice_code", "phone", "address", "plan", "is_active", "created_at"]
        read_only_fields = ["id", "plan", "is_active", "created_at"]


class OrganizationSettingsUpdateSerializer(serializers.ModelSerializer):
    """What an owner may change about their own company. Never plan or
    is_active — those are platform decisions, not self-service."""
    class Meta:
        model  = Organization
        fields = ["name", "invoice_code", "phone", "address"]

    def validate_invoice_code(self, value):
        value = value.strip().upper()
        if value and not re.match(r"^[A-Z0-9]{1,10}$", value):
            raise serializers.ValidationError("Kode invoice hanya boleh huruf dan angka, maksimal 10 karakter.")
        return value
