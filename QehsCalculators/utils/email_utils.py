# QehsCalculators/utils/email_utils.py
from django.core.mail import send_mail
from django.conf import settings

def send_subscription_email(user, subject, message):
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=True,
    )
