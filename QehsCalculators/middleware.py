# from django.shortcuts import redirect
# from .models import Subscription

# class SubscriptionMiddleware:
#     def __init__(self, get_response):
#         self.get_response = get_response

#     def __call__(self, request):
#         if request.user.is_authenticated and 'admin' not in request.path:
#             sub = Subscription.objects.get(user=request.user)
#             if sub.is_expired():
#                 if 'pricing' not in request.path:
#                     return redirect('pricing')
#         response = self.get_response(request)
#         return response