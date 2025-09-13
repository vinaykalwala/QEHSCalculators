from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from datetime import timedelta
from .utils.email_utils import send_subscription_email


class CustomUser(AbstractUser):
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    company_name = models.CharField(max_length=255, blank=True, null=True)
    designation = models.CharField(max_length=100, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    industry = models.CharField(max_length=100, blank=True, null=True)
    purpose = models.CharField(max_length=255, blank=True, null=True)
    profile_image = models.ImageField(upload_to="profile_images/", blank=True, null=True)

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
    STATUS_CHOICES = [
        ("pending", "Pending Approval"), 
        ("active", "Active"), 
        ("rejected", "Rejected"),
        ("expired", "Expired"), 
        ("cancelled", "Cancelled"),
        ("upgraded", "Upgraded")
    ]

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="subscriptions")
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.SET_NULL, null=True)
    start_date = models.DateTimeField(blank=True, null=True)
    end_date = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    razorpay_order_id = models.CharField(max_length=200, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=200, blank=True, null=True)
    razorpay_signature = models.CharField(max_length=200, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    previous_subscription = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='upgraded_subscriptions'
    )
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    is_upgrade = models.BooleanField(default=False)

    def activate(self):
        """
        Activate the subscription. For upgrades, set start date to now but preserve end date.
        For new subscriptions, set both start and end dates.
        """
        # Set start date to current time for both upgrades and new subscriptions
        self.start_date = timezone.now()
        
        # For upgrades, preserve the existing end date that was set during creation
        if self.is_upgrade and self.end_date:
            # Keep the existing end date, only update start date and status
            self.status = "active"
            self.save(update_fields=['start_date', 'status'])
            return
        
        # For new subscriptions, set end date based on plan duration
        if self.plan:
            self.end_date = self.start_date + timedelta(days=self.plan.duration_days)
        
        self.status = "active"
        self.save()

    def calculate_remaining_days(self):
        """Calculate remaining days from previous subscription for upgrades"""
        if not self.previous_subscription or not self.previous_subscription.end_date:
            return 0
        
        # Calculate days remaining in previous subscription
        time_remaining = self.previous_subscription.end_date - timezone.now()
        remaining_days = max(0, time_remaining.days)
        return remaining_days

    # def check_and_update_expiration(self):
    #     """Check and update expiration status if needed"""
    #     if (self.status == "active" and 
    #         self.end_date and 
    #         self.end_date < timezone.now()):
    #         self.status = "expired"
    #         self.save(update_fields=['status'])
    #         return True
    #     return False
    
    def check_and_update_expiration(self):
        """Expire subscription if needed and send email once after expiry."""
        now = timezone.now()

        if self.status == "active" and self.end_date and self.end_date < now:
            self.status = "expired"
            self.save(update_fields=['status'])

            # Send email AFTER expiry
            send_subscription_email(
                self.user,
                "Your Subscription has Expired",
                f"Hello {self.user.username},\n\n"
                f"We wanted to let you know that your subscription plan '{self.plan}' has expired on {self.end_date.strftime('%Y-%m-%d %H:%M')}.\n\n"
                "To continue enjoying access to our calculators and features, please subscribe again to your previous plan.\n\n"
                "Thank you for being with us!\n\n"
                "Best Regards,\n"
                "The QehsCalculators Team"
            )
            return True
        return False


    @property
    def is_active(self):
        # Always check expiration when accessing this property
        self.check_and_update_expiration()
        return self.status == "active"
    
    def mark_as_upgraded(self):
        """Mark this subscription as upgraded (for previous subscriptions)"""
        self.status = "upgraded"
        self.save(update_fields=['status'])

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        # Auto-check expiration before saving
        if self.pk and self.status == "active":
            original = UserSubscription.objects.get(pk=self.pk)
            if (original.end_date and 
                original.end_date < timezone.now()):
                self.status = "expired"
        super().save(*args, **kwargs)
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


class Contact(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=15)  # Added phone number
    subject = models.CharField(max_length=200)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.subject}"
    


class BlogPost(models.Model):
    CATEGORY_CHOICES = [
        ('quality', 'Quality'),
        ('environment', 'Environment'),
        ('health', 'Health'),
        ('safety', 'Safety'),
        ('fire', 'Fire'),
    ]

    title = models.CharField(max_length=200)
    author = models.CharField(max_length=100) 
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    content = models.TextField()  
    featured_image = models.ImageField(upload_to='blog_images/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_published = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.get_category_display()})"


class Training(models.Model):
    CATEGORY_CHOICES = [
        ("quality", "Quality"),
        ("environment", "Environment"),
        ("health", "Health"),
        ("safety", "Safety"),
        ("fire", "Fire"),
        ("other", "Other"),
    ]

    title = models.CharField(max_length=200)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default="other")
    media = models.FileField(upload_to="trainings/media/",blank=True,null=True,help_text="Upload any file (Image Or Promo video)")
    external_video_url = models.URLField(blank=True,null=True,help_text="Optional external video URL (e.g., YouTube, Vimeo)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.title} ({self.get_category_display()})"
