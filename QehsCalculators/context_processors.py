from django.db.models import Q
from .models import UserSubscription

def subscription_context(request):
    subscription = None
    can_access_calculators = False
    pending_subscriptions_count = 0

    if request.user.is_authenticated:
        # Get latest active or pending subscription
        subscription = request.user.subscriptions.filter(
            Q(status="active") | Q(status="pending")
        ).order_by('-created_at').first()

        # User can access calculators only if active
        can_access_calculators = bool(subscription and subscription.is_active)

        # Count all pending requests (for admin badge)
        pending_subscriptions_count = UserSubscription.objects.filter(status="pending").count()

    return {
        "subscription": subscription,
        "can_access_calculators": can_access_calculators,
        "pending_subscriptions_count": pending_subscriptions_count,
    }
