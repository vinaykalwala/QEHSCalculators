# from django.contrib.auth.models import AbstractUser
# from django.db import models
# from django.utils import timezone
# from dateutil.relativedelta import relativedelta

# class CustomUser(AbstractUser):
#     name = models.CharField(max_length=100, blank=True)
#     phone_number = models.CharField(max_length=15, blank=True)
#     company = models.CharField(max_length=100, blank=True)
#     date_joined = models.DateTimeField(default=timezone.now)

#     def __str__(self):
#         return self.email

# class Category(models.Model):
#     name = models.CharField(max_length=100)
    
#     def __str__(self):
#         return self.name

# class Calculator(models.Model):
#     name = models.CharField(max_length=200)
#     slug = models.SlugField(unique=True)
#     category = models.ForeignKey(Category, on_delete=models.CASCADE)
#     description = models.TextField()
#     template_name = models.CharField(max_length=200)  # e.g., 'calculators/health/bmi.html'

#     class Meta:
#         ordering = ['name']
    
#     def __str__(self):
#         return self.name

# class Plan(models.Model):
#     name = models.CharField(max_length=50, unique=True)
#     price = models.DecimalField(max_digits=10, decimal_places=2)
#     period = models.CharField(max_length=50)  # 'free', 'month', 'year'
#     access_limit_per_category = models.IntegerField()  # 2 for Free, 15 for Basic, 0 for unlimited

#     def __str__(self):
#         return self.name

# class Subscription(models.Model):
#     user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
#     plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True)
#     start_date = models.DateTimeField(auto_now_add=True)
#     end_date = models.DateTimeField(null=True, blank=True)
#     active = models.BooleanField(default=True)

#     def save(self, *args, **kwargs):
#         if self.plan.name == 'Free':
#             self.end_date = None
#         elif self.plan.period == 'month':
#             self.end_date = timezone.now() + relativedelta(months=1)
#         elif self.plan.period == 'year':
#             self.end_date = timezone.now() + relativedelta(years=1)
#         super().save(*args, **kwargs)

#     def is_expired(self):
#         if self.end_date and timezone.now() > self.end_date:
#             self.active = False
#             self.save()
#             return True
#         return False

#     def __str__(self):
#         return f"{self.user.email} - {self.plan}"

# class UsageHistory(models.Model):
#     user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
#     calculator = models.ForeignKey(Calculator, on_delete=models.CASCADE)
#     timestamp = models.DateTimeField(auto_now_add=True)

#     class Meta:
#         ordering = ['-timestamp']