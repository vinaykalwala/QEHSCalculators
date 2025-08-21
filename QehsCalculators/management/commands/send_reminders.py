# from django.core.management.base import BaseCommand
# from django.core.mail import send_mail
# from QehsCalculators.models import Subscription
# from datetime import timedelta
# from django.utils import timezone

# class Command(BaseCommand):
#     def handle(self, *args, **options):
#         near_expiry = Subscription.objects.filter(end_date__lte=timezone.now() + timedelta(days=3), active=True)
#         for sub in near_expiry:
#             send_mail(
#                 'Subscription Renewal Reminder',
#                 'Your subscription expires soon. Please renew on our pricing page.',
#                 'from@example.com',
#                 [sub.user.email],
#                 fail_silently=False,
#             )