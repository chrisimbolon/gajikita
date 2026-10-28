from django.contrib import admin

from .models import Employee


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("employee_no", "full_name", "organization", "employment_type", "pay_type",
                    "default_site", "default_shift", "status")
    list_filter = ("status", "employment_type", "pay_type", "organization")
    search_fields = ("employee_no", "full_name", "phone", "login_phone")
    readonly_fields = ("login_phone", "must_change_pin", "pin_failed_attempts", "pin_locked_until")
    filter_horizontal = ("sites",)
    raw_id_fields = ("mandor", "user")
