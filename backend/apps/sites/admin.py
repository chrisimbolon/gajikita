from django.contrib import admin

from .models import Shift, Site, SiteLocation


class SiteLocationInline(admin.TabularInline):
    # organization is filled from the site on save (SiteLocation._resolve_organization).
    # To move a pin, ADD a new row with a later "valid from" — don't edit the old one.
    model = SiteLocation
    extra = 0
    fields = ("latitude", "longitude", "radius_m", "valid_from")
    ordering = ("-valid_from",)


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "project_code", "organization", "is_active")
    list_filter = ("kind", "is_active", "organization")
    search_fields = ("name", "project_code")
    inlines = [SiteLocationInline]


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("name", "start_time", "end_time", "grace_minutes", "working_days", "organization", "is_active")
    list_filter = ("is_active", "organization")
