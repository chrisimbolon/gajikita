from django.contrib import admin

from .models import AttendanceDay, ClockEvent


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
