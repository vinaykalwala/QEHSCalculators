from django.shortcuts import redirect
from .models import UserDevice

class DeviceLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated:
            device_id = request.session.session_key or request.COOKIES.get("device_id")
            subscription = user.subscriptions.filter(status="active").last()
            if subscription:
                limit = subscription.plan.device_limit
                active_devices = UserDevice.objects.filter(user=user).count()
                if device_id and active_devices >= limit and not UserDevice.objects.filter(user=user, device_id=device_id).exists():
                    return redirect("dashboard")  # Can show message: "Device limit exceeded"
                if device_id:
                    UserDevice.objects.get_or_create(user=user, device_id=device_id)
        response = self.get_response(request)
        return response
