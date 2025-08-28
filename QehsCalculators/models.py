from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from datetime import timedelta

class CustomUser(AbstractUser):
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    company_name = models.CharField(max_length=255, blank=True, null=True)
    designation = models.CharField(max_length=100, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    industry = models.CharField(max_length=100, blank=True, null=True)
    purpose = models.CharField(max_length=255, blank=True, null=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    def __str__(self):
        return self.email

class SubscriptionPlan(models.Model):
    PLAN_CHOICES = [("individual", "Individual"), ("employee", "Employee"), ("corporate", "Corporate")]
    name = models.CharField(max_length=30, choices=PLAN_CHOICES, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    calculators_per_category = models.IntegerField(default=0)
    device_limit = models.IntegerField(default=1)
    duration_days = models.IntegerField(default=30)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.get_name_display()


class UserSubscription(models.Model):
    STATUS_CHOICES = [("pending", "Pending Approval"), ("active", "Active"), ("rejected", "Rejected"),
                      ("expired", "Expired"), ("cancelled", "Cancelled")]

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="subscriptions")
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.SET_NULL, null=True)
    start_date = models.DateTimeField(blank=True, null=True)
    end_date = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    razorpay_order_id = models.CharField(max_length=200, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=200, blank=True, null=True)
    razorpay_signature = models.CharField(max_length=200, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def activate(self):
        self.start_date = timezone.now()
        if self.plan:
            self.end_date = self.start_date + timedelta(days=self.plan.duration_days)
        self.status = "active"
        self.save()

    @property
    def is_active(self):
        return self.status == "active" and self.end_date and self.end_date >= timezone.now()


class UserDevice(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="devices")
    device_id = models.CharField(max_length=255)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "device_id")

    def __str__(self):
        return f"{self.user.email} @{self.device_id}"


class Transaction(models.Model):
    subscription = models.ForeignKey(UserSubscription, on_delete=models.CASCADE, related_name="transactions")
    razorpay_order_id = models.CharField(max_length=200)
    razorpay_payment_id = models.CharField(max_length=200, blank=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default="INR")
    created_at = models.DateTimeField(auto_now_add=True)
    payload = models.JSONField(blank=True, null=True)

    def __str__(self):
        return f"Txn {self.razorpay_order_id} for {self.subscription.user.email}"
