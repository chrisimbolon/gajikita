from django.contrib import admin

from .models import LeaveRequest


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ("employee", "kind", "start_date", "end_date", "days", "status", "source", "organization")
    list_filter = ("status", "kind", "source", "organization")
    search_fields = ("employee__full_name", "employee__employee_no")
    raw_id_fields = ("employee", "requested_by", "decided_by")
