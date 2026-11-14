from django.contrib import admin

from .models import (AttendanceDay, AttendanceExemption, ClockEvent, CompanyEvent, DayNote, EmployeeMachineId,
                     FingerprintMachine)


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


@admin.register(AttendanceExemption)                                      # G12i
class AttendanceExemptionAdmin(admin.ModelAdmin):
    list_display = ("employee", "start", "end", "reason", "organization")
    list_filter = ("organization",)
    search_fields = ("employee__full_name", "employee__employee_no", "reason")
    raw_id_fields = ("employee", "created_by")


@admin.register(CompanyEvent)                                             # G17-2
class CompanyEventAdmin(admin.ModelAdmin):
    list_display = ("kind", "start", "end", "reason", "everyone", "organization")
    list_filter = ("organization", "kind")
    search_fields = ("reason",)
    filter_horizontal = ("sites", "employees")
    raw_id_fields = ("created_by",)


@admin.register(DayNote)                                                  # G12f.3.1
class DayNoteAdmin(admin.ModelAdmin):
    list_display = ("date", "employee", "code", "text", "source", "organization")
    list_filter = ("organization", "source", "code")
    search_fields = ("employee__full_name", "employee__employee_no", "text")
    raw_id_fields = ("employee", "created_by")
    date_hierarchy = "date"
