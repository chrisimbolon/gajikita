from django.contrib import admin

from .models import PayrollSettings, PayRun, PayRunItem, PayRunLine


@admin.register(PayrollSettings)
class PayrollSettingsAdmin(admin.ModelAdmin):
    list_display = ("organization", "period_start_day", "pay_day", "overtime_mode", "updated_at")


class PayRunItemInline(admin.TabularInline):
    model = PayRunItem
    extra = 0


@admin.register(PayRun)
class PayRunAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "period_start", "period_end", "status")
    list_filter = ("status", "organization")


@admin.register(PayRunLine)
class PayRunLineAdmin(admin.ModelAdmin):
    list_display = ("run", "employee", "gross", "deductions", "net", "warning_count")
    raw_id_fields = ("run", "employee")
    inlines = [PayRunItemInline]
