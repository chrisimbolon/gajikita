# =============================================================================
# === backend/config/urls.py ===
# =============================================================================
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.core.health import HealthView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/",        HealthView.as_view(), name="health"),
    path("api/auth/",          include("apps.authentication.urls")),
    path("api/organizations/", include("apps.organizations.urls")),
    path("api/attendance/",    include("apps.attendance.urls")),
    path("api/worker/",        include("apps.employees.urls")),
    path("api/hr/",            include("apps.employees.hr_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
