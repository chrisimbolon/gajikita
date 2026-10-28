# =============================================================================
# === backend/apps/attendance/views.py ===
# =============================================================================
"""
The worker's side of attendance (G1, backend only):

  POST /api/attendance/clock/  record a tap: Masuk / Pindah lokasi / Pulang
  GET  /api/attendance/today/  my sites (with pins) and my taps today, for the phone app

Both act on the Employee linked to the logged-in user. HR's screens
(exceptions queue, attendance data) come in G3.
"""
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.employees.models import Employee

from .geofence import FLAG_LABELS, Flag
from .models import AttendanceDay, ClockEvent
from .serializers import ClockInputSerializer, event_payload
from .services import open_day, record_clock_event

NOT_AN_EMPLOYEE = "Akun ini belum terhubung ke data karyawan aktif."
DONE = {ClockEvent.Kind.IN: "Masuk tercatat", ClockEvent.Kind.SWITCH: "Pindah lokasi tercatat",
        ClockEvent.Kind.OUT: "Pulang tercatat"}
# Flags worth telling the worker about straight away; the rest only HR sees.
TELL_WORKER = (Flag.LOW_ACCURACY, Flag.NO_GPS, Flag.NO_SITE, Flag.NO_PIN, Flag.TIME_GAP,
               Flag.NO_SELFIE, Flag.NO_CLOCK_IN, Flag.ALREADY_IN)


def _my_employee(user):
    return (Employee.objects.filter(user=user, status=Employee.Status.ACTIVE)
            .select_related("organization", "default_site", "default_shift").first())


def _message(event):
    text = DONE[event.kind]
    if Flag.OUTSIDE_SITE in event.flags:
        return f"{text}. Di luar lokasi ({event.distance_m} m), HR akan meninjau."
    notes = [FLAG_LABELS[f] for f in event.flags if f in TELL_WORKER]
    return f"{text}. HR akan meninjau: {', '.join(notes)}." if notes else f"{text}."


class ClockView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        employee = _my_employee(request.user)
        if employee is None:
            return Response({"success": False, "message": NOT_AN_EMPLOYEE}, status=status.HTTP_403_FORBIDDEN)
        ser = ClockInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        site = None
        if data.get("site_id"):
            site = next((s for s in employee.candidate_sites() if s.id == data["site_id"]), None)
            if site is None:
                return Response({"success": False, "message": "Lokasi tidak tersedia untuk karyawan ini."},
                                status=status.HTTP_400_BAD_REQUEST)

        event, created = record_clock_event(
            employee=employee, kind=data["kind"],
            latitude=data.get("latitude"), longitude=data.get("longitude"), accuracy_m=data.get("accuracy"),
            phone_time=data.get("phone_time"), queued=data.get("queued", False),
            client_id=data.get("client_id"), site=site, selfie=data.get("selfie"),
        )
        return Response({"success": True, "event": event_payload(event), "message": _message(event)},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class TodayView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        employee = _my_employee(request.user)
        if employee is None:
            return Response({"success": False, "message": NOT_AN_EMPLOYEE}, status=status.HTTP_403_FORBIDDEN)
        now = timezone.now()
        current = open_day(employee, now)
        day = current or AttendanceDay.objects.filter(employee=employee, date=timezone.localdate(now)).first()
        sites = []
        for s in employee.candidate_sites():
            loc = s.location_at(now)
            sites.append({
                "id": str(s.id), "name": s.name, "kind": s.kind, "kind_label": s.get_kind_display(),
                "latitude": float(loc.latitude) if loc else None,
                "longitude": float(loc.longitude) if loc else None,
                "radius_m": loc.radius_m if loc else None,
            })
        shift = employee.default_shift
        return Response({
            "success": True,
            "must_change_pin": employee.must_change_pin,
            "employee": {"id": str(employee.id), "employee_no": employee.employee_no, "full_name": employee.full_name},
            "shift": {"name": shift.name, "start": f"{shift.start_time:%H:%M}", "end": f"{shift.end_time:%H:%M}"}
                     if shift else None,
            "sites": sites,
            "clocked_in": current is not None,
            "date": day.date.isoformat() if day else timezone.localdate(now).isoformat(),
            "events": [event_payload(e) for e in day.events.select_related("site", "day")] if day else [],
        })
