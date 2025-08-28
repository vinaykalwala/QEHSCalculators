from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
import razorpay
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
import razorpay
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from .models import CustomUser, SubscriptionPlan, UserSubscription, Transaction, UserDevice
from .access_map import CALCULATORS, PLAN_HIERARCHY, CATEGORIES 
from .decorators import subscription_required
import json

# Razorpay client
client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

def check_device_limit(user, plan):
    """Check if the user has exceeded their device limit."""
    device_count = UserDevice.objects.filter(user=user).count()
    if device_count >= plan.device_limit:
        return False, f"You have reached the maximum device limit ({plan.device_limit}) for your plan."
    return True, None

@login_required
def dashboard(request):
    subscription = request.user.subscriptions.filter(status="active").last()
    user_level = PLAN_HIERARCHY.get(subscription.plan.name.lower(), 0) if subscription else 0

    # Organize calculators by category with access control
    accessible_calculators_by_category = {}
    
    for calc in CALCULATORS:
        calc_plan_level = PLAN_HIERARCHY.get(calc["plan_type"].lower(), 3)
        if subscription and calc_plan_level <= user_level:
            category = calc["category"]
            if category not in accessible_calculators_by_category:
                accessible_calculators_by_category[category] = []
            accessible_calculators_by_category[category].append(calc)

    # Get all categories that have accessible calculators
    accessible_categories = {}
    for category_id, category_info in CATEGORIES.items():
        if category_id in accessible_calculators_by_category:
            accessible_categories[category_id] = category_info

    plans = SubscriptionPlan.objects.filter(is_active=True)

    device_message = None
    if subscription:
        is_allowed, device_message = check_device_limit(request.user, subscription.plan)
        if not is_allowed:
            messages.warning(request, device_message)

    return render(request, "dashboard.html", {
        "subscription": subscription,
        "calculators_by_category": accessible_calculators_by_category,
        "categories": accessible_categories,
        "plans": plans,
        "user": request.user
    })

from django.urls import reverse

# Razorpay client
client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

@login_required
def subscribe_plan(request, plan_id):
    plan = get_object_or_404(SubscriptionPlan, id=plan_id, is_active=True)
    
    existing_subscription = request.user.subscriptions.filter(status="active").last()
    if existing_subscription:
        messages.warning(request, "You already have an active subscription. Please cancel or wait for it to expire.")
        return redirect("dashboard")

    is_allowed, device_message = check_device_limit(request.user, plan)
    if not is_allowed:
        messages.error(request, device_message)
        return redirect("dashboard")

    amount_in_paise = int(plan.price * 100)
    
    if amount_in_paise < 100:
        messages.error(request, "Plan amount is too low for payment processing.")
        return redirect("dashboard")

    order_data = {
        "amount": amount_in_paise,
        "currency": "INR",
        "payment_capture": 1
    }
    
    try:
        razorpay_order = client.order.create(data=order_data)
    except razorpay.errors.BadRequestError as e:
        messages.error(request, "Failed to create payment order. Please try again later.")
        return redirect("dashboard")

    # Store order details in session instead of creating database records
    request.session['pending_subscription'] = {
        'plan_id': plan.id,
        'razorpay_order_id': razorpay_order["id"],
        'amount': str(plan.price),
        'order_data': razorpay_order
    }

    # Return the payment page with Razorpay integration
    context = {
        "plan": plan,
        "razorpay_order": razorpay_order,
        "razorpay_key_id": settings.RAZORPAY_KEY_ID,
        "callback_url": request.build_absolute_uri(reverse('payment_success')),
        "error_url": request.build_absolute_uri(reverse('payment_failed')),
    }
    return render(request, "subscribe_payment.html", context)

def verify_payment_signature(order_id, payment_id, signature):
    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature
        })
        return True
    except razorpay.errors.SignatureVerificationError:
        return False

@login_required
@csrf_exempt
def payment_success(request):
    if request.method == "POST":
        data = request.POST
        order_id = data.get("razorpay_order_id")
        payment_id = data.get("razorpay_payment_id")
        signature = data.get("razorpay_signature")
        
        if not order_id:
            messages.error(request, "No Razorpay order ID provided.")
            return redirect("dashboard")
            
        # Get pending subscription from session
        pending_subscription = request.session.get('pending_subscription')
        if not pending_subscription or pending_subscription.get('razorpay_order_id') != order_id:
            messages.error(request, "No pending subscription found for this order.")
            return redirect("dashboard")
            
        # Verify payment signature
        if not verify_payment_signature(order_id, payment_id, signature):
            messages.error(request, "Payment verification failed.")
            # Clear the pending subscription from session
            if 'pending_subscription' in request.session:
                del request.session['pending_subscription']
            return redirect("payment_failed")
            
        # Get the plan
        try:
            plan = SubscriptionPlan.objects.get(id=pending_subscription['plan_id'])
        except SubscriptionPlan.DoesNotExist:
            messages.error(request, "The subscription plan is no longer available.")
            return redirect("dashboard")
            
        # Create subscription only after successful payment verification
        subscription = UserSubscription.objects.create(
            user=request.user,
            plan=plan,
            razorpay_order_id=order_id,
            razorpay_payment_id=payment_id,
            razorpay_signature=signature,
            status="pending",
            start_date=None,
            end_date=None
        )

        # Create transaction record
        transaction = Transaction.objects.create(
            subscription=subscription,
            razorpay_order_id=order_id,
            razorpay_payment_id=payment_id,
            amount=plan.price,
            currency="INR",
            payload={
                "order": pending_subscription['order_data'],
                "payment_id": payment_id,
                "signature": signature,
                "verified": True
            }
        )
        
        # Activate subscription if it's an individual plan
        requires_approval = True
        if plan.name.lower() == "individual":
            subscription.activate()
            requires_approval = False
            messages.success(request, "Payment successful! Your subscription is now active.")
        else:
            subscription.status = "pending"
            subscription.save()
            messages.success(request, "Payment successful! Waiting for admin approval.")

        # Clear the pending subscription from session
        if 'pending_subscription' in request.session:
            del request.session['pending_subscription']

        return render(request, "payment_success.html", {
            "subscription": subscription,
            "requires_approval": requires_approval
        })
    else:
        messages.error(request, "Invalid request method.")
        return redirect("dashboard")

@login_required
def payment_failed(request):
    # Clear any pending subscription from session
    if 'pending_subscription' in request.session:
        del request.session['pending_subscription']
        
    return render(request, "payment_failed.html")

@login_required
def approve_subscription(request, subscription_id):
    if not request.user.is_staff:
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("dashboard")

    subscription = get_object_or_404(UserSubscription, id=subscription_id)
    if subscription.status == "pending":
        subscription.activate()
        messages.success(request, f"Subscription for {subscription.user.email} activated.")
    else:
        messages.warning(request, "Subscription is not in pending state.")
    
    return redirect("dashboard")

@csrf_exempt
def razorpay_webhook(request):
    if request.method == "POST":
        data = json.loads(request.body)
        event = data.get("event")
        if event == "payment.captured":
            order_id = data["payload"]["payment"]["entity"]["order_id"]
            payment_id = data["payload"]["payment"]["entity"]["id"]
            try:
                subscription = UserSubscription.objects.get(razorpay_order_id=order_id)
                subscription.razorpay_payment_id = payment_id
                if subscription.plan.name.lower() == "individual":
                    subscription.activate()
                else:
                    subscription.status = "pending"
                subscription.save()

                transaction = Transaction.objects.filter(razorpay_order_id=order_id).last()
                if transaction:
                    transaction.razorpay_payment_id = payment_id
                    transaction.payload.update({"payment_id": payment_id})
                    transaction.save()
            except UserSubscription.DoesNotExist:
                return JsonResponse({"status": "no_subscription"}, status=400)
        return JsonResponse({"status": "ok"})
    return JsonResponse({"status": "invalid"}, status=400)

# Other views (home, about, etc.) remain unchanged as per previous code
def home(request):
    return render(request, 'home.html')

def about(request):
    return render(request, 'about.html')

def quality_calculators(request):
    return render(request, 'calculators/quality.html', {'title': 'Quality Calculators'})

def environment_calculators(request):
    return render(request, 'calculators/environment.html', {'title': 'Environment Calculators'})

def health_calculators(request):
    return render(request, 'calculators/health.html', {'title': 'Health Calculators'})

def safety_calculators(request):
    return render(request, 'calculators/safety.html', {'title': 'Safety Calculators'})

def fire_calculators(request):
    return render(request, 'calculators/fire.html', {'title': 'Fire Calculators'})

def disclaimer(request):
    return render(request, 'disclaimer.html', {'title': 'Disclaimer'})

def contact(request):
    if request.method == 'POST':
        pass  # Handle form submission
    return render(request, 'contact.html')

def terms(request):
    return render(request, 'terms.html')

def privacy(request):
    return render(request, 'privacy.html')

def upgrade_required(request):
    return render(request, 'upgrade_required.html')

<<<<<<< HEAD
def accident_rate_calculator(request):
    return render(request, 'qehsfcalculators/Safety/accident_rate_calculator.html')
=======
from .forms import CustomUserCreationForm, CustomAuthenticationForm
from django.contrib.auth import login, logout, authenticate

def signup_view(request):
    if request.method == "POST":
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, "Account created successfully. Please log in.")
            return redirect("login")
    else:
        form = CustomUserCreationForm()
    return render(request, "signup.html", {"form": form})

def login_view(request):
    if request.method == "POST":
        form = CustomAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            email = form.cleaned_data.get("username")
            password = form.cleaned_data.get("password")
            user = authenticate(request, email=email, password=password)
            if user is not None:
                login(request, user)
                return redirect("dashboard")
            else:
                messages.error(request, "Invalid email or password.")
    else:
        form = CustomAuthenticationForm()
    return render(request, "login.html", {"form": form})

def logout_view(request):
    logout(request)
    messages.success(request, "Logged out successfully.")
    return redirect("home")

def fire_calculator(request):
    return render(request, 'calculators/fire.html', {'title': 'Fire Calculator'})

@login_required
@subscription_required(plan_type="employee")
def co2_calculator(request):
    return render(request, 'calculators/co2_emission.html', {'title': 'CO2 Emission Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def profit_calculator(request):
    return render(request, 'calculators/profit.html', {'title': 'Profit Calculator'})
>>>>>>> 5f5a572b3189a89dd637d2c5bc5493c2f1a61a6a
