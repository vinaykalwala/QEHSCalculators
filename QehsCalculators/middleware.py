from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin
from .models import UserDevice

class DeviceLimitMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if not request.user.is_authenticated:
            return None

        # Check ALL subscriptions for expiration (not just the latest)
        active_subscriptions = request.user.subscriptions.filter(status="active")
        expired_found = False
        
        for sub in active_subscriptions:
            if sub.check_and_update_expiration():  # This will save if expired
                expired_found = True
                # If this was the user's only active subscription, log them out
                if sub == active_subscriptions.last():
                    logout(request)
                    return redirect("subscription_expired")

        # Get latest active subscription after expiration checks
        latest_sub = request.user.subscriptions.filter(status="active").last()

        # If user had active subscriptions but all expired now
        if expired_found and not latest_sub:
            logout(request)
            return redirect("subscription_expired")

        # If no active subscription, stop further checks
        if not latest_sub:
            return None

        # --- Device Limit Enforcement ---
        device_id = request.session.session_key
        if not device_id:
            request.session.save()
            device_id = request.session.session_key

        limit = getattr(latest_sub.plan, "device_limit", None)
        if limit is not None:
            active_devices = UserDevice.objects.filter(user=request.user).count()
            exempt_paths = ["/device-limit/", "/logout/", "/login/", "/subscription-expired/"]

            if request.path not in exempt_paths:
                device_exists = UserDevice.objects.filter(user=request.user, device_id=device_id).exists()
                if active_devices >= limit and not device_exists:
                    return redirect("device_limit_exceeded")

            UserDevice.objects.get_or_create(user=request.user, device_id=device_id)

        return None