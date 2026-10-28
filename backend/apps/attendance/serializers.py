from rest_framework import serializers

from .models import ClockEvent

MAX_SELFIE_BYTES = 2 * 1024 * 1024   # the app compresses to ~50 KB; 2 MB is a generous ceiling


class ClockInputSerializer(serializers.Serializer):
    kind       = serializers.ChoiceField(choices=ClockEvent.Kind.choices)
    latitude   = serializers.FloatField(required=False, allow_null=True, min_value=-90, max_value=90)
    longitude  = serializers.FloatField(required=False, allow_null=True, min_value=-180, max_value=180)
    accuracy   = serializers.FloatField(required=False, allow_null=True, min_value=0)
    phone_time = serializers.DateTimeField(required=False, allow_null=True)
    queued     = serializers.BooleanField(required=False, default=False)
    client_id  = serializers.UUIDField(required=False, allow_null=True)
    site_id    = serializers.UUIDField(required=False, allow_null=True)
    selfie     = serializers.ImageField(required=False, allow_null=True)

    def validate_selfie(self, value):
        if value and value.size > MAX_SELFIE_BYTES:
            raise serializers.ValidationError("Ukuran selfie maksimal 2 MB.")
        return value

    def validate(self, attrs):
        if (attrs.get("latitude") is None) != (attrs.get("longitude") is None):
            raise serializers.ValidationError("Lintang dan bujur harus dikirim bersama.")
        return attrs


def event_payload(event):
    return {
        "id": str(event.id),
        "kind": event.kind,
        "kind_label": event.get_kind_display(),
        "date": event.day.date.isoformat(),
        "occurred_at": event.occurred_at.isoformat(),
        "site": {"id": str(event.site.id), "name": event.site.name} if event.site else None,
        "distance_m": event.distance_m,
        "accuracy_m": float(event.accuracy_m) if event.accuracy_m is not None else None,
        "flags": event.flags,
        "flag_labels": event.flag_labels,
        "has_selfie": bool(event.selfie),
    }
