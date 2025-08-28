from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (CustomUser,
                     SubscriptionPlan, UserSubscription, UserDevice, Transaction)

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ("email", "username", "company_name", "is_staff", "is_active")
    fieldsets = UserAdmin.fieldsets + (("Extra", {"fields": ("phone","company_name","designation","address","industry","purpose")}),)
    search_fields = ("email", "username", "company_name")

@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "calculators_per_category", "device_limit", "duration_days", "is_active")

@admin.action(description="Approve selected subscriptions")
def approve_subscriptions(modeladmin, request, queryset):
    for s in queryset:
        s.activate()
    modeladmin.message_user(request, "Selected subscriptions approved.")

@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "status", "start_date", "end_date", "created_at")
    list_filter = ("status", "plan")
    actions = [approve_subscriptions]

@admin.register(UserDevice)
class UserDeviceAdmin(admin.ModelAdmin):
    list_display = ("user", "device_id", "last_seen")
    search_fields = ("user__email", "device_id")

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("subscription", "razorpay_order_id", "amount", "currency", "created_at")
    readonly_fields = ("payload",)
