# =============================================================================
# === backend/apps/authentication/urls.py ===
# =============================================================================
from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import ChangePasswordView, MeView, RegisterView

urlpatterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("login/",     TokenObtainPairView.as_view(), name="auth-login"),
    path("refresh/",   TokenRefreshView.as_view(), name="auth-refresh"),
    path("me/",         MeView.as_view(), name="auth-me"),
    path("password/",   ChangePasswordView.as_view(), name="auth-password"),          # G22-1
]
