from django.db.models import Q

def subscription_context(request):
    subscription = None
    can_access_calculators = False

    if request.user.is_authenticated:
        # Get latest active or pending subscription
        subscription = request.user.subscriptions.filter(
            Q(status="active") | Q(status="pending")
        ).order_by('-created_at').first()

        # User can access calculators only if active
        can_access_calculators = bool(subscription and subscription.is_active)

    return {
        'subscription': subscription,
        'can_access_calculators': can_access_calculators
    }
