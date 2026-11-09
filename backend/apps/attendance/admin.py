from django.contrib import admin

from .models import AttendanceDay, ClockEvent, EmployeeMachineId, FingerprintMachine


class ClockEventInline(admin.TabularInline):
    model = ClockEvent
    extra = 0
    can_delete = False
    fields = ("kind", "source", "occurred_at", "site", "distance_m", "accuracy_m", "flags", "selfie")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(AttendanceDay)
class AttendanceDayAdmin(admin.ModelAdmin):
    list_display = ("date", "employee", "shift", "organization", "is_locked")
    list_filter = ("date", "organization")
    search_fields = ("employee__full_name", "employee__employee_no")
    readonly_fields = ("organization", "employee", "date")
    inlines = [ClockEventInline]


class EmployeeMachineIdInline(admin.TabularInline):                     # G12f.1a
    model = EmployeeMachineId
    extra = 0
    fields = ("employee", "fingerprint_id")
    raw_id_fields = ("employee",)


@admin.register(FingerprintMachine)
class FingerprintMachineAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "dept_labels", "is_active")
    list_filter = ("organization", "is_active")
    inlines = [EmployeeMachineIdInline]
