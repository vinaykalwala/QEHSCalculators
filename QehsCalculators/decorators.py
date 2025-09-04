# decorators.py
from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps
from .access_map import PLAN_HIERARCHY

def subscription_required(plan_type="individual"):
    """
    Restrict access based on subscription plan.
    Higher plans can access lower plan calculators.
    Also checks device limit.
    Superusers have access to all calculators regardless of subscription.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # Allow superusers to bypass all checks
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            
            # Check subscription
            subscription = request.user.subscriptions.filter(status="active").last()
            if not subscription:
                messages.warning(request, "You need an active subscription to access this calculator.")
                return redirect("dashboard")

            # Check plan level
            user_plan = subscription.plan.name.lower()
            user_level = PLAN_HIERARCHY.get(user_plan, 0)
            required_level = PLAN_HIERARCHY.get(plan_type.lower(), 0)
            if user_level < required_level:
                messages.warning(request, f"Your {subscription.plan.name} plan does not allow access to this calculator.")
                return redirect("dashboard")

            # Check device limit
            device_id = request.session.session_key or request.COOKIES.get('sessionid')
            devices_count = request.user.devices.count()
            if not request.user.devices.filter(device_id=device_id).exists():
                if devices_count >= subscription.plan.device_limit:
                    messages.warning(request, "Device limit exceeded. Logout from other devices to access this calculator.")
                    return redirect("dashboard")
                else:
                    request.user.devices.create(device_id=device_id)

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator