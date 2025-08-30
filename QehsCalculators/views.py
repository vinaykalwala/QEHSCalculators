from datetime import timedelta
from decimal import Decimal
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
from django.db.models import Q


# Razorpay client
client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

def check_device_limit(user, plan):
    """Check if the user has exceeded their device limit."""
    device_count = UserDevice.objects.filter(user=user).count()
    if device_count >= plan.device_limit:
        return False, f"You have reached the maximum device limit ({plan.device_limit}) for your plan."
    return True, None


from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import UserDevice
from django.contrib import messages

@login_required
def device_limit_exceeded(request):
    devices = UserDevice.objects.filter(user=request.user)

    if request.method == "POST":
        devices.delete()
        messages.success(request, "All devices removed. You can log in again.")
        return redirect("logout")  # Or redirect to login page

    return render(request, "device_limit.html", {"devices": devices})


from django.db.models import Q  # Add this import at the top
@login_required
def dashboard(request):
    # Get the latest active or pending subscription
    subscription = request.user.subscriptions.filter(
        Q(status="active") | Q(status="pending")
    ).order_by('-created_at').first()

    # Determine user's plan level
    user_level = PLAN_HIERARCHY.get(subscription.plan.name.lower(), 0) if subscription and subscription.plan else 0

    # Organize calculators by category with access control
    accessible_calculators_by_category = {}

    for calc in CALCULATORS:
        calc_plan_level = PLAN_HIERARCHY.get(calc["plan_type"].lower(), 3)
        if subscription and subscription.status == "active" and calc_plan_level <= user_level:
            category = calc["category"]
            if category not in accessible_calculators_by_category:
                accessible_calculators_by_category[category] = []
            accessible_calculators_by_category[category].append(calc)

    # Get only categories with accessible calculators
    accessible_categories = {
        category_id: category_info
        for category_id, category_info in CATEGORIES.items()
        if category_id in accessible_calculators_by_category
    }

    # Get all active subscription plans
    plans = SubscriptionPlan.objects.filter(is_active=True).order_by('price')

    # Check device limit if subscription exists
    device_message = None
    if subscription and subscription.status == "active" and subscription.plan:
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
    
    # Calculate upgrade amount if user has an active subscription
    upgrade_amount = Decimal('0.00')
    credit_amount = Decimal('0.00')  # Add credit amount calculation
    original_end_date = None
    is_upgrade = False
    
    if existing_subscription:
        # Check if user is trying to upgrade to a higher plan
        if plan.price <= existing_subscription.plan.price:
            messages.warning(request, "You can only upgrade to a higher-priced plan.")
            return redirect("dashboard")
        
        # Store the original end date from the existing subscription
        original_end_date = existing_subscription.end_date
        
        # Calculate remaining value of current subscription
        total_days = (existing_subscription.end_date - existing_subscription.start_date).days
        elapsed_days = (timezone.now() - existing_subscription.start_date).days
        remaining_days = max(0, total_days - elapsed_days)
        
        if remaining_days > 0:
            # Calculate daily rate of current plan
            daily_rate_current = existing_subscription.plan.price / total_days
            # Calculate remaining value
            remaining_value = daily_rate_current * remaining_days
            
            # Calculate daily rate of new plan
            daily_rate_new = plan.price / total_days
            # Calculate value for remaining days in new plan
            new_value = daily_rate_new * remaining_days
            
            # Calculate upgrade amount (difference between plans for remaining period)
            upgrade_amount = max(Decimal('0.00'), new_value - remaining_value)
            # Calculate credit amount for display purposes
            credit_amount = remaining_value
        
        is_upgrade = True
        messages.info(request, f"Upgrading from {existing_subscription.plan.name}. Your subscription will continue until {original_end_date.strftime('%b. %d, %Y')}.")
    else:
        # Regular subscription - use full plan price
        upgrade_amount = plan.price
        credit_amount = Decimal('0.00')  # No credit for new subscriptions

    is_allowed, device_message = check_device_limit(request.user, plan)
    if not is_allowed:
        messages.error(request, device_message)
        return redirect("dashboard")

    amount_in_paise = int(upgrade_amount * 100)
    
    if amount_in_paise < 100:
        # If amount is too low, create subscription without payment
        if is_upgrade and existing_subscription:
            # Handle upgrade with minimal payment
            existing_subscription.mark_as_upgraded()
        
        # Create new subscription with the SAME end date as previous subscription
        start_date = timezone.now()
        if is_upgrade and original_end_date:
            end_date = original_end_date  # Use the original end date
        else:
            end_date = start_date + timedelta(days=plan.duration_days)
        
        # Create new subscription
        new_subscription = UserSubscription.objects.create(
            user=request.user,
            plan=plan,
            start_date=start_date,
            end_date=end_date,
            amount_paid=upgrade_amount,
            status="active" if plan.name.lower() == "individual" else "pending",
            previous_subscription=existing_subscription if is_upgrade else None,
            is_upgrade=is_upgrade
        )
        
        if plan.name.lower() == "individual":
            messages.success(request, f"Your plan has been upgraded to {plan.name}!")
        else:
            messages.success(request, f"Upgrade request submitted! Waiting for admin approval.")
        
        return redirect("dashboard")

    # Create Razorpay order
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

    # Store order details in session
    request.session['pending_subscription'] = {
        'plan_id': plan.id,
        'razorpay_order_id': razorpay_order["id"],
        'amount': str(upgrade_amount),
        'order_data': razorpay_order,
        'is_upgrade': is_upgrade,
        'existing_subscription_id': existing_subscription.id if existing_subscription else None,
        'original_end_date': original_end_date.isoformat() if original_end_date else None
    }

    # Return the payment page with Razorpay integration
    context = {
        "plan": plan,
        "razorpay_order": razorpay_order,
        "razorpay_key_id": settings.RAZORPAY_KEY_ID,
        "callback_url": request.build_absolute_uri(reverse('payment_success')),
        "error_url": request.build_absolute_uri(reverse('payment_failed')),
        "is_upgrade": is_upgrade,
        "upgrade_amount": upgrade_amount,
        "credit_amount": credit_amount,  # Add credit amount to context
        "existing_plan": existing_subscription.plan if existing_subscription else None
    }
    return render(request, "subscribe_payment.html", context)

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
            
        # Handle upgrade scenario
        is_upgrade = pending_subscription.get('is_upgrade', False)
        existing_subscription = None
        original_end_date = None
        
        if is_upgrade:
            existing_subscription_id = pending_subscription.get('existing_subscription_id')
            if existing_subscription_id:
                try:
                    existing_subscription = UserSubscription.objects.get(
                        id=existing_subscription_id, 
                        user=request.user
                    )
                    # Store the original end date BEFORE marking as upgraded
                    original_end_date = existing_subscription.end_date
                    # Mark old subscription as upgraded
                    existing_subscription.mark_as_upgraded()
                except UserSubscription.DoesNotExist:
                    messages.error(request, "Existing subscription not found.")
                    return redirect("dashboard")
            else:
                # Try to get original_end_date from session as fallback
                original_end_date_str = pending_subscription.get('original_end_date')
                if original_end_date_str:
                    original_end_date = timezone.datetime.fromisoformat(original_end_date_str)
        
        # Calculate start and end dates
        start_date = timezone.now()
        
        # For upgrades, use the original end date from the previous subscription
        if is_upgrade and original_end_date:
            end_date = original_end_date
        else:
            end_date = start_date + timedelta(days=plan.duration_days)
        
        # Create subscription only after successful payment verification
        subscription = UserSubscription.objects.create(
            user=request.user,
            plan=plan,
            razorpay_order_id=order_id,
            razorpay_payment_id=payment_id,
            razorpay_signature=signature,
            status="active" if plan.name.lower() == "individual" else "pending",
            start_date=start_date,
            end_date=end_date,
            amount_paid=Decimal(pending_subscription['amount']),
            previous_subscription=existing_subscription if is_upgrade else None,
            is_upgrade=is_upgrade
        )

        # Create transaction record
        transaction = Transaction.objects.create(
            subscription=subscription,
            razorpay_order_id=order_id,
            razorpay_payment_id=payment_id,
            amount=Decimal(pending_subscription['amount']),
            currency="INR",
            payload={
                "order": pending_subscription['order_data'],
                "payment_id": payment_id,
                "signature": signature,
                "verified": True,
                "is_upgrade": is_upgrade,
                "original_end_date": original_end_date.isoformat() if original_end_date else None
            }
        )
        
        # Set appropriate message based on plan type and upgrade status
        requires_approval = plan.name.lower() != "individual"
        
        if requires_approval:
            messages.success(request, "Payment successful! Waiting for admin approval.")
        else:
            if is_upgrade:
                messages.success(request, f"Payment successful! Your plan has been upgraded to {plan.name}.")
            else:
                messages.success(request, f"Payment successful! You are now subscribed to {plan.name}.")

        # Clear the pending subscription from session
        if 'pending_subscription' in request.session:
            del request.session['pending_subscription']

        return render(request, "payment_success.html", {
            "subscription": subscription,
            "requires_approval": requires_approval,
            "is_upgrade": is_upgrade
        })
    else:
        messages.error(request, "Invalid request method.")
        return redirect("dashboard")
    
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

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Contact
from .forms import ContactForm

def contact(request):
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your message has been sent successfully!')
            return redirect('contact')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = ContactForm()

    return render(request, 'contact.html', {'form': form})

@login_required
def contact_list(request):
    contacts = Contact.objects.all().order_by('-created_at')
    return render(request, 'contact_list.html', {'contacts': contacts})

@login_required
def delete_contact(request, pk):
    contact = get_object_or_404(Contact, pk=pk)
    contact.delete()
    messages.success(request, 'Contact deleted successfully!')
    return redirect('contact_list')

@login_required
def safety_basic_calculator(request):
     return render(request, 'calculators/safety_basic_calculator.html')
     
@login_required
def quality_basic_calculator(request):
     return render(request, 'calculators/quality_basic_calculator.html')

@login_required
def environment_basic_calculator(request):
     return render(request, 'calculators/environment_basic_calculator.html')

@login_required
def health_basic_calculator(request):
     return render(request, 'calculators/health_basic_calculator.html')

@login_required
def fire_basic_calculator(request):
     return render(request, 'calculators/fire_basic_calculator.html')

def terms(request):
    return render(request, 'terms.html')

def privacy(request):
    return render(request, 'privacy.html')

def upgrade_required(request):
    return render(request, 'upgrade_required.html')

def accident_rate_calculator(request):
    return render(request, 'qehsfcalculators/Safety/accident_rate_calculator.html')
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
    user = request.user
    device_id = request.session.session_key or request.COOKIES.get("device_id")

    # Remove the current device from UserDevice
    if user.is_authenticated and device_id:
        UserDevice.objects.filter(user=user, device_id=device_id).delete()

    # Log out the user
    logout(request)
    messages.success(request, "Logged out successfully.")
    return redirect("home")

def fire_calculator(request):
    return render(request, 'calculators/fire.html', {'title': 'Fire Calculator'})


from django.shortcuts import render
from django.utils import timezone
from .models import UserSubscription  # import your subscription model
from .access_map import CALCULATORS, CATEGORIES, PLAN_HIERARCHY

def get_user_plan(user):
    """Returns the plan name if user has an active subscription, else None."""
    if not user.is_authenticated:
        return None  # Guests have no plan

    active_subscription = UserSubscription.objects.filter(
        user=user,
        status="active",
        end_date__gte=timezone.now()
    ).order_by('-start_date').first()

    if active_subscription and active_subscription.plan:
        return active_subscription.plan.name  # "individual" / "employee" / "corporate"
    return None  # No active plan


def get_calculators_for_category(category, user_plan):
    if not user_plan:
        # No plan → no calculators
        return []

    user_plan_level = PLAN_HIERARCHY.get(user_plan, 0)  # 0 = no access
    filtered = [
        calc for calc in CALCULATORS
        if calc['category'] == category and PLAN_HIERARCHY[calc['plan_type']] <= user_plan_level
    ]
    print(f"DEBUG: Category={category}, User Plan={user_plan}, Found={filtered}")
    return filtered


def qualitycategory_calculators(request):
    user_plan = get_user_plan(request.user)
    calculators = get_calculators_for_category('quality', user_plan)
    return render(request, 'calculatorcategories/qualitycategory.html', {
        'calculators': calculators,
        'category': CATEGORIES['quality']
    })


def environmentcategory_calculators(request):
    user_plan = get_user_plan(request.user)
    calculators = get_calculators_for_category('environment', user_plan)
    return render(request, 'calculatorcategories/environmentcategory.html', {
        'calculators': calculators,
        'category': CATEGORIES['environment']
    })


def healthcategory_calculators(request):
    user_plan = get_user_plan(request.user)
    calculators = get_calculators_for_category('health', user_plan)
    return render(request, 'calculatorcategories/healthcategory.html', {
        'calculators': calculators,
        'category': CATEGORIES['health']
    })


def safetycategory_calculators(request):
    user_plan = get_user_plan(request.user)
    calculators = get_calculators_for_category('safety', user_plan)
    return render(request, 'calculatorcategories/safetycategory.html', {
        'calculators': calculators,
        'category': CATEGORIES['safety']
    })


def firecategory_calculators(request):
    user_plan = get_user_plan(request.user)
    calculators = get_calculators_for_category('fire', user_plan)
    return render(request, 'calculatorcategories/firecategory.html', {
        'calculators': calculators,
        'category': CATEGORIES['fire']
    })

from django.contrib.auth.decorators import login_required, user_passes_test

from .forms import UserEditForm 

# Check if user is superuser
def is_superuser(user):
    return user.is_superuser

@login_required
@user_passes_test(is_superuser)
def user_list(request):
    """List all users (superuser only)."""
    users = CustomUser.objects.all().order_by('-date_joined')
    return render(request, 'user_list.html', {'users': users})




@login_required
def edit_user(request, pk):
    """Allow user to edit their own profile."""
    user_obj = get_object_or_404(CustomUser, pk=pk)

    if request.user != user_obj:
        messages.error(request, "You can only edit your own profile.")
        return redirect('user_detail', pk=request.user.pk)

    if request.method == 'POST':
        form = UserEditForm(request.POST, instance=user_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Your profile has been updated successfully!")
            return redirect('user_detail', pk=user_obj.pk)
    else:
        form = UserEditForm(instance=user_obj)

    return render(request, 'edit_user.html', {'form': form})


@login_required
@user_passes_test(is_superuser)
def delete_user(request, pk):
    """Delete a user (superusers only)."""
    user_obj = get_object_or_404(CustomUser, pk=pk)
    if request.method == 'POST':
        user_obj.delete()
        messages.success(request, "User deleted successfully!")
        return redirect('user_list')

    return render(request, 'delete_user_confirm.html', {'user_obj': user_obj})

@login_required
@subscription_required(plan_type="employee")
def co2_calculator(request):
    return render(request, 'calculators/co2_emission.html', {'title': 'CO2 Emission Calculator'})


@login_required
@subscription_required(plan_type="corporate")
def quality_main_calculator(request):
    return render(request, 'qehsfcalculators/quality/main.html', {'title': 'Main calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_actual_evaporation_rate_of_a_boiler_from_its_kw_rating_and_the_energy_required_to_make_steam_calculator(request):
    return render(request, 'qehsfcalculators/quality/actual_evaporation_rate_of_a_boiler_from_its_kw_rating_and_the_energy_required_to_make_steam.html', {'title': 'Actual evaporation rate of a boiler from its kW rating and the energy required to make steam Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_attendee_training_time_calculator(request):
    return render(request, 'qehsfcalculators/quality/attendee_training_time.html', {'title': 'Attendee Training Time Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_acidity_based_on_hydrogen_ion_concentration_calculator(request):
    return render(request, 'qehsfcalculators/quality/acidity_based_on_hydrogen_ion_concentration.html', {'title': 'Acidity Calculator based on Hydrogen Ion Concentration'})

@login_required
@subscription_required(plan_type="corporate")
def quality_boiler_horse_power_from_heat_transwer_area_calculator(request):
    return render(request, 'qehsfcalculators/quality/boiler_horse_power_from_heat_transwer_area.html', {'title': 'Boiler Horse Power From heat transwer area calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_binomial_distribution_calculator(request):
    return render(request, 'qehsfcalculators/quality/binomial_distribution.html', {'title': 'Binomial Distribution Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_broad_calculation_of_garments_cost_of_making_cm_calculator(request):
    return render(request, 'qehsfcalculators/quality/broad_calculation_of_garments_cost_of_making_cm.html', {'title': 'Broad Calculation of Garments Cost of Making (CM)'})

@login_required
@subscription_required(plan_type="corporate")
def quality_boiling_point_elevation_calculator(request):
    return render(request, 'qehsfcalculators/quality/boiling_point_elevation.html', {'title': 'Boiling Point Elevation Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_correct_the_conductivity_of_a_sample_calculator(request):
    return render(request, 'qehsfcalculators/quality/correct_the_conductivity_of_a_sample.html', {'title': 'Correct the conductivity of a sample Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_cost_of_poor_quality_copq_calculator(request):
    return render(request, 'qehsfcalculators/quality/cost_of_poor_quality_copq.html', {'title': 'Cost of Poor Quality (COPQ) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_customer_satisfaction_csat_calculator(request):
    return render(request, 'qehsfcalculators/quality/customer_satisfaction_csat.html', {'title': 'Customer Satisfaction (CSAT) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_cost_per_minute_cpm_calculator(request):
    return render(request, 'qehsfcalculators/quality/cost_per_minute_cpm.html', {'title': 'Cost Per Minute (CPM) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_cost_of_making_cm_calculator(request):
    return render(request, 'qehsfcalculators/quality/cost_of_making_cm.html', {'title': 'Cost of Making (CM) Calculator '})

@login_required
@subscription_required(plan_type="corporate")
def quality_corrective_action_effectiveness_cae_calculator(request):
    return render(request, 'qehsfcalculators/quality/corrective_action_effectiveness_cae.html', {'title': 'Corrective Action Effectiveness (CAE) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_critical_number_of_samples_calculator(request):
    return render(request, 'qehsfcalculators/quality/critical_number_of_samples.html', {'title': 'Critical Number of Samples Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_defects_per_million_opportunities_dpmo_and_six_sigma_calculator(request):
    return render(request, 'qehsfcalculators/quality/defects_per_million_opportunities_dpmo_and_six_sigma.html', {'title': 'Defects Per Million Opportunities (DPMO) and Six Sigma  Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_defect_rate_calculator(request):
    return render(request, 'qehsfcalculators/quality/defect_rate.html', {'title': 'Defect Rate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_directional_survey_calculator(request):
    return render(request, 'qehsfcalculators/quality/directional_survey.html', {'title': 'Directional Survey Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_dispersion_calculator(request):
    return render(request, 'qehsfcalculators/quality/dispersion.html', {'title': 'Dispersion Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_dilution_ventilation_rate_for_contaminant_control_calculator(request):
    return render(request, 'qehsfcalculators/quality/dilution_ventilation_rate_for_contaminant_control.html', {'title': 'Dilution Ventilation Rate for Contaminant Control Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_dry_film_thickness_dft_calculator(request):
    return render(request, 'qehsfcalculators/quality/dry_film_thickness_dft.html', {'title': 'Dry Film Thickness (DFT) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_evaporation_factor_of_a_boiler_from_its_from_and_at_rating_calculator(request):
    return render(request, 'qehsfcalculators/quality/evaporation_factor_of_a_boiler_from_its_from_and_at_rating.html')
@subscription_required(plan_type="corporate")
def quality_electrical_resistance_for_conductivity_probe_calculator(request):
    return render(request, 'qehsfcalculators/quality/electrical_resistance_for_conductivity_probe.html', {'title': 'Electrical Resistance Calculator for Conductivity Probe calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_first_pass_yield_fpy_calculator(request):
    return render(request, 'qehsfcalculators/quality/first_pass_yield_fpy.html', {'title': 'First Pass Yield (FPY) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_fold_of_increase_calculator(request):
    return render(request, 'qehsfcalculators/quality/fold_of_increase.html', {'title': 'Fold of Increase Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_facade_element_weight_calculator(request):
    return render(request, 'qehsfcalculators/quality/facade_element_weight.html', {'title': 'Facade Element Weight Calculator '})

@login_required
@subscription_required(plan_type="corporate")
def quality_gibbs_phase_rule_calculator(request):
    return render(request, 'qehsfcalculators/quality/gibbs_phase_rule.html', {'title': 'Gibbs Phase Rule Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_heat_exchanger_heating_area_calculator(request):
    return render(request, 'qehsfcalculators/quality/heat_exchanger_heating_area.html', {'title': 'Heat Exchanger Heating Area Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_largest_particle_size_through_a_strainer_screen_calculator(request):
    return render(request, 'qehsfcalculators/quality/largest_particle_size_through_a_strainer_screen.html', {'title': 'Largest Particle Size Through a Strainer Screen Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_line_target_calculator(request):
    return render(request, 'qehsfcalculators/quality/line_target.html', {'title': 'Line Target Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_mass_flow_rate_of_steam_through_an_orifice_calculator(request):
    return render(request, 'qehsfcalculators/quality/mass_flow_rate_of_steam_through_an_orifice.html', {'title': 'Mass Flow Rate of Steam Through an Orifice calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_overall_equipment_effectiveness_oee_calculator(request):
    return render(request, 'qehsfcalculators/quality/overall_equipment_effectiveness_oee.html', {'title': 'Overall Equipment Effectiveness (OEE) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_percentage_error_when_using_velocity_calculator(request):
    return render(request, 'qehsfcalculators/quality/percentage_error_when_using_velocity.html', {'title': 'Percentage Error when using velocity Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_percentage_error_when_using_pressure_calculator(request):
    return render(request, 'qehsfcalculators/quality/percentage_error_when_using_pressure.html', {'title': 'Percentage Error when using pressure Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_pressure_drop_and_friction_loss_calculator(request):
    return render(request, 'qehsfcalculators/quality/pressure_drop_and_friction_loss.html', {'title': 'Pressure Drop & Friction Loss Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_process_capability_cp_cpk_calculator(request):
    return render(request, 'qehsfcalculators/quality/process_capability_cp_cpk.html', {'title': 'Process Capability (Cp, Cpk) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_production_efficiency_calculator(request):
    return render(request, 'qehsfcalculators/quality/production_efficiency.html', {'title': 'Production Efficiency Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_quality_loss_function_taguchi_method_calculator(request):
    return render(request, 'qehsfcalculators/quality/quality_loss_function_taguchi_method.html', {'title': 'Quality Loss Function Calculator (Taguchi Method)'})

@login_required
@subscription_required(plan_type="corporate")
def quality_relating_boiler_pressure_to_heat_transfer_rate_calculator(request):
    return render(request, 'qehsfcalculators/quality/relating_boiler_pressure_to_heat_transfer_rate.html', {'title': 'Relating boiler pressure to heat transfer rate'})

@login_required
@subscription_required(plan_type="corporate")
def quality_reynolds_number_calculator(request):
    return render(request, 'qehsfcalculators/quality/reynolds_number.html', {'title': 'Reynolds Number Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_relation_between_indicate_and_actual_flowrate_calculator(request):
    return render(request, 'qehsfcalculators/quality/relation_between_indicate_and_actual_flowrate.html', {'title': 'Relation between indicate and actual flowrate calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_rolled_throughput_yield_rty_calculator(request):
    return render(request, 'qehsfcalculators/quality/rolled_throughput_yield_rty.html', {'title': 'Rolled Throughput Yield (RTY) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_steam_consumption_of_drying_cylinders_calculator(request):
    return render(request, 'qehsfcalculators/quality/steam_consumption_of_drying_cylinders.html', {'title': 'Steam Consumption of Drying Cylinders Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_steam_velocity_through_an_orifice_calculator(request):
    return render(request, 'qehsfcalculators/quality/steam_velocity_through_an_orifice.html', {'title': 'Steam Velocity Calculator through an orifice Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_steam_density_usin_b44_b38_calculator(request):
    return render(request, 'qehsfcalculators/quality/steam_density_usin_b44_b38.html', {'title': 'Steam Density Calculator (Usin+B44+B38'})

@login_required
@subscription_required(plan_type="corporate")
def quality_statistical_process_control_spc_chart_calculator(request):
    return render(request, 'qehsfcalculators/quality/statistical_process_control_spc_chart.html', {'title': 'Statistical Process Control (SPC) Chart Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_secondary_fluid_outlet_temperature_at_any_load_calculator(request):
    return render(request, 'qehsfcalculators/quality/secondary_fluid_outlet_temperature_at_any_load.html', {'title': 'Secondary Fluid Outlet Temperature At Any Load Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_standard_minute_value_smv_calculator(request):
    return render(request, 'qehsfcalculators/quality/standard_minute_value_smv.html', {'title': 'Standard Minute Value (SMV) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_sample_size_calculator(request):
    return render(request, 'qehsfcalculators/quality/sample_size.html', {'title': 'Sample Size Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_sensible_heat_gain_from_infiltration_calculator(request):
    return render(request, 'qehsfcalculators/quality/sensible_heat_gain_from_infiltration.html', {'title': 'Sensible Heat Gain from Infiltration Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_turndown_ratio_of_a_steam_flowmeter_calculator(request):
    return render(request, 'qehsfcalculators/quality/turndown_ratio_of_a_steam_flowmeter.html', {'title': 'Turndown ratio of a steam flowmeter Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_training_efficiency_calculator(request):
    return render(request, 'qehsfcalculators/quality/training_efficiency.html', {'title': 'Training Efficiency Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_two_pack_mix_density_calculator(request):
    return render(request, 'qehsfcalculators/quality/two_pack_mix_density.html', {'title': 'Two-Pack Mix Density Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_vortex_shedding_frequency_calculator(request):
    return render(request, 'qehsfcalculators/quality/vortex_shedding_frequency.html', {'title': 'Vortex Shedding Frequency Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_volume_solids_vs_calculator(request):
    return render(request, 'qehsfcalculators/quality/volume_solids_vs.html', {'title': 'Volume Solids (VS) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_volume_of_paint_required_calculator(request):
    return render(request, 'qehsfcalculators/quality/volume_of_paint_required.html', {'title': 'Volume of Paint Required Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_wet_film_thickness_wft_calculator(request):
    return render(request, 'qehsfcalculators/quality/wet_film_thickness_wft.html', {'title': 'Wet Film Thickness (WFT) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def quality_water_ion_product_calculator(request):
    return render(request, 'qehsfcalculators/quality/water_ion_product.html', {'title': 'Water Ion Product Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_main_calculator(request):
    return render(request, 'qehsfcalculators/environment/main.html', {'title': 'Main calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_ambient_noise_level_calculator(request):
    return render(request, 'qehsfcalculators/environment/ambient_noise_level.html', {'title': 'Ambient Noise Level Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_arithmetic_mean_temperature_difference_amtd_calculator(request):
    return render(request, 'qehsfcalculators/environment/arithmetic_mean_temperature_difference_amtd.html', {'title': 'Arithmetic Mean Temperature Difference (AMTD) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_air_flow_rate_mass_flow_calculator(request):
    return render(request, 'qehsfcalculators/environment/air_flow_rate_mass_flow.html', {'title': 'Air flow rate(mass flow) calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_air_flow_rate_time_based_calculator(request):
    return render(request, 'qehsfcalculators/environment/air_flow_rate_time_based.html', {'title': 'Air flow rate(Time -Based) calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_actual_value_of_super_heated_steam_flow_calculator(request):
    return render(request, 'qehsfcalculators/environment/actual_value_of_super_heated_steam_flow.html', {'title': 'Actual value of super-heated steam flow calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_air_pollutant_concentration_calculator(request):
    return render(request, 'qehsfcalculators/environment/air_pollutant_concentration.html', {'title': 'Air Pollutant Concentration Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_air_changes_per_hour_ach_calculator(request):
    return render(request, 'qehsfcalculators/environment/air_changes_per_hour_ach.html', {'title': 'Air Changes per Hour (ACH) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_aeration_tank_volume_calculator(request):
    return render(request, 'qehsfcalculators/environment/aeration_tank_volume.html', {'title': 'Aeration Tank Volume Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_boiler_blowdown_rate_calculator(request):
    return render(request, 'qehsfcalculators/environment/boiler_blowdown_rate.html', {'title': 'Boiler Blowdown Rate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_boiler_efficiency_calculator(request):
    return render(request, 'qehsfcalculators/environment/boiler_efficiency.html', {'title': 'Boiler efficiency Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_bernoullis_equation_with_constant_potential_energy_terms_calculator(request):
    return render(request, 'qehsfcalculators/environment/bernoullis_equation_with_constant_potential_energy_terms.html')

@login_required
@subscription_required(plan_type="corporate")
def environment_bod_biochemical_oxygen_demand_exertion_calculator(request):
    return render(request, 'qehsfcalculators/environment/bod_biochemical_oxygen_demand_exertion.html', {'title': 'BOD  (Biochemical Oxygen Demand) Exertion Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_breakthrough_time_calculator(request):
    return render(request, 'qehsfcalculators/environment/breakthrough_time.html', {'title': 'Breakthrough Time Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_biomass_microbial_growth_calculator(request):
    return render(request, 'qehsfcalculators/environment/biomass_microbial_growth.html', {'title': 'Biomass Microbial Growth Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_biomass_substrate_utilization_rate_calculator(request):
    return render(request, 'qehsfcalculators/environment/biomass_substrate_utilization_rate.html', {'title': 'Biomass Substrate Utilization Rate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_biomass_concentration_xr_calculator(request):
    return render(request, 'qehsfcalculators/environment/biomass_concentration_xr.html', {'title': 'Biomass Concentration (Xr) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_carbnot_effiency_calculator(request):
    return render(request, 'qehsfcalculators/environment/carbnot_effiency.html', {'title': 'Carbnot effiency calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_carbon_footprint_effient_calculator(request):
    return render(request, 'qehsfcalculators/environment/carbon_footprint_effient.html', {'title': 'Carbon Footprint Effient Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_cost_of_fuel_saved_by_returning_condensate_calculator(request):
    return render(request, 'qehsfcalculators/environment/cost_of_fuel_saved_by_returning_condensate.html', {'title': 'Cost of Fuel Saved by Returning Condensate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_cost_of_water_saved_by_returning_condensate_calculator(request):
    return render(request, 'qehsfcalculators/environment/cost_of_water_saved_by_returning_condensate.html', {'title': 'Cost of water Saved by Returning Condensate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_cost_of_effluent_saved_by_returning_condensate_calculator(request):
    return render(request, 'qehsfcalculators/environment/cost_of_effluent_saved_by_returning_condensate.html', {'title': 'Cost of Effluent Saved by Returning Condensate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_corrosion_rate_calculator(request):
    return render(request, 'qehsfcalculators/environment/corrosion_rate.html', {'title': 'Corrosion Rate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_cyclone_collection_particle_removal_efficiency_calculator(request):
    return render(request, 'qehsfcalculators/environment/cyclone_collection_particle_removal_efficiency.html', {'title': 'Cyclone Collection Particle Removal Efficiency Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_cyclone_50_collection_efficiency_for_particle_diameter_calculator(request):
    return render(request, 'qehsfcalculators/environment/cyclone_50_collection_efficiency_for_particle_diameter.html', {'title': 'Cyclone 50% Collection Efficiency for Particle Diameter Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_cyclone_effective_number_of_turns_approximation_calculator(request):
    return render(request, 'qehsfcalculators/environment/cyclone_effective_number_of_turns_approximation.html', {'title': 'Cyclone Effective Number of Turns Approximation Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_continuity_equation_calculator(request):
    return render(request, 'qehsfcalculators/environment/continuity_equation.html', {'title': 'Continuity Equation Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_cooling_load_temperature_difference_cltd_calculator(request):
    return render(request, 'qehsfcalculators/environment/cooling_load_temperature_difference_cltd.html', {'title': 'Cooling Load Temperature Difference (CLTD) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_chlorine_contact_time_calculator(request):
    return render(request, 'qehsfcalculators/environment/chlorine_contact_time.html', {'title': 'Chlorine Contact Time Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_carman_kozen_head_loss_and_friction_factor_calculator(request):
    return render(request, 'qehsfcalculators/environment/carman_kozen_head_loss_and_friction_factor.html', {'title': 'Carman-Kozen Head Loss & Friction Factor Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_chicks_law_microbial_disinfection_calculator(request):
    return render(request, 'qehsfcalculators/environment/chicks_law_microbial_disinfection.html', {'title': 'Chick’s Law: Microbial Disinfection Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_chemical_equilibrium_calculator(request):
    return render(request, 'qehsfcalculators/environment/chemical_equilibrium.html', {'title': 'Chemical Equilibrium Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_cmfr_completely_mixed_flow_reactor_bod_biochemical_oxygen_demand_removal_calculator(request):
    return render(request, 'qehsfcalculators/environment/cmfr_completely_mixed_flow_reactor_bod_biochemical_oxygen_demand_removal.html', {'title': 'CMFR (Completely Mixed Flow Reactor) BOD (Biochemical Oxygen Demand) Removal Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_digester_capacity_v_calculator(request):
    return render(request, 'qehsfcalculators/environment/digester_capacity_v.html', {'title': 'Digester Capacity (V) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_dynamic_viscosity_calculator(request):
    return render(request, 'qehsfcalculators/environment/dynamic_viscosity.html', {'title': 'Dynamic Viscosity Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_dissolved_oxygen_do_deficit_streeter_phelps_model_calculator(request):
    return render(request, 'qehsfcalculators/environment/dissolved_oxygen_do_deficit_streeter_phelps_model.html', {'title': 'Dissolved Oxygen (DO) Deficit (Streeter-Phelps Model) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_decreasing_rate_of_increase_growth_calculator(request):
    return render(request, 'qehsfcalculators/environment/decreasing_rate_of_increase_growth.html', {'title': 'Decreasing-Rate-of-Increase Growth Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_daughter_product_activity_calculator(request):
    return render(request, 'qehsfcalculators/environment/daughter_product_activity.html', {'title': 'Daughter Product Activity Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_darcy_weisbach_head_loss_calculator(request):
    return render(request, 'qehsfcalculators/environment/darcy_weisbach_head_loss.html', {'title': 'Darcy-Weisbach Head Loss Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_environmental_impact_carbon_footprint_calculator(request):
    return render(request, 'qehsfcalculators/environment/environmental_impact_carbon_footprint.html', {'title': 'Environmental impact Carbon Footprint Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_energy_requirement_for_a_non_flow_application_eg_batch_or_tank_calculator(request):
    return render(request, 'qehsfcalculators/environment/energy_requirement_for_a_non_flow_application_eg_batch_or_tank.html', {'title': 'Energy requirement for a non-flow application (e.g. batch or tank)'})

@login_required
@subscription_required(plan_type="corporate")
def environment_energy_consumption_calculator(request):
    return render(request, 'qehsfcalculators/environment/energy_consumption.html', {'title': 'Energy Consumption Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_exposure_level_concentration_calculator(request):
    return render(request, 'qehsfcalculators/environment/exposure_level_concentration.html', {'title': 'Exposure Level (Concentration) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_energy_balance_between_steam_and_secondary_fluid_of_a_non_flow_process_calculator(request):
    return render(request, 'qehsfcalculators/environment/energy_balance_between_steam_and_secondary_fluid_of_a_non_flow_process.html', {'title': 'Energy Balance between Steam and Secondary Fluid of a Non-Flow Process caluculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_energy_balance_between_steam_and_fluid_of_a_flow_type_application_calculator(request):
    return render(request, 'qehsfcalculators/environment/energy_balance_between_steam_and_fluid_of_a_flow_type_application.html', {'title': 'Energy Balance between Steam and Fluid of a Flow-Type Application Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_equal_percentage_valve_lift_based_on_relative_flow_calculator(request):
    return render(request, 'qehsfcalculators/environment/equal_percentage_valve_lift_based_on_relative_flow.html', {'title': 'Equal percentage valve lift calculator based on relative flow'})

@login_required
@subscription_required(plan_type="corporate")
def environment_equal_percentage_valve_lift_based_on_kv_calculator(request):
    return render(request, 'qehsfcalculators/environment/equal_percentage_valve_lift_based_on_kv.html', {'title': 'Equal percentage valve lift calculator based on kv'})

@login_required
@subscription_required(plan_type="corporate")
def environment_environmental_damage_frequency_endf_calculator(request):
    return render(request, 'qehsfcalculators/environment/environmental_damage_frequency_endf.html', {'title': 'Environmental Damage Frequency (ENDF) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_environmental_incident_rate_eir_calculator(request):
    return render(request, 'qehsfcalculators/environment/environmental_incident_rate_eir.html', {'title': 'Environmental Incident rate (EIR) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_electrostatic_precipitator_efficiency_calculator(request):
    return render(request, 'qehsfcalculators/environment/electrostatic_precipitator_efficiency.html', {'title': 'Electrostatic Precipitator Efficiency Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_exponential_population_growth_calculator(request):
    return render(request, 'qehsfcalculators/environment/exponential_population_growth.html', {'title': 'Exponential Population Growth Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_effective_half_life_calculator(request):
    return render(request, 'qehsfcalculators/environment/effective_half_life.html', {'title': 'Effective Half-Life Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_entering_coil_conditions_ventilation_airflow_calculator(request):
    return render(request, 'qehsfcalculators/environment/entering_coil_conditions_ventilation_airflow.html', {'title': 'Entering Coil Conditions (Ventilation Airflow) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_elevation_head_loss_calculator(request):
    return render(request, 'qehsfcalculators/environment/elevation_head_loss.html', {'title': 'Elevation Head Loss Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_energy_consumption_per_person_per_year_calculator(request):
    return render(request, 'qehsfcalculators/environment/energy_consumption_per_person_per_year.html', {'title': 'Energy Consumption per Person per Year Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_flash_steam_calculator(request):
    return render(request, 'qehsfcalculators/environment/flash_steam.html', {'title': 'Flash Steam Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_friction_factor_si_based_calculator(request):
    return render(request, 'qehsfcalculators/environment/friction_factor_si_based.html', {'title': 'Friction Factor Calculator (SI-Based)'})

@login_required
@subscription_required(plan_type="corporate")
def environment_friction_factor_imperial_based_calculator(request):
    return render(request, 'qehsfcalculators/environment/friction_factor_imperial_based.html', {'title': 'Friction Factor Calculator (Imperial-Based)'})

@login_required
@subscription_required(plan_type="corporate")
def environment_friction_factor_reynolds_number_calculator(request):
    return render(request, 'qehsfcalculators/environment/friction_factor_reynolds_number.html', {'title': 'Friction Factor Calculator(Reynolds-Number)'})

@login_required
@subscription_required(plan_type="corporate")
def environment_fracture_conductivity_calculator(request):
    return render(request, 'qehsfcalculators/environment/fracture_conductivity.html', {'title': 'Fracture Conductivity Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_freundlich_isotherm_adsorption_capacity_calculator(request):
    return render(request, 'qehsfcalculators/environment/freundlich_isotherm_adsorption_capacity.html', {'title': 'Freundlich Isotherm Calculator (Adsorption Capacity Calculator)'})

@login_required
@subscription_required(plan_type="corporate")
def environment_food_to_microorganism_fm_ratio_calculator(request):
    return render(request, 'qehsfcalculators/environment/food_to_microorganism_fm_ratio.html', {'title': 'Food to Microorganism (F/M) Ratio Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_freezing_point_depression_calculator(request):
    return render(request, 'qehsfcalculators/environment/freezing_point_depression.html', {'title': 'Freezing Point Depression Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_fluid_flow_mass_velocity_calculator(request):
    return render(request, 'qehsfcalculators/environment/fluid_flow_mass_velocity.html', {'title': 'Fluid Flow Mass Velocity Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_gaussian_air_pollutant_dispersion_calculator(request):
    return render(request, 'qehsfcalculators/environment/gaussian_air_pollutant_dispersion.html', {'title': 'Gaussian Air Pollutant Dispersion Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_gas_flux_calculator(request):
    return render(request, 'qehsfcalculators/environment/gas_flux.html', {'title': 'Gas Flux Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_gas_phase_analyte_concentration_calculator(request):
    return render(request, 'qehsfcalculators/environment/gas_phase_analyte_concentration.html', {'title': 'Gas Phase Analyte Concentration Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_gas_buoyancy_calculator(request):
    return render(request, 'qehsfcalculators/environment/gas_buoyancy.html', {'title': 'Gas Buoyancy Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_heat_transfer_thermo_flow_calculator(request):
    return render(request, 'qehsfcalculators/environment/heat_transfer_thermo_flow.html', {'title': 'Heat Transfer Thermo Flow Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_heat_transfer_rate_condensing_steam_calculator(request):
    return render(request, 'qehsfcalculators/environment/heat_transfer_rate_condensing_steam.html', {'title': 'Heat Transfer Rate Calculator (Condensing Steam)'})

@login_required
@subscription_required(plan_type="corporate")
def environment_heat_transfer_thermo_resistance_calculator(request):
    return render(request, 'qehsfcalculators/environment/heat_transfer_thermo_resistance.html', {'title': 'Heat Transfer Thermo resistance Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_heat_transferred_by_condensing_steam_calculator(request):
    return render(request, 'qehsfcalculators/environment/heat_transferred_by_condensing_steam.html', {'title': 'Heat transferred by condensing steam'})

@login_required
@subscription_required(plan_type="corporate")
def environment_heat_exchanger_temperature_design_constant_calculator(request):
    return render(request, 'qehsfcalculators/environment/heat_exchanger_temperature_design_constant.html', {'title': 'Heat Exchanger Temperature Design Constant Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_half_life_decay_calculator(request):
    return render(request, 'qehsfcalculators/environment/half_life_decay.html', {'title': 'Half-Life Decay Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_hazen_williams_hydraulic_flow_velocity_calculator(request):
    return render(request, 'qehsfcalculators/environment/hazen_williams_hydraulic_flow_velocity.html', {'title': 'Hazen-Williams Hydraulic Flow Velocity Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_hardy_cross_flow_correction_δd_calculator(request):
    return render(request, 'qehsfcalculators/environment/hardy_cross_flow_correction_δd.html', {'title': 'Hardy Cross Flow Correction Calculator (Δd)'})

@login_required
@subscription_required(plan_type="corporate")
def environment_hardy_cross_head_loss_calculator(request):
    return render(request, 'qehsfcalculators/environment/hardy_cross_head_loss.html', {'title': 'Hardy Cross Head Loss Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_hardy_cross_flow_update_calculator(request):
    return render(request, 'qehsfcalculators/environment/hardy_cross_flow_update.html', {'title': 'Hardy Cross Flow Update Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_heat_gain_from_lighting_calculator(request):
    return render(request, 'qehsfcalculators/environment/heat_gain_from_lighting.html', {'title': 'Heat Gain from Lighting Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_heat_gain_from_ventilation_calculator(request):
    return render(request, 'qehsfcalculators/environment/heat_gain_from_ventilation.html', {'title': 'Heat Gain from Ventilation Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_height_calculation_for_drain_pipe_slope_calculator(request):
    return render(request, 'qehsfcalculators/environment/height_calculation_for_drain_pipe_slope.html', {'title': 'Height Calculation for Drain Pipe Slope'})

@login_required
@subscription_required(plan_type="corporate")
def environment_height_of_soak_pit_based_on_volume_calculator(request):
    return render(request, 'qehsfcalculators/environment/height_of_soak_pit_based_on_volume.html', {'title': 'Height of Soak Pit Based on Volume Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_horizontal_settling_velocity_vh_calculator(request):
    return render(request, 'qehsfcalculators/environment/horizontal_settling_velocity_vh.html', {'title': 'Horizontal Settling Velocity (vh) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_head_loss_through_clean_flat_bar_screens_calculator(request):
    return render(request, 'qehsfcalculators/environment/head_loss_through_clean_flat_bar_screens.html', {'title': 'Head Loss through Clean Flat Bar Screens Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_head_loss_through_fine_screens_calculator(request):
    return render(request, 'qehsfcalculators/environment/head_loss_through_fine_screens.html', {'title': 'Head Loss through Fine Screens Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_incineration_dre_calculator(request):
    return render(request, 'qehsfcalculators/environment/incineration_dre.html', {'title': 'Incineration DRE Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_kinematic_viscosity_calculator(request):
    return render(request, 'qehsfcalculators/environment/kinematic_viscosity.html', {'title': 'Kinematic Viscosity Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_kiln_residence_time_calculator(request):
    return render(request, 'qehsfcalculators/environment/kiln_residence_time.html', {'title': 'Kiln Residence Time Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_kirschmers_head_loss_h_calculator(request):
    return render(request, 'qehsfcalculators/environment/kirschmers_head_loss_h.html', {'title': 'Kirschmer’s Head Loss (h) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_log_mean_temperature_difference_lmtd_calculator(request):
    return render(request, 'qehsfcalculators/environment/log_mean_temperature_difference_lmtd.html', {'title': 'Log Mean Temperature Difference (LMTD) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_liquid_flow_rate_vs_pressure_drop_calculator(request):
    return render(request, 'qehsfcalculators/environment/liquid_flow_rate_vs_pressure_drop.html', {'title': 'Liquid Flow rate vs pressure drop calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_latent_heat_gain_from_people_calculator(request):
    return render(request, 'qehsfcalculators/environment/latent_heat_gain_from_people.html', {'title': 'Latent Heat Gain from People Calculator '})

@login_required
@subscription_required(plan_type="corporate")
def environment_latent_heat_gain_from_infiltration_calculator(request):
    return render(request, 'qehsfcalculators/environment/latent_heat_gain_from_infiltration.html', {'title': 'Latent Heat Gain from Infiltration Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_loading_rate_hydraulic_retention_time_hrt_calculator(request):
    return render(request, 'qehsfcalculators/environment/loading_rate_hydraulic_retention_time_hrt.html', {'title': 'Loading Rate Hydraulic Retention Time (HRT) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_loading_rate_specific_substrate_utilization_rate_calculator(request):
    return render(request, 'qehsfcalculators/environment/loading_rate_specific_substrate_utilization_rate.html', {'title': 'Loading Rate Specific Substrate Utilization Rate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_lapse_rate_calculator(request):
    return render(request, 'qehsfcalculators/environment/lapse_rate.html', {'title': 'Lapse Rate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_liquid_film_coefficient_kl_calculator(request):
    return render(request, 'qehsfcalculators/environment/liquid_film_coefficient_kl.html', {'title': 'Liquid Film Coefficient (KL) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_mass_flow_rate_from_velocity_calculator(request):
    return render(request, 'qehsfcalculators/environment/mass_flow_rate_from_velocity.html', {'title': 'Mass Flow Rate From Velocity Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_mean_steam_consumption_rate_for_a_flow_type_application1_calculator(request):
    return render(request, 'qehsfcalculators/environment/mean_steam_consumption_rate_for_a_flow_type_application1.html', {'title': 'Mean steam consumption rate for  a flow type application(1)'})

@login_required
@subscription_required(plan_type="corporate")
def environment_mean_steam_consumption_of_a_flow_type_application2_calculator(request):
    return render(request, 'qehsfcalculators/environment/mean_steam_consumption_of_a_flow_type_application2.html', {'title': 'Mean Steam Consumption  Of a Flow-Type Application caluculator (2)'})

@login_required
@subscription_required(plan_type="corporate")
def environment_mean_steam_flowrate_to_a_storage_calorifier_calculator(request):
    return render(request, 'qehsfcalculators/environment/mean_steam_flowrate_to_a_storage_calorifier.html', {'title': 'mean steam flowrate to a storage calorifier calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_maximum_allowable_concentartion_mac_calculator(request):
    return render(request, 'qehsfcalculators/environment/maximum_allowable_concentartion_mac.html', {'title': 'Maximum allowable concentartion (MAC) calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_mass_flow_rate_from_volumetric_flowrate_calculator(request):
    return render(request, 'qehsfcalculators/environment/mass_flow_rate_from_volumetric_flowrate.html', {'title': 'Mass Flow Rate from volumetric flowrate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_metal_loss_calculator(request):
    return render(request, 'qehsfcalculators/environment/metal_loss.html', {'title': 'Metal Loss Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_municipal_water_quantity_estimator_calculator(request):
    return render(request, 'qehsfcalculators/environment/municipal_water_quantity_estimator.html', {'title': 'Municipal Water Quantity Estimator Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_maximum_pollutant_concentration_calculator(request):
    return render(request, 'qehsfcalculators/environment/maximum_pollutant_concentration.html', {'title': 'Maximum Pollutant Concentration Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_monod_kinetics_substrate_limited_growth_calculator(request):
    return render(request, 'qehsfcalculators/environment/monod_kinetics_substrate_limited_growth.html', {'title': 'Monod Kinetics - Substrate Limited Growth Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_mannings_formula_for_hydraulic_flow_velocity_calculator(request):
    return render(request, 'qehsfcalculators/environment/mannings_formula_for_hydraulic_flow_velocity.html', {'title': 'Manning’s Formula For Hydraulic Flow Velocity Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_mean_cell_residence_sludge_retention_time_srt_calculator(request):
    return render(request, 'qehsfcalculators/environment/mean_cell_residence_sludge_retention_time_srt.html', {'title': 'Mean Cell Residence Sludge Retention Time (SRT) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_mass_of_waste_activated_sludge_calculator(request):
    return render(request, 'qehsfcalculators/environment/mass_of_waste_activated_sludge.html', {'title': 'Mass of Waste Activated Sludge Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_minor_losses_fittings_calculator(request):
    return render(request, 'qehsfcalculators/environment/minor_losses_fittings.html', {'title': 'Minor Losses (Fittings) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_maximum_plume_concentration_calculator(request):
    return render(request, 'qehsfcalculators/environment/maximum_plume_concentration.html', {'title': 'Maximum Plume Concentration Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_mass_transfer_rate_calculator(request):
    return render(request, 'qehsfcalculators/environment/mass_transfer_rate.html', {'title': 'Mass Transfer Rate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_molar_humidity_calculator(request):
    return render(request, 'qehsfcalculators/environment/molar_humidity.html', {'title': 'Molar Humidity Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_net_microbial_growth_rate_calculator(request):
    return render(request, 'qehsfcalculators/environment/net_microbial_growth_rate.html', {'title': 'Net Microbial Growth Rate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_overburden_pressure_calculator(request):
    return render(request, 'qehsfcalculators/environment/overburden_pressure.html', {'title': 'Overburden Pressure Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_oxygen_requirement_o2_activated_sludge_process_calculator(request):
    return render(request, 'qehsfcalculators/environment/oxygen_requirement_o2_activated_sludge_process.html', {'title': 'Oxygen Requirement O2 Calculator - Activated Sludge Process'})

@login_required
@subscription_required(plan_type="corporate")
def environment_oxygen_transfer_under_field_conditions_calculator(request):
    return render(request, 'qehsfcalculators/environment/oxygen_transfer_under_field_conditions.html', {'title': 'Oxygen Transfer Under Field Conditions Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_pressure_drop_across_a_valve_in_a_liquid_calculator(request):
    return render(request, 'qehsfcalculators/environment/pressure_drop_across_a_valve_in_a_liquid.html', {'title': 'Pressure Drop Across a Valve In A Liquid Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_population_projection_calculator(request):
    return render(request, 'qehsfcalculators/environment/population_projection.html', {'title': 'Population Projection Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_percent_growth_calculator(request):
    return render(request, 'qehsfcalculators/environment/percent_growth.html', {'title': 'Percent Growth Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_psychrometric_mixed_air_temperature_calculator(request):
    return render(request, 'qehsfcalculators/environment/psychrometric_mixed_air_temperature.html', {'title': 'Psychrometric Mixed Air Temperature Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_pressure_drop_darcy_weisbach_calculator(request):
    return render(request, 'qehsfcalculators/environment/pressure_drop_darcy_weisbach.html', {'title': 'Pressure Drop Calculator (Darcy-Weisbach) '})

@login_required
@subscription_required(plan_type="corporate")
def environment_pipe_flow_velocity_calculator(request):
    return render(request, 'qehsfcalculators/environment/pipe_flow_velocity.html', {'title': 'Pipe Flow Velocity Calculator '})

@login_required
@subscription_required(plan_type="corporate")
def environment_pipe_friction_factor_calculator(request):
    return render(request, 'qehsfcalculators/environment/pipe_friction_factor.html', {'title': 'Pipe Friction Factor Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_pipe_diameter_sizing_calculator(request):
    return render(request, 'qehsfcalculators/environment/pipe_diameter_sizing.html', {'title': 'Pipe Diameter Sizing Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_power_required_kw_calculator(request):
    return render(request, 'qehsfcalculators/environment/power_required_kw.html', {'title': 'Power Required (kW) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_plug_flow_biochemical_oxygen_demand_bod_removal_effluent_bod_calculator(request):
    return render(request, 'qehsfcalculators/environment/plug_flow_biochemical_oxygen_demand_bod_removal_effluent_bod.html', {'title': 'Plug Flow Biochemical Oxygen Demand (BOD) Removal (Effluent BOD) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_ppm_to_mg_m_conversion_air_pollution_calculator(request):
    return render(request, 'qehsfcalculators/environment/ppm_to_mg_m_conversion_air_pollution.html', {'title': 'PPM to mg/m³ Conversion Calculator (Air Pollution)'})

@login_required
@subscription_required(plan_type="corporate")
def environment_plume_rise_estimation_hollands_equation_calculator(request):
    return render(request, 'qehsfcalculators/environment/plume_rise_estimation_hollands_equation.html', {'title': 'Plume Rise Estimation Calculator (Holland’s Equation)'})

@login_required
@subscription_required(plan_type="corporate")
def environment_percentage_of_saturation_humidity_ratio_calculator(request):
    return render(request, 'qehsfcalculators/environment/percentage_of_saturation_humidity_ratio.html', {'title': 'Percentage of Saturation (Humidity Ratio) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_recycling_carbon_footprint_savings_calculator(request):
    return render(request, 'qehsfcalculators/environment/recycling_carbon_footprint_savings.html', {'title': 'Recycling Carbon Footprint Savings Calculator '})

@login_required
@subscription_required(plan_type="corporate")
def environment_recycling_impact_calculator(request):
    return render(request, 'qehsfcalculators/environment/recycling_impact.html', {'title': 'Recycling impact calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_rankine_efficiency_calculator(request):
    return render(request, 'qehsfcalculators/environment/rankine_efficiency.html', {'title': 'Rankine Efficiency Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_relative_pipe_roughness_calculator(request):
    return render(request, 'qehsfcalculators/environment/relative_pipe_roughness.html', {'title': 'Relative Pipe Roughness Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_ratio_and_correlation_growth_calculator(request):
    return render(request, 'qehsfcalculators/environment/ratio_and_correlation_growth.html', {'title': 'Ratio and Correlation Growth Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_rapid_mix_and_flocculator_design_calculator(request):
    return render(request, 'qehsfcalculators/environment/rapid_mix_and_flocculator_design.html', {'title': 'Rapid Mix & Flocculator Design Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_reverse_osmosis_osmotic_pressure_calculator(request):
    return render(request, 'qehsfcalculators/environment/reverse_osmosis_osmotic_pressure.html', {'title': 'Reverse Osmosis (Osmotic Pressure Calculator)'})

@login_required
@subscription_required(plan_type="corporate")
def environment_required_ventilation_rate_for_indoor_air_quality_calculator(request):
    return render(request, 'qehsfcalculators/environment/required_ventilation_rate_for_indoor_air_quality.html', {'title': 'Required Ventilation Rate Calculator For Indoor Air Quality'})

@login_required
@subscription_required(plan_type="corporate")
def environment_reynolds_flow_predictor_calculator(request):
    return render(request, 'qehsfcalculators/environment/reynolds_flow_predictor.html', {'title': 'Reynolds Flow Predictor Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_retention_time_in_settling_zone_t_calculator(request):
    return render(request, 'qehsfcalculators/environment/retention_time_in_settling_zone_t.html', {'title': 'Retention Time in Settling Zone (t) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_rankins_equation_filter_efficiency_calculator(request):
    return render(request, 'qehsfcalculators/environment/rankins_equation_filter_efficiency.html')

@login_required
@subscription_required(plan_type="corporate")
def environment_relative_saturation_humidity_calculator(request):
    return render(request, 'qehsfcalculators/environment/relative_saturation_humidity.html', {'title': 'Relative Saturation (Humidity) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_steam_flow_rate_for_a_steam_injection_process_calculator(request):
    return render(request, 'qehsfcalculators/environment/steam_flow_rate_for_a_steam_injection_process.html', {'title': 'Steam Flow Rate For A Steam Injection Process Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_specific_volume_of_wet_steam_calculator(request):
    return render(request, 'qehsfcalculators/environment/specific_volume_of_wet_steam.html', {'title': 'Specific volume of wet steam calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_steam_condensing_rate_for_horizontal_pipes_in_still_air_calculator(request):
    return render(request, 'qehsfcalculators/environment/steam_condensing_rate_for_horizontal_pipes_in_still_air.html', {'title': 'steam condensing rate for horizontal pipes in still air calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_steam_condensing_rate_for_air_heating_equipment_calculator(request):
    return render(request, 'qehsfcalculators/environment/steam_condensing_rate_for_air_heating_equipment.html', {'title': 'Steam Condensing Rate for Air Heating Equipment caluculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_steam_running_load_to_keep_a_steam_maintain_calculator(request):
    return render(request, 'qehsfcalculators/environment/steam_running_load_to_keep_a_steam_maintain.html', {'title': 'Steam Running Load to keep a steam maintain Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_steam_injection_required_to_power_a_steam_deaerator_calculator(request):
    return render(request, 'qehsfcalculators/environment/steam_injection_required_to_power_a_steam_deaerator.html', {'title': 'Steam injection required to power a steam deaerator  calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_steam_storage_capacity_of_an_accumulator_calculator(request):
    return render(request, 'qehsfcalculators/environment/steam_storage_capacity_of_an_accumulator.html', {'title': 'Steam storage capacity of an accumulator calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_speed_of_sound_in_steam_calculator(request):
    return render(request, 'qehsfcalculators/environment/speed_of_sound_in_steam.html', {'title': 'Speed of sound in steamcalculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_sound_power_level_at_the_safety_valve_outlet_calculator(request):
    return render(request, 'qehsfcalculators/environment/sound_power_level_at_the_safety_valve_outlet.html', {'title': 'Sound Power Level At The Safety Valve Outlet Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_sound_pressure_level_at_the_safety_valve_outlet_calculator(request):
    return render(request, 'qehsfcalculators/environment/sound_pressure_level_at_the_safety_valve_outlet.html', {'title': 'Sound Pressure Level At The Safety Valve Outlet Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_steam_temperature_at_any_load_calculator(request):
    return render(request, 'qehsfcalculators/environment/steam_temperature_at_any_load.html', {'title': 'Steam Temperature At Any Load Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_secondary_fluid_inlet_temperature_at_any_load_calculator(request):
    return render(request, 'qehsfcalculators/environment/secondary_fluid_inlet_temperature_at_any_load.html', {'title': 'Secondary Fluid Inlet Temperature At Any Load Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_secondary_inlet_temperature_at_any_load_calculator(request):
    return render(request, 'qehsfcalculators/environment/secondary_inlet_temperature_at_any_load.html', {'title': 'Secondary Inlet Temperature At Any Load Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_stall_load_for_a_variable_flow_secondary_calculator(request):
    return render(request, 'qehsfcalculators/environment/stall_load_for_a_variable_flow_secondary.html', {'title': 'Stall Load For A Variable Flow Secondary Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_short_term_corrosion_rate_stcr_calculator(request):
    return render(request, 'qehsfcalculators/environment/short_term_corrosion_rate_stcr.html', {'title': 'Short-Term Corrosion Rate (STCR) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_soil_landfill_cover_water_balance_calculator(request):
    return render(request, 'qehsfcalculators/environment/soil_landfill_cover_water_balance.html', {'title': 'Soil Landfill Cover Water Balance Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_shaded_wall_heat_conduction_calculator(request):
    return render(request, 'qehsfcalculators/environment/shaded_wall_heat_conduction.html', {'title': 'Shaded Wall Heat Conduction Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_solar_heat_gain_through_glass_calculator(request):
    return render(request, 'qehsfcalculators/environment/solar_heat_gain_through_glass.html', {'title': 'Solar Heat Gain Through Glass Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_sensible_heat_ratio_shr_calculator(request):
    return render(request, 'qehsfcalculators/environment/sensible_heat_ratio_shr.html', {'title': 'Sensible Heat Ratio (SHR) Calculator '})

@login_required
@subscription_required(plan_type="corporate")
def environment_supply_airflow_calculator(request):
    return render(request, 'qehsfcalculators/environment/supply_airflow.html', {'title': 'Supply Airflow Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_settling_equation_general_spherical_calculator(request):
    return render(request, 'qehsfcalculators/environment/settling_equation_general_spherical.html', {'title': 'Settling Equation (General-Spherical) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_settling_velocity_stokes_law_calculator(request):
    return render(request, 'qehsfcalculators/environment/settling_velocity_stokes_law.html')

@login_required
@subscription_required(plan_type="corporate")
def environment_sensible_heat_gain_from_people_calculator(request):
    return render(request, 'qehsfcalculators/environment/sensible_heat_gain_from_people.html', {'title': 'Sensible Heat Gain from People Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_settling_net_force_calculator(request):
    return render(request, 'qehsfcalculators/environment/settling_net_force.html', {'title': 'Settling Net Force Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_settling_drag_force_calculator(request):
    return render(request, 'qehsfcalculators/environment/settling_drag_force.html', {'title': 'Settling Drag Force Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_salt_flux_through_the_membrane_calculator(request):
    return render(request, 'qehsfcalculators/environment/salt_flux_through_the_membrane.html', {'title': 'Salt Flux Through the Membrane Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_settling_terminal_velocity_calculator(request):
    return render(request, 'qehsfcalculators/environment/settling_terminal_velocity.html', {'title': 'Settling Terminal Velocity Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_settling_spherical_particle_volume_calculator(request):
    return render(request, 'qehsfcalculators/environment/settling_spherical_particle_volume.html', {'title': 'Settling Spherical Particle Volume Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_settling_projected_area_of_a_spherical_particle_calculator(request):
    return render(request, 'qehsfcalculators/environment/settling_projected_area_of_a_spherical_particle.html', {'title': 'Settling Projected Area of a Spherical Particle Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_settling_reynolds_number_calculator(request):
    return render(request, 'qehsfcalculators/environment/settling_reynolds_number.html', {'title': 'Settling Reynolds Number Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_soak_pit_volume_calculator(request):
    return render(request, 'qehsfcalculators/environment/soak_pit_volume.html', {'title': 'Soak Pit Volume Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_sludge_retention_time_srt_and_specific_substrate_utilization_rate_calculator(request):
    return render(request, 'qehsfcalculators/environment/sludge_retention_time_srt_and_specific_substrate_utilization_rate.html', {'title': 'Sludge Retention Time (SRT) And Specific Substrate Utilization Rate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_settling_overflow_rate_q_calculator(request):
    return render(request, 'qehsfcalculators/environment/settling_overflow_rate_q₀.html', {'title': 'Settling Overflow Rate (q₀) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_sedimentation_tank_volume_v_calculator(request):
    return render(request, 'qehsfcalculators/environment/sedimentation_tank_volume_v.html', {'title': 'Sedimentation Tank Volume (V) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_sedimentation_tank_surface_area_a_calculator(request):
    return render(request, 'qehsfcalculators/environment/sedimentation_tank_surface_area_a.html', {'title': 'Sedimentation Tank Surface Area (A) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_sedimentation_tank_dimensions_calculator(request):
    return render(request, 'qehsfcalculators/environment/sedimentation_tank_dimensions.html', {'title': 'Sedimentation Tank Dimensions Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_sedimentation_overflow_rate_calculator(request):
    return render(request, 'qehsfcalculators/environment/sedimentation_overflow_rate.html', {'title': 'Sedimentation Overflow Rate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_scouring_velocity_v_schields_formula_calculator(request):
    return render(request, 'qehsfcalculators/environment/scouring_velocity_v_schields_formula.html', {'title': 'Scouring Velocity (V) Calculator - Schield’s Formula'})

@login_required
@subscription_required(plan_type="corporate")
def environment_sludge_recirculation_rate_qr_calculator(request):
    return render(request, 'qehsfcalculators/environment/sludge_recirculation_rate_qr.html', {'title': 'Sludge Recirculation Rate (Qr) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_solubility_product_ksp_calculator(request):
    return render(request, 'qehsfcalculators/environment/solubility_product_ksp.html', {'title': 'Solubility Product (Ksp) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_thermodynamic_temperature_calculator(request):
    return render(request, 'qehsfcalculators/environment/thermodynamic_temperature.html', {'title': 'Thermodynamic temperature calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_travel_carbpon_footprint_calculator(request):
    return render(request, 'qehsfcalculators/environment/travel_carbpon_footprint.html', {'title': 'Travel Carbpon footprint calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_thermal_transmittance_u_from_the_individual_thicknesses_and_conductivities_calculator(request):
    return render(request, 'qehsfcalculators/environment/thermal_transmittance_u_from_the_individual_thicknesses_and_conductivities.html', {'title': 'Thermal transmittance (U) from the individual thicknesses and conductivities'})

@login_required
@subscription_required(plan_type="corporate")
def environment_thermal_transmittance_u_from_the_individual_thermal_resistances_calculator(request):
    return render(request, 'qehsfcalculators/environment/thermal_transmittance_u_from_the_individual_thermal_resistances.html', {'title': 'Thermal transmittance (U) from the individual thermal resistances'})

@login_required
@subscription_required(plan_type="corporate")
def environment_thermal_transmittance_u_value_calculator(request):
    return render(request, 'qehsfcalculators/environment/thermal_transmittance_u_value.html', {'title': 'Thermal Transmittance (U-Value) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_thermal_resistivity_from_conductivity_calculator(request):
    return render(request, 'qehsfcalculators/environment/thermal_resistivity_from_conductivity.html', {'title': 'Thermal Resistivity from conductivity Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_tds_density_method_calculator(request):
    return render(request, 'qehsfcalculators/environment/tds_density_method.html', {'title': 'TDS Calculator (Density Method)'})

@login_required
@subscription_required(plan_type="corporate")
def environment_tds_total_dissolved_solids_conductivity_calculator(request):
    return render(request, 'qehsfcalculators/environment/tds_total_dissolved_solids_conductivity.html', {'title': 'TDS (Total Dissolved Solids) conductivity Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_transient_mass_balance_calculator(request):
    return render(request, 'qehsfcalculators/environment/transient_mass_balance.html', {'title': 'Transient Mass Balance Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_transition_flow_general_velocity_calculator(request):
    return render(request, 'qehsfcalculators/environment/transition_flow_general_velocity.html', {'title': 'Transition Flow General Velocity Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_total_height_of_soak_pit_calculator(request):
    return render(request, 'qehsfcalculators/environment/total_height_of_soak_pit.html', {'title': 'Total Height of Soak Pit Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_two_phase_flow_parameter_calculator(request):
    return render(request, 'qehsfcalculators/environment/two_phase_flow_parameter.html', {'title': 'Two-Phase Flow Parameter Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_threshold_limit_value_tlv_for_silica_dust_calculator(request):
    return render(request, 'qehsfcalculators/environment/threshold_limit_value_tlv_for_silica_dust.html', {'title': 'Threshold Limit Value (TLV) Calculator for Silica Dust'})

@login_required
@subscription_required(plan_type="corporate")
def environment_time_to_settle_t_calculator(request):
    return render(request, 'qehsfcalculators/environment/time_to_settle_t₀.html', {'title': 'Time to Settle (t₀) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_u_factor_calculation_for_walls_calculator(request):
    return render(request, 'qehsfcalculators/environment/u_factor_calculation_for_walls.html', {'title': 'U-Factor Calculation for Walls'})

@login_required
@subscription_required(plan_type="corporate")
def environment_vapor_pressure_calculator(request):
    return render(request, 'qehsfcalculators/environment/vapor_pressure.html', {'title': 'Vapor Pressure Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_volumetric_flow_rate_calculator(request):
    return render(request, 'qehsfcalculators/environment/volumetric_flow_rate.html', {'title': 'Volumetric Flow Rate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_volumetric_flowrate_from_the_shedding_frequency_calculator(request):
    return render(request, 'qehsfcalculators/environment/volumetric_flowrate_from_the_shedding_frequency.html', {'title': 'Volumetric Flowrate From The Shedding Frequency Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_volumetric_flow_throw_an_equal_percentage_valve_calculator(request):
    return render(request, 'qehsfcalculators/environment/volumetric_flow_throw_an_equal_percentage_valve.html', {'title': 'Volumetric flow throw an equal percentage valve calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_vegan_footprint_calculator(request):
    return render(request, 'qehsfcalculators/environment/vegan_footprint.html', {'title': 'Vegan Footprint Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_vertical_settling_velocity_vt_calculator(request):
    return render(request, 'qehsfcalculators/environment/vertical_settling_velocity_vt.html', {'title': 'Vertical Settling Velocity (vt) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_vant_hoff_reaction_isochore_calculator(request):
    return render(request, 'qehsfcalculators/environment/vant_hoff_reaction_isochore.html')

@login_required
@subscription_required(plan_type="corporate")
def environment_wet_steam_enthalpy_calculator(request):
    return render(request, 'qehsfcalculators/environment/wet_steam_enthalpy.html', {'title': 'Wet Steam Enthalpy Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_waste_segregation_efficiency_calculator(request):
    return render(request, 'qehsfcalculators/environment/waste_segregation_efficiency.html', {'title': 'Waste segregation efficiency calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_water_mass_to_volumetric_flowrate_converter_calculator(request):
    return render(request, 'qehsfcalculators/environment/water_mass_to_volumetric_flowrate_converter.html', {'title': 'Water Mass to Volumetric Flowrate Converter Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_water_demand_fluctuation_calculator(request):
    return render(request, 'qehsfcalculators/environment/water_demand_fluctuation.html', {'title': 'Water Demand Fluctuation Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_water_pollutant_load_calculator(request):
    return render(request, 'qehsfcalculators/environment/water_pollutant_load.html', {'title': 'Water Pollutant Load Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_water_flux_through_the_membrane_calculator(request):
    return render(request, 'qehsfcalculators/environment/water_flux_through_the_membrane.html', {'title': 'Water Flux Through the Membrane Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_waterflux_ultrafiltration_calculator(request):
    return render(request, 'qehsfcalculators/environment/waterflux_ultrafiltration.html', {'title': 'Waterflux Ultrafiltration calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_wind_profile_calculator(request):
    return render(request, 'qehsfcalculators/environment/wind_profile.html', {'title': 'Wind Profile Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def environment_weir_flow_rate_q_calculator(request):
    return render(request, 'qehsfcalculators/environment/weir_flow_rate_q.html', {'title': 'Weir Flow Rate (Q) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_main_calculator(request):
    return render(request, 'qehsfcalculators/health/main.html', {'title': 'Main calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_army_body_fat_calculator(request):
    return render(request, 'qehsfcalculators/health/army_body_fat.html', {'title': 'Army Body Fat Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_adjusted_body_weight_calculator(request):
    return render(request, 'qehsfcalculators/health/adjusted_body_weight.html', {'title': 'Adjusted Body Weight Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_a_body_shape_index_absi_calculator(request):
    return render(request, 'qehsfcalculators/health/a_body_shape_index_absi.html', {'title': 'A Body Shape Index (ABSI) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_a1c_hemoglobin_a1c_to_average_blood_sugar_calculator(request):
    return render(request, 'qehsfcalculators/health/a1c_hemoglobin_a1c_to_average_blood_sugar.html', {'title': 'A1c Calculator – Hemoglobin A1c to Average Blood Sugar'})

@login_required
@subscription_required(plan_type="corporate")
def health_age_shock_index_age_si_calculator(request):
    return render(request, 'qehsfcalculators/health/age_shock_index_age_si.html', {'title': 'Age Shock Index (Age SI) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_alzheimers_life_expectancy_calculator(request):
    return render(request, 'qehsfcalculators/health/alzheimers_life_expectancy.html', {'title': 'Alzheimer’s Life Expectancy Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_ankle_brachial_index_abi_calculator(request):
    return render(request, 'qehsfcalculators/health/ankle_brachial_index_abi.html', {'title': 'Ankle-Brachial Index (ABI) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_bmi_calculator(request):
    return render(request, 'qehsfcalculators/health/bmi.html', {'title': 'BMI calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_bmi_for_kids_calculator(request):
    return render(request, 'qehsfcalculators/health/bmi_for_kids.html', {'title': 'BMI Calculator for Kids'})

@login_required
@subscription_required(plan_type="corporate")
def health_basal_metabolic_rate_bmr_calculator(request):
    return render(request, 'qehsfcalculators/health/basal_metabolic_rate_bmr.html', {'title': 'Basal metabolic rate (BMR) calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_body_roundness_index_bri_calculator(request):
    return render(request, 'qehsfcalculators/health/body_roundness_index_bri.html', {'title': 'Body Roundness Index (BRI) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_body_fat_us_navy_method_calculator(request):
    return render(request, 'qehsfcalculators/health/body_fat_us_navy_method.html', {'title': 'Body Fat Calculator (U.S. Navy Method)'})

@login_required
@subscription_required(plan_type="corporate")
def health_body_adiposity_index_bai_calculator(request):
    return render(request, 'qehsfcalculators/health/body_adiposity_index_bai.html', {'title': 'Body Adiposity Index (BAI) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_body_frame_size_calculator(request):
    return render(request, 'qehsfcalculators/health/body_frame_size.html', {'title': 'Body Frame Size Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_body_surface_area_bsa_calculator(request):
    return render(request, 'qehsfcalculators/health/body_surface_area_bsa.html', {'title': 'Body Surface Area (BSA) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_blood_sugar_converter_calculator(request):
    return render(request, 'qehsfcalculators/health/blood_sugar_converter.html', {'title': 'Blood Sugar Converter'})

@login_required
@subscription_required(plan_type="corporate")
def health_bedridden_patient_height_estimator_calculator(request):
    return render(request, 'qehsfcalculators/health/bedridden_patient_height_estimator.html', {'title': 'Bedridden Patient Height Estimator'})

@login_required
@subscription_required(plan_type="corporate")
def health_bedridden_patient_weight_estimator_calculator(request):
    return render(request, 'qehsfcalculators/health/bedridden_patient_weight_estimator.html', {'title': 'Bedridden Patient Weight Estimator'})

@login_required
@subscription_required(plan_type="corporate")
def health_baby_milk_intake_calculator(request):
    return render(request, 'qehsfcalculators/health/baby_milk_intake.html', {'title': 'Baby Milk Intake Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_cardiac_index_calculator(request):
    return render(request, 'qehsfcalculators/health/cardiac_index.html', {'title': 'Cardiac Index Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_daily_drinking_water_intake_calculator(request):
    return render(request, 'qehsfcalculators/health/daily_drinking_water_intake.html', {'title': 'Daily Drinking Water Intake Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_dietary_reference_intake_dri_calculator(request):
    return render(request, 'qehsfcalculators/health/dietary_reference_intake_dri.html', {'title': 'Dietary Reference Intake (DRI) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_diabetes_risk_estimate_your_75_year_risk_calculator(request):
    return render(request, 'qehsfcalculators/health/diabetes_risk_estimate_your_75_year_risk.html', {'title': 'Diabetes Risk Calculator – Estimate Your 7.5-Year Risk'})

@login_required
@subscription_required(plan_type="corporate")
def health_depression_screening_by_phq_2_calculator(request):
    return render(request, 'qehsfcalculators/health/depression_screening_by_phq_2.html', {'title': 'Depression Screening by PHQ-2 Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_dose_response_probit_calculator(request):
    return render(request, 'qehsfcalculators/health/dose_response_probit.html', {'title': 'Dose-Response Probit Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_diet_risk_score_calculator(request):
    return render(request, 'qehsfcalculators/health/diet_risk_score.html', {'title': 'Diet Risk Score Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_estimated_average_glucose_calculator(request):
    return render(request, 'qehsfcalculators/health/estimated_average_glucose.html', {'title': 'Estimated Average Glucose Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_epworth_sleepiness_scale_ess_calculator(request):
    return render(request, 'qehsfcalculators/health/epworth_sleepiness_scale_ess.html', {'title': 'Epworth Sleepiness Scale (ESS) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_fat_free_mass_index_ffmi_calculator(request):
    return render(request, 'qehsfcalculators/health/fat_free_mass_index_ffmi.html', {'title': 'Fat-Free Mass Index (FFMI) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_fiber_intake_calculator(request):
    return render(request, 'qehsfcalculators/health/fiber_intake.html', {'title': 'Fiber Intake Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_generalized_anxiety_disorder_assessment_calculator(request):
    return render(request, 'qehsfcalculators/health/generalized_anxiety_disorder_assessment.html', {'title': 'Generalized Anxiety Disorder Assessment Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_gupta_perioperative_risk_calculator(request):
    return render(request, 'qehsfcalculators/health/gupta_perioperative_risk.html', {'title': 'Gupta Perioperative Risk Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_heat_stress_index_hsi_calculator(request):
    return render(request, 'qehsfcalculators/health/heat_stress_index_hsi.html', {'title': 'heat stress index (HSI) calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_healthy_weight_calculator(request):
    return render(request, 'qehsfcalculators/health/healthy_weight.html', {'title': 'Healthy Weight Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_heaviness_of_smoking_index_hsi_calculator(request):
    return render(request, 'qehsfcalculators/health/heaviness_of_smoking_index_hsi.html', {'title': 'Heaviness of Smoking Index (HSI) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_hand_arm_vibration_exposure_hav_a8_value_calculator(request):
    return render(request, 'qehsfcalculators/health/hand_arm_vibration_exposure_hav_a8_value.html', {'title': 'Hand-Arm Vibration Exposure (HAV) Calculator-A(8) Value'})

@login_required
@subscription_required(plan_type="corporate")
def health_happiness_calculator(request):
    return render(request, 'qehsfcalculators/health/happiness.html', {'title': 'Happiness Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_heart_score_calculator(request):
    return render(request, 'qehsfcalculators/health/heart_score.html', {'title': 'HEART Score Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_homa_ir_insulin_resistance_calculator(request):
    return render(request, 'qehsfcalculators/health/homa_ir_insulin_resistance.html', {'title': 'HOMA-IR Calculator — Insulin Resistance'})

@login_required
@subscription_required(plan_type="corporate")
def health_ideal_weight_calculator(request):
    return render(request, 'qehsfcalculators/health/ideal_weight.html', {'title': 'Ideal Weight Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_injury_severity_score_iss_calculator(request):
    return render(request, 'qehsfcalculators/health/injury_severity_score_iss.html', {'title': 'Injury Severity Score (ISS) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_karvonen_formula_calculator(request):
    return render(request, 'qehsfcalculators/health/karvonen_formula.html', {'title': 'Karvonen Formula Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_kidney_failure_risk_calculator(request):
    return render(request, 'qehsfcalculators/health/kidney_failure_risk.html', {'title': 'Kidney Failure Risk Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_kidney_stone_for_percutaneous_nephrolithotomy_calculator(request):
    return render(request, 'qehsfcalculators/health/kidney_stone_for_percutaneous_nephrolithotomy.html', {'title': 'Kidney STONE Calculator for Percutaneous Nephrolithotomy'})

@login_required
@subscription_required(plan_type="corporate")
def health_lean_body_mass_lbm_calculator(request):
    return render(request, 'qehsfcalculators/health/lean_body_mass_lbm.html', {'title': 'Lean Body Mass (LBM) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_lille_score_for_alcoholic_hepatitis_calculator(request):
    return render(request, 'qehsfcalculators/health/lille_score_for_alcoholic_hepatitis.html', {'title': 'Lille Score Calculator for Alcoholic Hepatitis'})

@login_required
@subscription_required(plan_type="corporate")
def health_metabolic_syndrome_calculator(request):
    return render(request, 'qehsfcalculators/health/metabolic_syndrome.html', {'title': 'Metabolic Syndrome Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_modified_shock_index_msi_calculator(request):
    return render(request, 'qehsfcalculators/health/modified_shock_index_msi.html', {'title': 'Modified Shock Index (MSI) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_mean_arterial_pressure_map_and_pulse_pressure_pp_calculator(request):
    return render(request, 'qehsfcalculators/health/mean_arterial_pressure_map_and_pulse_pressure_pp.html', {'title': 'Mean Arterial Pressure (MAP) & Pulse Pressure (PP) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_noise_exposure_level_leq_calculator(request):
    return render(request, 'qehsfcalculators/health/noise_exposure_level_leq.html', {'title': 'Noise  exposure level (Leq)  calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_ponderal_index_pi_calculator(request):
    return render(request, 'qehsfcalculators/health/ponderal_index_pi.html', {'title': 'Ponderal Index (PI) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_protein_intake_calculator(request):
    return render(request, 'qehsfcalculators/health/protein_intake.html', {'title': 'Protein Intake Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_plasma_volume_calculator(request):
    return render(request, 'qehsfcalculators/health/plasma_volume.html', {'title': 'Plasma Volume Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_relative_fat_mass_rfm_calculator(request):
    return render(request, 'qehsfcalculators/health/relative_fat_mass_rfm.html', {'title': 'Relative Fat Mass (RFM) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_rapid_entire_body_assessment_reba_calculator(request):
    return render(request, 'qehsfcalculators/health/rapid_entire_body_assessment_reba.html', {'title': 'Rapid Entire Body Assessment (REBA) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_sleep_calculator(request):
    return render(request, 'qehsfcalculators/health/sleep.html', {'title': 'Sleep Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_shock_index_si_calculator(request):
    return render(request, 'qehsfcalculators/health/shock_index_si.html', {'title': 'Shock Index (SI) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_stroke_volume_sv_calculator(request):
    return render(request, 'qehsfcalculators/health/stroke_volume_sv.html', {'title': 'Stroke Volume (SV) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_stroke_volume_index_svi_calculator(request):
    return render(request, 'qehsfcalculators/health/stroke_volume_index_svi.html', {'title': 'Stroke Volume Index (SVI) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_threshold_limit_value_tlv_calculator(request):
    return render(request, 'qehsfcalculators/health/threshold_limit_value_tlv.html', {'title': 'Threshold Limit Value (TLV) calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_total_recordable_occupational_illness_frequency_trcf_ill_calculator(request):
    return render(request, 'qehsfcalculators/health/total_recordable_occupational_illness_frequency_trcf_ill.html', {'title': 'Total Recordable Occupational Illness Frequency (TRCF-ILL) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_time_of_death_calculator(request):
    return render(request, 'qehsfcalculators/health/time_of_death.html', {'title': 'Time of Death Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_workplace_exposure_limit_wel_calculator(request):
    return render(request, 'qehsfcalculators/health/workplace_exposure_limit_wel.html', {'title': 'Workplace Exposure Limit (WEL) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_weight_loss_calculator(request):
    return render(request, 'qehsfcalculators/health/weight_loss.html', {'title': 'Weight Loss Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_weight_gain_calculator(request):
    return render(request, 'qehsfcalculators/health/weight_gain.html', {'title': 'Weight Gain Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_waist_to_hip_ratio_calculator(request):
    return render(request, 'qehsfcalculators/health/waist_to_hip_ratio.html', {'title': 'Waist-to-Hip Ratio Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_waist_to_height_ratio_calculator(request):
    return render(request, 'qehsfcalculators/health/waist_to_height_ratio.html', {'title': 'Waist-to-Height Ratio Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def health_winters_formula_calculator(request):
    return render(request, 'qehsfcalculators/health/winters_formula.html')

@login_required
@subscription_required(plan_type="corporate")
def safety_main_calculator(request):
    return render(request, 'qehsfcalculators/safety/main.html', {'title': 'Main calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_accident_rate_calculator(request):
    return render(request, 'qehsfcalculators/safety/accident_rate.html', {'title': 'Accident rate calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_average_resolution_time_art_calculator(request):
    return render(request, 'qehsfcalculators/safety/average_resolution_time_art.html', {'title': 'Average Resolution Time (ART) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_averaging_thickness_for_corroded_areas_calculator(request):
    return render(request, 'qehsfcalculators/safety/averaging_thickness_for_corroded_areas.html', {'title': 'Averaging Thickness for Corroded Areas'})

@login_required
@subscription_required(plan_type="corporate")
def safety_allowable_leakage_and_additional_leakage_calculation_calculator(request):
    return render(request, 'qehsfcalculators/safety/allowable_leakage_and_additional_leakage_calculation.html', {'title': 'Allowable Leakage and Additional Leakage Calculation'})

@login_required
@subscription_required(plan_type="corporate")
def safety_approximate_mass_flux_formula_all_liquid_inlet_condition_calculator(request):
    return render(request, 'qehsfcalculators/safety/approximate_mass_flux_formula_all_liquid_inlet_condition.html', {'title': 'Approximate Mass Flux Formula (All-Liquid Inlet Condition) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_accident_severity_index_asi_calculator(request):
    return render(request, 'qehsfcalculators/safety/accident_severity_index_asi.html', {'title': 'Accident Severity Index (ASI) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_average_individual_risk_calculator(request):
    return render(request, 'qehsfcalculators/safety/average_individual_risk.html', {'title': 'Average Individual Risk Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_ad_merkblatt_valves_minimum_flow_area_for_steam_calculator(request):
    return render(request, 'qehsfcalculators/safety/ad_merkblatt_valves_minimum_flow_area_for_steam.html', {'title': 'AD-Merkblatt valves - Minimum flow area for steam'})

@login_required
@subscription_required(plan_type="corporate")
def safety_ad_merkblatt_valves_minimum_flow_area_for_dry_gases_and_air_calculator(request):
    return render(request, 'qehsfcalculators/safety/ad_merkblatt_valves_minimum_flow_area_for_dry_gases_and_air.html', {'title': 'AD-Merkblatt valves - Minimum flow area for Dry Gases And Air'})

@login_required
@subscription_required(plan_type="corporate")
def safety_asme_api_rp_520_valves_minimum_flow_area_for_liquids_calculator(request):
    return render(request, 'qehsfcalculators/safety/asme_api_rp_520_valves_minimum_flow_area_for_liquids.html', {'title': 'ASME (API RP 520) valves - Minimum Flow Area For Liquids Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_asme_api_rp_520_valves_nozzle_gas_constant_cg_calculator(request):
    return render(request, 'qehsfcalculators/safety/asme_api_rp_520_valves_nozzle_gas_constant_cg.html', {'title': 'ASME (API RP 520) valves - Nozzle Gas Constant (Cg) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_asme_api_rp_520_valves_backpressure_correction_factor_calculator(request):
    return render(request, 'qehsfcalculators/safety/asme_api_rp_520_valves_backpressure_correction_factor.html', {'title': 'ASME (API RP 520) valves - Backpressure Correction Factor Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_asme_api_rp_520_valves_bellows_balanced_valves_calculator(request):
    return render(request, 'qehsfcalculators/safety/asme_api_rp_520_valves_bellows_balanced_valves.html', {'title': 'ASME (API RP 520) valves - Bellows balanced valves Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_ad_merkblatt_minimum_flow_area_for_liquids_calculator(request):
    return render(request, 'qehsfcalculators/safety/ad_merkblatt_minimum_flow_area_for_liquids.html', {'title': 'AD-MERKBLATT Minimum Flow Area for Liquids Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_asme_api_rp_520_valves_conventional_valves_calculator(request):
    return render(request, 'qehsfcalculators/safety/asme_api_rp_520_valves_conventional_valves.html', {'title': 'ASME (API RP 520) valves - Conventional valves Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_asme_api_rp_520_valves_reynolds_number_metric_units_calculator(request):
    return render(request, 'qehsfcalculators/safety/asme_api_rp_520_valves_reynolds_number_metric_units.html', {'title': 'ASME (API RP 520) valves - Reynolds Number- Metric Units Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_asme_api_rp_520_valves_minimum_flow_area_for_steam_calculator(request):
    return render(request, 'qehsfcalculators/safety/asme_api_rp_520_valves_minimum_flow_area_for_steam.html', {'title': 'ASME (API RP 520) Valves Minimum Flow Area For Steam Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_asme_api_rp_520_valves_minimum_flow_area_for_dry_gases_and_air_calculator(request):
    return render(request, 'qehsfcalculators/safety/asme_api_rp_520_valves_minimum_flow_area_for_dry_gases_and_air.html', {'title': 'ASME (API RP 520) Valves - Minimum Flow Area for Dry Gases and Air Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_asme_api_rp_520_valves_reynolds_number_imperial_units_calculator(request):
    return render(request, 'qehsfcalculators/safety/asme_api_rp_520_valves_reynolds_number_imperial_units_calculator.html', {'title': 'ASME (API RP 520) Valves - Reynolds number imperial units Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_bs_6759_minimum_orifice_area_for_steam_calculator(request):
    return render(request, 'qehsfcalculators/safety/bs_6759_minimum_orifice_area_for_steam.html', {'title': 'BS-6759 Minimum Orifice Area Calculator for Steam'})

@login_required
@subscription_required(plan_type="corporate")
def safety_bs_6759_minimum_orifice_area_for_air_calculator(request):
    return render(request, 'qehsfcalculators/safety/bs_6759_minimum_orifice_area_for_air.html', {'title': 'BS-6759 Minimum Orifice Area Calculator for Air'})

@login_required
@subscription_required(plan_type="corporate")
def safety_bs_6759_valves_minimum_orifice_area_for_liquids_calculator(request):
    return render(request, 'qehsfcalculators/safety/bs_6759_valves_minimum_orifice_area_for_liquids.html', {'title': 'BS 6759 Valves Minimum Orifice Area For Liquids Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_bs_6759_valves_minimum_orifice_area_for_hot_water_calculator(request):
    return render(request, 'qehsfcalculators/safety/bs_6759_valves_minimum_orifice_area_for_hot_water.html', {'title': 'BS 6759 Valves Minimum Orifice Area For Hot Water Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_bs_6759_valves_nozzle_gas_constant_calculator(request):
    return render(request, 'qehsfcalculators/safety/bs_6759_valves_nozzle_gas_constant.html', {'title': 'BS 6759 Valves - Nozzle Gas constant Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_bs_6759_minimum_orifice_area_for_dry_gases_calculator(request):
    return render(request, 'qehsfcalculators/safety/bs_6759_minimum_orifice_area_for_dry_gases.html', {'title': 'BS-6759 Minimum Orifice Area Calculator for Dry Gases'})

@login_required
@subscription_required(plan_type="corporate")
def safety_bs_en_4126_minimum_orifice_area_for_air_and_dry_gas_calculator(request):
    return render(request, 'qehsfcalculators/safety/bs_en_4126_minimum_orifice_area_for_air_and_dry_gas.html', {'title': 'BS EN 4126 Minimum Orifice Area Calculator for Air & Dry Gas'})

@login_required
@subscription_required(plan_type="corporate")
def safety_bs_en_4126_minimum_orifice_area_for_liquids_calculator(request):
    return render(request, 'qehsfcalculators/safety/bs_en_4126_minimum_orifice_area_for_liquids.html', {'title': 'BS EN 4126 Minimum Orifice Area Calculator for Liquids'})

@login_required
@subscription_required(plan_type="corporate")
def safety_bs_en_4126_valves_minimum_orifice_area_for_steam_air_and_dry_gas_at_critical_flow_calculator(request):
    return render(request, 'qehsfcalculators/safety/bs_en_4126_valves_minimum_orifice_area_for_steam_air_and_dry_gas_at_critical_flow.html', {'title': 'BS EN 4126 Valves - Minimum Orifice Area For Steam, Air And Dry Gas At Critical Flow Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_bs_en_4126_valves_minimum_flow_area_for_wet_steam_at_crilical_flow_calculator(request):
    return render(request, 'qehsfcalculators/safety/bs_en_4126_valves_minimum_flow_area_for_wet_steam_at_crilical_flow.html', {'title': 'BS EN 4126 Valves - Minimum Flow Area For Wet Steam At Crilical Flow Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_bit_wear_and_effeiciency_calculator(request):
    return render(request, 'qehsfcalculators/safety/bit_wear_and_effeiciency.html', {'title': 'Bit wear and effeiciency calcualtor'})

@login_required
@subscription_required(plan_type="corporate")
def safety_bernoullis_equation_multiplied_throughout_by_pg_calculator(request):
    return render(request, 'qehsfcalculators/safety/bernoullis_equation_multiplied_throughout_by_pg.html')

@login_required
@subscription_required(plan_type="corporate")
def safety_boyles_vent_area_calculator(request):
    return render(request, 'qehsfcalculators/safety/boyles_vent_area.html')

@login_required
@subscription_required(plan_type="corporate")
def safety_change_in_entropy_calculator(request):
    return render(request, 'qehsfcalculators/safety/change_in_entropy.html', {'title': 'Change in entropy calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_cost_of_an_accident_calculator(request):
    return render(request, 'qehsfcalculators/safety/cost_of_an_accident.html', {'title': 'Cost of an accident'})

@login_required
@subscription_required(plan_type="corporate")
def safety_casing_burst_pressure_calculator(request):
    return render(request, 'qehsfcalculators/safety/casing_burst_pressure.html', {'title': 'Casing burst pressure calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_casing_ccollapse_pressure_calculator(request):
    return render(request, 'qehsfcalculators/safety/casing_ccollapse_pressure.html', {'title': 'Casing ccollapse pressure calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_cement_volume_calculator(request):
    return render(request, 'qehsfcalculators/safety/cement_volume.html', {'title': 'Cement-volume-calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_cement_slurry_density_calculator(request):
    return render(request, 'qehsfcalculators/safety/cement_slurry_density.html', {'title': 'Cement-slurry-density-calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_condensate_velocity_of_a_pipe_calculator(request):
    return render(request, 'qehsfcalculators/safety/condensate_velocity_of_a_pipe.html', {'title': 'condensate velocity of a pipe calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_cooling_water_flowrate_for_desuperheater_calculator(request):
    return render(request, 'qehsfcalculators/safety/cooling_water_flowrate_for_desuperheater.html', {'title': 'Cooling Water Flowrate Calculator for Desuperheater'})

@login_required
@subscription_required(plan_type="corporate")
def safety_capacitance_law_calculator(request):
    return render(request, 'qehsfcalculators/safety/capacitance_law.html', {'title': 'capacitance law calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_cold_differential_pressure_calculator(request):
    return render(request, 'qehsfcalculators/safety/cold_differential_pressure.html', {'title': 'Cold Differential Pressure Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_coefficient_of_discharge_calculator(request):
    return render(request, 'qehsfcalculators/safety/coefficient_of_discharge.html', {'title': 'Coefficient of Discharge Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_curtain_area_of_safety_valve_calculator(request):
    return render(request, 'qehsfcalculators/safety/curtain_area_of_safety_valve.html', {'title': 'Curtain Area of Safety Valve Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_compressibility_factor_for_compressible_steam_and_dry_gas_calculator(request):
    return render(request, 'qehsfcalculators/safety/compressibility_factor_for_compressible_steam_and_dry_gas.html', {'title': 'Compressibility Factor For Compressible Steam And Dry Gas Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_crane_capacity_index_cci_calculator(request):
    return render(request, 'qehsfcalculators/safety/crane_capacity_index_cci.html', {'title': 'Crane Capacity Index (CCI) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_crane_wind_speed_allowance_calculator(request):
    return render(request, 'qehsfcalculators/safety/crane_wind_speed_allowance.html', {'title': 'Crane Wind Speed Allowance Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_composite_risk_calculator(request):
    return render(request, 'qehsfcalculators/safety/composite_risk.html', {'title': 'Composite Risk Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_critical_pressure_ratio_for_dry_steam_and_gases_calculator(request):
    return render(request, 'qehsfcalculators/safety/critical_pressure_ratio_for_dry_steam_and_gases.html', {'title': 'Critical Pressure Ratio For Dry Steam And Gases Calcualtor'})

@login_required
@subscription_required(plan_type="corporate")
def safety_collision_rate_cr_calculator(request):
    return render(request, 'qehsfcalculators/safety/collision_rate_cr.html', {'title': 'Collision Rate (CR) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_crash_reduction_factor_crf_calculator(request):
    return render(request, 'qehsfcalculators/safety/crash_reduction_factor_crf.html', {'title': 'Crash Reduction Factor (CRF) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_concrete_element_weight_calculator(request):
    return render(request, 'qehsfcalculators/safety/concrete_element_weight.html', {'title': 'Concrete Element Weight Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_corrective_action_closure_rate_calculator(request):
    return render(request, 'qehsfcalculators/safety/corrective_action_closure_rate.html', {'title': 'Corrective Action Closure Rate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_chemical_exposure_burn_severity_rate_calculator(request):
    return render(request, 'qehsfcalculators/safety/chemical_exposure_burn_severity_rate.html', {'title': 'Chemical Exposure Burn Severity Rate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_compressible_flow_crane_equation_3_20_calculator(request):
    return render(request, 'qehsfcalculators/safety/compressible_flow_crane_equation_3_20.html', {'title': 'Compressible Flow Calculator (Crane Equation 3-20)'})

@login_required
@subscription_required(plan_type="corporate")
def safety_clausius_clapeyron_equation_calculator(request):
    return render(request, 'qehsfcalculators/safety/clausius_clapeyron_equation.html', {'title': 'Clausius-Clapeyron Equation Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_composite_risk_calculator(request):
    return render(request, 'qehsfcalculators/safety/composite_risk.html', {'title': 'Composite Risk Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_density_of_a_material_calculator(request):
    return render(request, 'qehsfcalculators/safety/density_of_a_material.html', {'title': 'Density of a material calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_daltons_law_of_partial_pressures_calculator(request):
    return render(request, 'qehsfcalculators/safety/daltons_law_of_partial_pressures.html')

@login_required
@subscription_required(plan_type="corporate")
def safety_drilling_torque_and_drag_calculator(request):
    return render(request, 'qehsfcalculators/safety/drilling_torque_and_drag.html', {'title': 'Drilling Torque & Drag Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_dynamic_lifting_load_calculator(request):
    return render(request, 'qehsfcalculators/safety/dynamic_lifting_load.html', {'title': 'Dynamic Lifting Load Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_double_t_beam_weight_calculator(request):
    return render(request, 'qehsfcalculators/safety/double_t_beam_weight.html', {'title': 'Double-T Beam Weight Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_earthing_system_calculator(request):
    return render(request, 'qehsfcalculators/safety/earthing_system.html', {'title': 'Earthing system calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_enery_transfor_calculator(request):
    return render(request, 'qehsfcalculators/safety/enery_transfor.html', {'title': 'Enery transfor calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_erogonomic_risk_score_calculator(request):
    return render(request, 'qehsfcalculators/safety/erogonomic_risk_score.html', {'title': 'Erogonomic risk score calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_emergency_drill_success_rate_calculator(request):
    return render(request, 'qehsfcalculators/safety/emergency_drill_success_rate.html', {'title': 'Emergency drill success rate calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_excavation_slope_calculator(request):
    return render(request, 'qehsfcalculators/safety/excavation_slope.html', {'title': 'Excavation Slope Calculator     '})

@login_required
@subscription_required(plan_type="corporate")
def safety_energy_requirement_for_a_flow_type_application_calculator(request):
    return render(request, 'qehsfcalculators/safety/energy_requirement_for_a_flow_type_application.html', {'title': 'Energy Requirement for a Flow-Type Application Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_equivalent_skin_factor_calculator(request):
    return render(request, 'qehsfcalculators/safety/equivalent_skin_factor.html', {'title': 'Equivalent Skin Factor Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_employee_training_cost_calculator(request):
    return render(request, 'qehsfcalculators/safety/employee_training_cost.html', {'title': 'Employee Training Cost Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_exothermic_reaction_burn_severity_calculator(request):
    return render(request, 'qehsfcalculators/safety/exothermic_reaction_burn_severity.html', {'title': 'Exothermic Reaction Burn Severity Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_expected_accident_rate_ear_calculator(request):
    return render(request, 'qehsfcalculators/safety/expected_accident_rate_ear.html', {'title': 'Expected Accident Rate (EAR) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_fluid_loss_for_drilling_calculator(request):
    return render(request, 'qehsfcalculators/safety/fluid_loss_for_drilling.html', {'title': 'Fluid loss calculator for drilling'})

@login_required
@subscription_required(plan_type="corporate")
def safety_fracture_gradient_calculator(request):
    return render(request, 'qehsfcalculators/safety/fracture_gradient.html', {'title': 'Fracture Gradient Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_fracture_width_pkn_model_calculator(request):
    return render(request, 'qehsfcalculators/safety/fracture_width_pkn_model.html', {'title': 'Fracture Width Calculator (PKN Model)'})

@login_required
@subscription_required(plan_type="corporate")
def safety_fracture_volume_pkn_model_calculator(request):
    return render(request, 'qehsfcalculators/safety/fracture_volume_pkn_model.html', {'title': 'Fracture Volume Calculator (PKN Model)'})

@login_required
@subscription_required(plan_type="corporate")
def safety_fall_clearance_calculator(request):
    return render(request, 'qehsfcalculators/safety/fall_clearance.html', {'title': 'Fall Clearance Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_fluid_velocity_pitot_tube_calculator(request):
    return render(request, 'qehsfcalculators/safety/fluid_velocity_pitot_tube.html', {'title': 'Fluid velocity calculaor (pitot tube)'})

@login_required
@subscription_required(plan_type="corporate")
def safety_flow_area_of_safety_valve_calculator(request):
    return render(request, 'qehsfcalculators/safety/flow_area_of_safety_valve.html', {'title': 'Flow Area of Safety Valve Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_friction_factor_for_fluids_colebrook_white_calculator(request):
    return render(request, 'qehsfcalculators/safety/friction_factor_for_fluids_colebrook_white.html', {'title': 'Friction Factor For Fluids (Colebrook-White)  Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_formwork_adhesion_calculator(request):
    return render(request, 'qehsfcalculators/safety/formwork_adhesion.html', {'title': 'Formwork Adhesion Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_fatal_accident_rate_far_calculator(request):
    return render(request, 'qehsfcalculators/safety/fatal_accident_rate_far.html', {'title': 'Fatal Accident Rate (FAR) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_gas_flow_rate_calculator(request):
    return render(request, 'qehsfcalculators/safety/gas_flow_rate.html', {'title': 'Gas Flow Rate Calculator  '})

@login_required
@subscription_required(plan_type="corporate")
def safety_hydraulic_vertical_pressure_calculator(request):
    return render(request, 'qehsfcalculators/safety/hydraulic_vertical_pressure.html', {'title': 'Hydraulic Vertical Pressure Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_horizontal_stress_breckels_and_van_eekelen_model_calculator(request):
    return render(request, 'qehsfcalculators/safety/horizontal_stress_breckels_and_van_eekelen_model.html', {'title': 'Horizontal Stress Calculator (Breckels and van Eekelen Model)'})

@login_required
@subscription_required(plan_type="corporate")
def safety_hazard_reporting_rate_calculator(request):
    return render(request, 'qehsfcalculators/safety/hazard_reporting_rate.html', {'title': 'Hazard Reporting Rate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_hazard_quotient_hq_chemical_exposure_risk_calculator(request):
    return render(request, 'qehsfcalculators/safety/hazard_quotient_hq_chemical_exposure_risk.html', {'title': 'Hazard Quotient (HQ) Calculator – Chemical Exposure Risk'})

@login_required
@subscription_required(plan_type="corporate")
def safety_hazard_score_calculator(request):
    return render(request, 'qehsfcalculators/safety/hazard_score.html', {'title': 'Hazard Score Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_incidence_rate_calculator(request):
    return render(request, 'qehsfcalculators/safety/incidence_rate.html', {'title': 'Incidence Rate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_incident_frequency_rate_fr_calculator(request):
    return render(request, 'qehsfcalculators/safety/incident_frequency_rate_fr.html', {'title': 'Incident frequency rate (FR) calcualtor'})

@login_required
@subscription_required(plan_type="corporate")
def safety_incidents_and_near_misses_calculator(request):
    return render(request, 'qehsfcalculators/safety/incidents_and_near_misses.html', {'title': ' Incidents & Near Misses Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_ip_rating_checker_calculator(request):
    return render(request, 'qehsfcalculators/safety/ip_rating_checker.html', {'title': 'IP Rating Checker             '})

@login_required
@subscription_required(plan_type="corporate")
def safety_imperial_based_darcy_equation_for_determining_pressure_drop_due_to_frictional_resistance_calculator(request):
    return render(request, 'qehsfcalculators/safety/imperial_based_darcy_equation_for_determining_pressure_drop_due_to_frictional_resistance.html')

@login_required
@subscription_required(plan_type="corporate")
def safety_inflow_equation_calculator(request):
    return render(request, 'qehsfcalculators/safety/inflow_equation.html', {'title': 'Inflow Equation Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_inverse_square_law_calculator(request):
    return render(request, 'qehsfcalculators/safety/inverse_square_law.html', {'title': 'Inverse Square Law Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_initial_accident_rate_iar_calculator(request):
    return render(request, 'qehsfcalculators/safety/initial_accident_rate_iar.html', {'title': 'Initial Accident Rate (IAR) Calculato'})

@login_required
@subscription_required(plan_type="corporate")
def safety_job_safety_analysis_frequency_jsaf_calculator(request):
    return render(request, 'qehsfcalculators/safety/job_safety_analysis_frequency_jsaf.html', {'title': 'Job Safety Analysis Frequency (JSAF) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_job_safety_analysis_coverage_calculator(request):
    return render(request, 'qehsfcalculators/safety/job_safety_analysis_coverage.html', {'title': 'Job Safety Analysis Coverage Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_kick_tolerance_calculator(request):
    return render(request, 'qehsfcalculators/safety/kick_tolerance.html', {'title': 'Kick tolerance calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_kinetic_energy_in_steam_calculator(request):
    return render(request, 'qehsfcalculators/safety/kinetic_energy_in_steam.html', {'title': ' kinetic energy in steam  calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_kinetic_energy_calculator(request):
    return render(request, 'qehsfcalculators/safety/kinetic_energy.html', {'title': 'Kinetic Energy Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_kv_flow_coeffient_calculator(request):
    return render(request, 'qehsfcalculators/safety/kv_flow_coeffient.html', {'title': 'Kv flow coeffient calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_ladder_length_calculator(request):
    return render(request, 'qehsfcalculators/safety/ladder_length.html', {'title': 'Ladder Length  Calculator '})

@login_required
@subscription_required(plan_type="corporate")
def safety_lost_time_injury_incident_rate_calculator(request):
    return render(request, 'qehsfcalculators/safety/lost_time_injury_incident_rate.html', {'title': 'Lost Time Injury Incident Rate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_live_load_calculation_ll_calculator(request):
    return render(request, 'qehsfcalculators/safety/live_load_calculation_ll.html', {'title': 'live load calculation (LL)'})

@login_required
@subscription_required(plan_type="corporate")
def safety_load_distribution_per_leg_calculator(request):
    return render(request, 'qehsfcalculators/safety/load_distribution_per_leg.html', {'title': 'load distribution per leg'})

@login_required
@subscription_required(plan_type="corporate")
def safety_leading_safety_indicator_calculator(request):
    return render(request, 'qehsfcalculators/safety/leading_safety_indicator.html', {'title': 'leading safety indicator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_lost_time_case_rate_ltc_calculator(request):
    return render(request, 'qehsfcalculators/safety/lost_time_case_rate_ltc.html', {'title': 'Lost Time Case Rate (LTC) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_long_term_corrosion_rate_ltcr_calculator(request):
    return render(request, 'qehsfcalculators/safety/long_term_corrosion_rate_ltcr.html', {'title': 'Long-Term Corrosion Rate (LTCR) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_load_distribution_and_lifting_calculator(request):
    return render(request, 'qehsfcalculators/safety/load_distribution_and_lifting.html', {'title': 'Load Distribution & Lifting Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_lifting_force_per_anchor_at_building_site_calculator(request):
    return render(request, 'qehsfcalculators/safety/lifting_force_per_anchor_at_building_site.html', {'title': 'Lifting Force per Anchor at Building Site Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_lifting_force_per_anchor_at_precast_factory_calculator(request):
    return render(request, 'qehsfcalculators/safety/lifting_force_per_anchor_at_precast_factory.html', {'title': 'Lifting Force per Anchor at Precast Factory Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_load_per_anchor_during_de_moulding_calculator(request):
    return render(request, 'qehsfcalculators/safety/load_per_anchor_during_de_moulding.html', {'title': 'Load per Anchor During De-Moulding Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_load_per_anchor_during_transport_calculator(request):
    return render(request, 'qehsfcalculators/safety/load_per_anchor_during_transport.html', {'title': 'Load per Anchor During Transport Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_lifting_force_per_anchor_pitching_calculator(request):
    return render(request, 'qehsfcalculators/safety/lifting_force_per_anchor_pitching.html', {'title': 'Lifting Force per Anchor (Pitching) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_liquid_sizing_calculator(request):
    return render(request, 'qehsfcalculators/safety/liquid_sizing.html', {'title': 'Liquid Sizing Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_mud_weight_density_calculator(request):
    return render(request, 'qehsfcalculators/safety/mud_weight_density.html', {'title': 'Mud weight (density) calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_mud_pump_output_calculator(request):
    return render(request, 'qehsfcalculators/safety/mud_pump_output.html', {'title': 'Mud Pump Output Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_marsh_funnel_viscosity_calculator(request):
    return render(request, 'qehsfcalculators/safety/marsh_funnel_viscosity.html', {'title': 'Marsh Funnel Viscosity Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_mass_and_heat_balance_for_steam_injection_into_a_tank_calculator(request):
    return render(request, 'qehsfcalculators/safety/mass_and_heat_balance_for_steam_injection_into_a_tank.html', {'title': 'Mass and heat balance for steam injection into a tank calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_motor_vehicle_crash_rate_mvcr_calculator(request):
    return render(request, 'qehsfcalculators/safety/motor_vehicle_crash_rate_mvcr.html', {'title': 'Motor Vehicle Crash Rate (MVCR) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_motor_vehicle_crash_frequency_rate_calculator(request):
    return render(request, 'qehsfcalculators/safety/motor_vehicle_crash_frequency_rate.html', {'title': 'Motor Vehicle Crash Frequency Rate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_mean_temperature_difference_bw_primary_and_secondary_fluid_calculator(request):
    return render(request, 'qehsfcalculators/safety/mean_temperature_difference_bw_primary_and_secondary_fluid.html', {'title': 'Mean Temperature Difference B/W Primary and secondary Fluid Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_maximum_inspection_interval_calculator(request):
    return render(request, 'qehsfcalculators/safety/maximum_inspection_interval.html', {'title': 'Maximum Inspection Interval Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_nema_and_ip_rating_calculator(request):
    return render(request, 'qehsfcalculators/safety/nema_and_ip_rating.html', {'title': 'NEMA and IP Rating Calculator '})

@login_required
@subscription_required(plan_type="corporate")
def safety_no_overpressure_vent_area_calculator(request):
    return render(request, 'qehsfcalculators/safety/no_overpressure_vent_area.html', {'title': 'No-Overpressure Vent Area Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_no_overpressure_vent_area_formula_external_heating_calculator(request):
    return render(request, 'qehsfcalculators/safety/no_overpressure_vent_area_formula_external_heating.html', {'title': 'No-Overpressure Vent Area Formula (External Heating) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_no_overpressure_vent_area_formula_all_liquid_venting_calculator(request):
    return render(request, 'qehsfcalculators/safety/no_overpressure_vent_area_formula_all_liquid_venting.html', {'title': 'No-Overpressure Vent Area Formula (All-Liquid Venting) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_normalized_mass_flux_formula_low_quality_region_calculator(request):
    return render(request, 'qehsfcalculators/safety/normalized_mass_flux_formula_low_quality_region.html', {'title': 'Normalized Mass Flux Formula (Low-Quality Region) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_niosh_lifting_index_li_calculator(request):
    return render(request, 'qehsfcalculators/safety/niosh_lifting_index_li.html', {'title': 'NIOSH Lifting Index (LI) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_non_viscous_liquid_vent_area_calculator(request):
    return render(request, 'qehsfcalculators/safety/non_viscous_liquid_vent_area.html', {'title': 'Non-Viscous Liquid Vent Area Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_osha_total_recordable_incident_rate_calculator(request):
    return render(request, 'qehsfcalculators/safety/osha_total_recordable_incident_rate.html', {'title': 'OSHA Total Recordable Incident Rate Calculator '})

@login_required
@subscription_required(plan_type="corporate")
def safety_osha_dart_rate_calculator(request):
    return render(request, 'qehsfcalculators/safety/osha_dart_rate.html', {'title': 'OSHA DART Rate Calculator  '})

@login_required
@subscription_required(plan_type="corporate")
def safety_ohms_law_calculator(request):
    return render(request, 'qehsfcalculators/safety/ohms_law.html')

@login_required
@subscription_required(plan_type="corporate")
def safety_orifice_plate_beta_ratio_calculator(request):
    return render(request, 'qehsfcalculators/safety/orifice_plate_beta_ratio.html', {'title': 'Orifice Plate Beta Ratio Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_ppe_compilance_rate_calculator(request):
    return render(request, 'qehsfcalculators/safety/ppe_compilance_rate.html', {'title': 'PPE compilance rate calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_pressure_gradient_calculator(request):
    return render(request, 'qehsfcalculators/safety/pressure_gradient.html', {'title': 'Pressure Gradient Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_potential_energy_calculator(request):
    return render(request, 'qehsfcalculators/safety/potential_energy.html', {'title': 'Potential Energy Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_proportion_of_vapor_in_two_phase_discharge_calculator(request):
    return render(request, 'qehsfcalculators/safety/proportion_of_vapor_in_two_phase_discharge.html', {'title': 'Proportion of Vapor in Two-Phase Discharge Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_pore_pressure_calculator(request):
    return render(request, 'qehsfcalculators/safety/pore_pressure.html', {'title': 'Pore Pressure Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_pressure_drop_calculator(request):
    return render(request, 'qehsfcalculators/safety/pressure_drop.html', {'title': 'Pressure Drop Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_pressure_drop_across_a_steam_valve_calculator(request):
    return render(request, 'qehsfcalculators/safety/pressure_drop_across_a_steam_valve.html', {'title': 'Pressure Drop Across A Steam Valve  Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_pit_area_calculation_calculator(request):
    return render(request, 'qehsfcalculators/safety/pit_area_calculation.html', {'title': 'Pit Area Calculation'})

@login_required
@subscription_required(plan_type="corporate")
def safety_pump_efficiency_calculator(request):
    return render(request, 'qehsfcalculators/safety/pump_efficiency.html', {'title': 'Pump Efficiency Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_precast_lifting_safety_calculator(request):
    return render(request, 'qehsfcalculators/safety/precast_lifting_safety.html', {'title': 'Precast Lifting Safety Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_ppe_consumption_rate_calculator(request):
    return render(request, 'qehsfcalculators/safety/ppe_consumption_rate.html', {'title': 'PPE Consumption Rate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_ppe_stock_level_calculator(request):
    return render(request, 'qehsfcalculators/safety/ppe_stock_level.html', {'title': 'PPE Stock Level Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_pipe_fittings_pressure_loss_calculator(request):
    return render(request, 'qehsfcalculators/safety/pipe_fittings_pressure_loss.html', {'title': 'Pipe Fittings Pressure Loss Calculator '})

@login_required
@subscription_required(plan_type="corporate")
def safety_percentage_risk_index_calculator(request):
    return render(request, 'qehsfcalculators/safety/percentage_risk_index.html', {'title': 'Percentage Risk Index Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_reorder_point_rop_calculator(request):
    return render(request, 'qehsfcalculators/safety/reorder_point_rop.html', {'title': 'Reorder Point (ROP) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_risk_level_assesment_calculator(request):
    return render(request, 'qehsfcalculators/safety/risk_level_assesment.html', {'title': 'Risk level assesment'})

@login_required
@subscription_required(plan_type="corporate")
def safety_risk_priority_number_rpn_calculator(request):
    return render(request, 'qehsfcalculators/safety/risk_priority_number_rpn.html', {'title': 'Risk priority Number (RPN)  calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_rate_of_penetration_rop_calculator(request):
    return render(request, 'qehsfcalculators/safety/rate_of_penetration_rop.html', {'title': 'Rate of Penetration (ROP) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_rheology_viscosity_calculator(request):
    return render(request, 'qehsfcalculators/safety/rheology_viscosity.html', {'title': 'Rheology (Viscosity) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_required_opening_force_for_a_balanced_safety_valve_calculator(request):
    return render(request, 'qehsfcalculators/safety/required_opening_force_for_a_balanced_safety_valve.html', {'title': 'Required Opening Force For A Balanced Safety Valve  Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_reaction_force_at_the_end_of_safety_valve_calculator(request):
    return render(request, 'qehsfcalculators/safety/reaction_force_at_the_end_of_safety_valve.html', {'title': 'Reaction Force at the end of Safety Valve Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_remaining_corrosion_life1_calculator(request):
    return render(request, 'qehsfcalculators/safety/remaining_corrosion_life1.html', {'title': 'Remaining Corrosion Life Calculator (1)'})

@login_required
@subscription_required(plan_type="corporate")
def safety_remaining_corrosion_allowance_calculator(request):
    return render(request, 'qehsfcalculators/safety/remaining_corrosion_allowance.html', {'title': 'Remaining Corrosion Allowance Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_relief_vent_rate_all_vapor_and_all_liquid_venting_calculator(request):
    return render(request, 'qehsfcalculators/safety/relief_vent_rate_all_vapor_and_all_liquid_venting.html', {'title': 'Relief Vent Rate  All-Vapor and All-Liquid Venting Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_relief_vent_rate_formula_all_liquid_venting_calculator(request):
    return render(request, 'qehsfcalculators/safety/relief_vent_rate_formula_all_liquid_venting.html', {'title': 'Relief Vent Rate Formula (All-Liquid Venting) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_road_safety_braking_distance_calculator(request):
    return render(request, 'qehsfcalculators/safety/road_safety_braking_distance.html', {'title': 'Road Safety - Braking Distance Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_road_safety_time_headway_th_calculator(request):
    return render(request, 'qehsfcalculators/safety/road_safety_time_headway_th.html', {'title': 'Road Safety - Time Headway (TH) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_road_safety_and_speed_flow_relationship_calculator(request):
    return render(request, 'qehsfcalculators/safety/road_safety_and_speed_flow_relationship.html', {'title': 'Road Safety & Speed-Flow Relationship Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_road_safety_stopping_sight_distance_ssd_calculator(request):
    return render(request, 'qehsfcalculators/safety/road_safety_stopping_sight_distance_ssd.html', {'title': 'Road Safety - Stopping Sight Distance (SSD) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_recommended_weight_limit_rwl_calculator(request):
    return render(request, 'qehsfcalculators/safety/recommended_weight_limit_rwl.html', {'title': 'Recommended Weight Limit (RWL) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_risk_matrix_calculator(request):
    return render(request, 'qehsfcalculators/safety/risk_matrix.html', {'title': 'Risk Matrix Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_reel_and_paddle_power_calculator(request):
    return render(request, 'qehsfcalculators/safety/reel_and_paddle_power.html', {'title': 'Reel and Paddle Power Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_risk_index_calculator(request):
    return render(request, 'qehsfcalculators/safety/risk_index.html', {'title': 'Risk Index Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_safe_overtaking_sight_distance_osd_calculator(request):
    return render(request, 'qehsfcalculators/safety/safe_overtaking_sight_distance_osd.html', {'title': 'Safe Overtaking Sight Distance (OSD) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_severity_rate_calculator(request):
    return render(request, 'qehsfcalculators/safety/severity_rate.html', {'title': 'Severity Rate Calculator '})

@login_required
@subscription_required(plan_type="corporate")
def safety_swl_of_wire_rope_calculator(request):
    return render(request, 'qehsfcalculators/safety/swl_of_wire_rope.html', {'title': 'SWL of Wire Rope Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_stack_height_calculator(request):
    return render(request, 'qehsfcalculators/safety/stack_height.html', {'title': 'Stack Height Calculator '})

@login_required
@subscription_required(plan_type="corporate")
def safety_specifi_gravity_calculator(request):
    return render(request, 'qehsfcalculators/safety/specifi_gravity.html', {'title': 'Specifi gravity calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_safety_factor_calculator(request):
    return render(request, 'qehsfcalculators/safety/safety_factor.html', {'title': 'Safety Factor calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_steam_consumption_to_provide_tank_heat_losses_calculator(request):
    return render(request, 'qehsfcalculators/safety/steam_consumption_to_provide_tank_heat_losses.html', {'title': 'Steam consumption to provide tank heat losses'})

@login_required
@subscription_required(plan_type="corporate")
def safety_steam_consumption_by_injection_into_a_tank_calculator(request):
    return render(request, 'qehsfcalculators/safety/steam_consumption_by_injection_into_a_tank.html', {'title': 'Steam Consumption by Injection into a Tank caluculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_steam_start_up_load_to_bring_steam_pipework_calculator(request):
    return render(request, 'qehsfcalculators/safety/steam_start_up_load_to_bring_steam_pipework.html', {'title': 'Steam Start-Up Load to bring steam pipework Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_stress_in_a_boiler_shell_resulting_from_boiler_pressure_calculator(request):
    return render(request, 'qehsfcalculators/safety/stress_in_a_boiler_shell_resulting_from_boiler_pressure.html', {'title': ' Stress in a boiler shell resulting from boiler pressure'})

@login_required
@subscription_required(plan_type="corporate")
def safety_sizing_a_control_valve_for_liquid_calculator(request):
    return render(request, 'qehsfcalculators/safety/sizing_a_control_valve_for_liquid.html', {'title': 'Sizing a control valve for liquid '})

@login_required
@subscription_required(plan_type="corporate")
def safety_sizing_a_control_valve_for_saturated_steam_calculator(request):
    return render(request, 'qehsfcalculators/safety/sizing_a_control_valve_for_saturated_steam.html', {'title': 'Sizing a control valve for saturated steam '})

@login_required
@subscription_required(plan_type="corporate")
def safety_steam_flow_through_valve_under_critical_condition_calculator(request):
    return render(request, 'qehsfcalculators/safety/steam_flow_through_valve_under_critical_condition.html', {'title': 'steam flow through valve under critical condition calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_steam_valve_flow_coefficient_cv_for_sub_sonic_flow_calculator(request):
    return render(request, 'qehsfcalculators/safety/steam_valve_flow_coefficient_cv_for_sub_sonic_flow.html', {'title': 'steam valve flow coefficient (cv) for sub-sonic flow calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_stem_force_required_to_close_a_control_valve_calculator(request):
    return render(request, 'qehsfcalculators/safety/stem_force_required_to_close_a_control_valve.html', {'title': 'Stem Force Required To Close a Control Valve Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_safety_valve_opening_force_with_the_spring_housing_calculator(request):
    return render(request, 'qehsfcalculators/safety/safety_valve_opening_force_with_the_spring_housing.html', {'title': 'Safety Valve Opening Force with the spring housing Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_safety_valve_opening_force_with_the_spring_housing_vented_atmosphere_calculator(request):
    return render(request, 'qehsfcalculators/safety/safety_valve_opening_force_with_the_spring_housing_vented_atmosphere.html', {'title': 'Safety Valve Opening Force with the spring housing vented atmosphere Calculator '})

@login_required
@subscription_required(plan_type="corporate")
def safety_safety_valve_opening_force_with_the_spring_housing_build_up_pressure_calculator(request):
    return render(request, 'qehsfcalculators/safety/safety_valve_opening_force_with_the_spring_housing_build_up_pressure.html', {'title': 'Safety Valve Opening Force with the spring housing build-up pressure Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_safety_valve_vent_pipe_diameter_calculator(request):
    return render(request, 'qehsfcalculators/safety/safety_valve_vent_pipe_diameter.html', {'title': 'Safety Valve Vent Pipe Diameter Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_si_based_darcy_equation_for_determining_pressure_drop_due_to_frictional_resistance_calculator(request):
    return render(request, 'qehsfcalculators/safety/si_based_darcy_equation_for_determining_pressure_drop_due_to_frictional_resistance.html')

@login_required
@subscription_required(plan_type="corporate")
def safety_steam_pipeline_pressure_drop_calculator(request):
    return render(request, 'qehsfcalculators/safety/steam_pipeline_pressure_drop.html', {'title': 'Steam Pipeline Pressure Drop Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_stall_load_for_a_constant_flow_secondary_calculator(request):
    return render(request, 'qehsfcalculators/safety/stall_load_for_a_constant_flow_secondary.html', {'title': 'Stall Load For A Constant Flow Secondary Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_spherical_portion_calculator(request):
    return render(request, 'qehsfcalculators/safety/spherical_portion.html', {'title': 'Spherical Portion Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_spread_angle_factor_calculator(request):
    return render(request, 'qehsfcalculators/safety/spread_angle_factor.html', {'title': 'Spread Angle Factor Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_safety_load_anchor_calculation_tool_calculator(request):
    return render(request, 'qehsfcalculators/safety/safety_load_anchor_calculation_tool.html', {'title': 'Safety Load Anchor Calculation Tool'})

@login_required
@subscription_required(plan_type="corporate")
def safety_safety_performance_function_spf_calculator(request):
    return render(request, 'qehsfcalculators/safety/safety_performance_function_spf.html', {'title': 'Safety Performance Function (SPF) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_safety_training_completion_rate_calculator(request):
    return render(request, 'qehsfcalculators/safety/safety_training_completion_rate.html', {'title': 'Safety Training Completion Rate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_safety_audit_compliance_score_calculator(request):
    return render(request, 'qehsfcalculators/safety/safety_audit_compliance_score.html', {'title': 'Safety Audit Compliance Score Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_settling_force_of_gravity_calculator(request):
    return render(request, 'qehsfcalculators/safety/settling_force_of_gravity.html', {'title': 'Settling Force of Gravity Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_subcritical_flow_vent_area_api_rp_520_calculator(request):
    return render(request, 'qehsfcalculators/safety/subcritical_flow_vent_area_api_rp_520.html', {'title': 'Subcritical Flow Vent Area Calculator (API RP 520)'})

@login_required
@subscription_required(plan_type="corporate")
def safety_steam_sizing_calculator(request):
    return render(request, 'qehsfcalculators/safety/steam_sizing.html', {'title': 'Steam Sizing Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_safety_stock_calculator(request):
    return render(request, 'qehsfcalculators/safety/safety_stock.html', {'title': 'Safety Stock Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_safety_index_si_calculator(request):
    return render(request, 'qehsfcalculators/safety/safety_index_si.html', {'title': 'Safety Index (SI) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_safety_risk_assessment_calculator(request):
    return render(request, 'qehsfcalculators/safety/safety_risk_assessment.html', {'title': 'Safety Risk Assessment Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_training_hour_calculation_calculator(request):
    return render(request, 'qehsfcalculators/safety/training_hour_calculation.html', {'title': 'Training hour calculation'})

@login_required
@subscription_required(plan_type="corporate")
def safety_total_dead_load_dl_calculator(request):
    return render(request, 'qehsfcalculators/safety/total_dead_load_dl.html', {'title': 'Total Dead load calculator (DL)'})

@login_required
@subscription_required(plan_type="corporate")
def safety_total_intend_load_calculator(request):
    return render(request, 'qehsfcalculators/safety/total_intend_load.html', {'title': 'Total intend Load calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_total_enthalpy_of_steam_calculator(request):
    return render(request, 'qehsfcalculators/safety/total_enthalpy_of_steam.html', {'title': 'Total Enthalpy of Steam Calculator".'})

@login_required
@subscription_required(plan_type="corporate")
def safety_total_fall_distance_calculator(request):
    return render(request, 'qehsfcalculators/safety/total_fall_distance.html', {'title': 'Total Fall Distance Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_tension_per_leg_calculator(request):
    return render(request, 'qehsfcalculators/safety/tension_per_leg.html', {'title': 'Tension per leg calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_total_recordable_incident_frequency_rate_trifr_calculator(request):
    return render(request, 'qehsfcalculators/safety/total_recordable_incident_frequency_rate_trifr.html', {'title': 'Total Recordable Incident Frequency Rate (TRIFR) calcualtor'})

@login_required
@subscription_required(plan_type="corporate")
def safety_total_loss_hours_calculator(request):
    return render(request, 'qehsfcalculators/safety/total_loss_hours.html', {'title': 'Total Loss Hours Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_total_pump_delivery_head_calculator(request):
    return render(request, 'qehsfcalculators/safety/total_pump_delivery_head.html', {'title': 'Total Pump Delivery Head Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_to_determine_the_required_steam_flowrate_from_a_kw_rating_calculator(request):
    return render(request, 'qehsfcalculators/safety/to_determine_the_required_steam_flowrate_from_a_kw_rating.html', {'title': 'To determine the required steam flowrate from a kW rating'})

@login_required
@subscription_required(plan_type="corporate")
def safety_total_recordable_case_frequency_trcf_calculator(request):
    return render(request, 'qehsfcalculators/safety/total_recordable_case_frequency_trcf.html', {'title': 'Total Recordable Case Frequency (TRCF) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_thermal_penetration_time_for_conductive_heat_transfer_calculator(request):
    return render(request, 'qehsfcalculators/safety/thermal_penetration_time_for_conductive_heat_transfer.html', {'title': 'Thermal Penetration Time for Conductive Heat Transfer'})

@login_required
@subscription_required(plan_type="corporate")
def safety_thermal_expansion_of_pipe_calculator(request):
    return render(request, 'qehsfcalculators/safety/thermal_expansion_of_pipe.html', {'title': 'Thermal Expansion Of Pipe Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_tori_spherical_head_radius_calculator(request):
    return render(request, 'qehsfcalculators/safety/tori_spherical_head_radius.html', {'title': 'Tori-Spherical Head Radius Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_total_brake_horsepower_bhp_required_calculator(request):
    return render(request, 'qehsfcalculators/safety/total_brake_horsepower_bhp_required.html', {'title': 'Total Brake Horsepower (BHP) Required Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_turnaround_time_formula_external_heating_calculator(request):
    return render(request, 'qehsfcalculators/safety/turnaround_time_formula_external_heating.html', {'title': 'Turnaround Time Formula (External Heating) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_tension_factor_calculator(request):
    return render(request, 'qehsfcalculators/safety/tension_factor.html', {'title': 'Tension Factor Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_total_integrated_dose_at_ground_level_puff_model_calculator(request):
    return render(request, 'qehsfcalculators/safety/total_integrated_dose_at_ground_level_puff_model.html', {'title': 'Total Integrated Dose at Ground Level Calculator (Puff Model)'})

@login_required
@subscription_required(plan_type="corporate")
def safety_velocity_of_steam_passing_through_an_orifice1_calculator(request):
    return render(request, 'qehsfcalculators/safety/velocity_of_steam_passing_through_an_orifice1.html', {'title': 'Velocity of Steam Passing Through an Orifice Calculator(1)'})

@login_required
@subscription_required(plan_type="corporate")
def safety_velocity_of_steam_passing_through_an_orifice2_calculator(request):
    return render(request, 'qehsfcalculators/safety/velocity_of_steam_passing_through_an_orifice2.html', {'title': 'Velocity of Steam Passing Through an Orifice Calculator(2)'})

@login_required
@subscription_required(plan_type="corporate")
def safety_velocity_energy_conversion_calculator(request):
    return render(request, 'qehsfcalculators/safety/velocity_energy_conversion.html', {'title': 'velocity calculator (energy conversion)'})

@login_required
@subscription_required(plan_type="corporate")
def safety_velocity_of_liquid_through_orifice_calculator(request):
    return render(request, 'qehsfcalculators/safety/velocity_of_liquid_through_orifice.html', {'title': 'Velocity of liquid through orifice calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_volumetric_flowrate_of_a_liquid_through_orifice_calculator(request):
    return render(request, 'qehsfcalculators/safety/volumetric_flowrate_of_a_liquid_through_orifice.html', {'title': 'Volumetric Flowrate of a liquid through orifice Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_valve_closing_force_calculator(request):
    return render(request, 'qehsfcalculators/safety/valve_closing_force.html', {'title': 'Valve Closing Force Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_volumetric_flow_of_water_through_a_valve_calculator(request):
    return render(request, 'qehsfcalculators/safety/volumetric_flow_of_water_through_a_valve.html', {'title': 'Volumetric Flow Of Water Through A Valve Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_valve_authority_calculator(request):
    return render(request, 'qehsfcalculators/safety/valve_authority.html', {'title': 'Valve authority calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_venting_time_calculator(request):
    return render(request, 'qehsfcalculators/safety/venting_time.html', {'title': 'Venting Time Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_vent_area_reduction_formula_calculator(request):
    return render(request, 'qehsfcalculators/safety/vent_area_reduction_formula.html', {'title': 'Vent Area Reduction Formula Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_vent_area_asme_section_viii_calculator(request):
    return render(request, 'qehsfcalculators/safety/vent_area_asme_section_viii.html', {'title': 'Vent Area Calculator (ASME Section VIII)'})

@login_required
@subscription_required(plan_type="corporate")
def safety_vent_sizing_api_rp520_calculator(request):
    return render(request, 'qehsfcalculators/safety/vent_sizing_api_rp520.html', {'title': 'Vent Sizing Calculator (API RP520)'})

@login_required
@subscription_required(plan_type="corporate")
def safety_liquid_sizing_calculator(request):
    return render(request, 'qehsfcalculators/safety/liquid_sizing.html', {'title': 'Liquid Sizing Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_wire_rope_grips_calculator(request):
    return render(request, 'qehsfcalculators/safety/wire_rope_grips.html', {'title': 'Wire Rope Grips Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_well_control_kill_mud_weight_calculator(request):
    return render(request, 'qehsfcalculators/safety/well_control_kill_mud_weight.html', {'title': 'Well Control (Kill Mud Weight) Calculator '})

@login_required
@subscription_required(plan_type="corporate")
def safety_work_done_by_a_pump_in_horsepower_hp_calculator(request):
    return render(request, 'qehsfcalculators/safety/work_done_by_a_pump_in_horsepower_hp.html', {'title': 'Work Done By A Pump In Horsepower (H.P.) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def safety_21_ellipsoidal_head_radius_calculator(request):
    return render(request, 'qehsfcalculators/safety/21_ellipsoidal_head_radius.html', {'title': '2:1 Ellipsoidal Head Radius Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_main_calculator(request):
    return render(request, 'qehsfcalculators/fire/main.html', {'title': 'Main calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_burn_rate_chemical_exposure_calculator(request):
    return render(request, 'qehsfcalculators/fire/burn_rate_chemical_exposure.html', {'title': 'Burn Rate (chemical Exposure) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_base_design_quantity_for_co_calculator(request):
    return render(request, 'qehsfcalculators/fire/base_design_quantity_for_co₂.html', {'title': 'Base Design Quantity for CO₂ Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_bernoullis_equation_for_a_liquid_calculator(request):
    return render(request, 'qehsfcalculators/fire/bernoullis_equation_for_a_liquid.html')

@login_required
@subscription_required(plan_type="corporate")
def fire_bernoullis_equation_with_constant_potential_energy_terms_and_frictional_losses_calculator(request):
    return render(request, 'qehsfcalculators/fire/bernoullis_equation_with_constant_potential_energy_terms_and_frictional_losses.html')

@login_required
@subscription_required(plan_type="corporate")
def fire_combustion_efficiency_ce_calculator(request):
    return render(request, 'qehsfcalculators/fire/combustion_efficiency_ce.html', {'title': 'Combustion Efficiency (CE) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_discharge_rate_for_co2_calculator(request):
    return render(request, 'qehsfcalculators/fire/discharge_rate_for_co2.html', {'title': 'Discharge Rate Calculator for co2'})

@login_required
@subscription_required(plan_type="corporate")
def fire_discharge_rate_of_co2_for_local_applications_calculator(request):
    return render(request, 'qehsfcalculators/fire/discharge_rate_of_co2_for_local_applications.html', {'title': 'Discharge Rate of co2 Calculator for local applications'})

@login_required
@subscription_required(plan_type="corporate")
def fire_equivalent_orifice_area_for_co2_calculator(request):
    return render(request, 'qehsfcalculators/fire/equivalent_orifice_area_for_co2.html', {'title': 'Equivalent Orifice Area Calculator for co2'})

@login_required
@subscription_required(plan_type="corporate")
def fire_equivalent_water_flowrate_through_a_check_valve_calculator(request):
    return render(request, 'qehsfcalculators/fire/equivalent_water_flowrate_through_a_check_valve.html', {'title': 'Equivalent Water Flowrate Through A Check Valve Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_fire_load_calculator(request):
    return render(request, 'qehsfcalculators/fire/fire_load.html', {'title': 'Fire Load Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_fire_extinguisher_placement_calculator(request):
    return render(request, 'qehsfcalculators/fire/fire_extinguisher_placement.html', {'title': 'Fire Extinguisher Placement Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_fire_extinguisher_weight_inspection_calculator(request):
    return render(request, 'qehsfcalculators/fire/fire_extinguisher_weight_inspection.html', {'title': 'Fire extinguisher weight inspection'})

@login_required
@subscription_required(plan_type="corporate")
def fire_fire_load_density_calculator(request):
    return render(request, 'qehsfcalculators/fire/fire_load_density.html', {'title': 'fire load density calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_fire_flow_calculator(request):
    return render(request, 'qehsfcalculators/fire/fire_flow.html', {'title': 'Fire Flow calcualtor'})

@login_required
@subscription_required(plan_type="corporate")
def fire_fm_200_novec_1230_net_hazard_volume_calculator(request):
    return render(request, 'qehsfcalculators/fire/fm_200_novec_1230_net_hazard_volume.html', {'title': 'FM-200 / NOVEC 1230 - Net Hazard Volume Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_fm_200_novec_1230_agent_quantity_calculator(request):
    return render(request, 'qehsfcalculators/fire/fm_200_novec_1230_agent_quantity.html', {'title': 'FM-200 / NOVEC 1230 - agent quantity calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_fm_200_novec_1230_nozzle_quantity_calculator(request):
    return render(request, 'qehsfcalculators/fire/fm_200_novec_1230_nozzle_quantity.html', {'title': 'FM-200 / NOVEC 1230 - Nozzle Quantity Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_fm_200_novec_1230_pipe_sizing_calculator(request):
    return render(request, 'qehsfcalculators/fire/fm_200_novec_1230_pipe_sizing.html', {'title': 'FM-200 / NOVEC 1230 - Pipe Sizing Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_final_design_quantity_for_co2_calculator(request):
    return render(request, 'qehsfcalculators/fire/final_design_quantity_for_co2.html', {'title': 'Final design Quantity for co2 calcualtor'})

@login_required
@subscription_required(plan_type="corporate")
def fire_flow_rate_for_local_application_system_calculator(request):
    return render(request, 'qehsfcalculators/fire/flow_rate_for_local_application_system.html', {'title': 'Flow rate calculator for Local application System'})

@login_required
@subscription_required(plan_type="corporate")
def fire_fire_alarm_system_secondary_battery_set_calculation_calculator(request):
    return render(request, 'qehsfcalculators/fire/fire_alarm_system_secondary_battery_set_calculation.html', {'title': 'Fire Alarm System Secondary Battery -Set Calculation'})

@login_required
@subscription_required(plan_type="corporate")
def fire_fire_safety_occupancy_for_assembly_and_recreation_limit_calculator(request):
    return render(request, 'qehsfcalculators/fire/fire_safety_occupancy_for_assembly_and_recreation_limit.html', {'title': 'Fire Safety Occupancy Calculator For Assembly and Recreation Limit'})

@login_required
@subscription_required(plan_type="corporate")
def fire_flammable_range_calculator(request):
    return render(request, 'qehsfcalculators/fire/flammable_range.html', {'title': 'Flammable Range Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_flammability_for_gas_mixtures_calculator(request):
    return render(request, 'qehsfcalculators/fire/flammability_for_gas_mixtures.html', {'title': 'Flammability Calculator for Gas Mixtures'})

@login_required
@subscription_required(plan_type="corporate")
def fire_fauskes_vent_area_calculator(request):
    return render(request, 'qehsfcalculators/fire/fauskes_vent_area.html')

@login_required
@subscription_required(plan_type="corporate")
def fire_fire_fighting_demand_calculator(request):
    return render(request, 'qehsfcalculators/fire/fire_fighting_demand.html', {'title': 'Fire Fighting Demand Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_fire_hazard_risk_calculation_fire_load_density_calculator(request):
    return render(request, 'qehsfcalculators/fire/fire_hazard_risk_calculation_fire_load_density.html', {'title': 'Fire Hazard Risk Calculation (Fire Load Density)'})

@login_required
@subscription_required(plan_type="corporate")
def fire_heat_transfer_conduction_fouriers_law_calculator(request):
    return render(request, 'qehsfcalculators/fire/heat_transfer_conduction_fouriers_law.html')

@login_required
@subscription_required(plan_type="corporate")
def fire_heat_transfer_convection_newtons_law_calculator(request):
    return render(request, 'qehsfcalculators/fire/heat_transfer_convection_newtons_law.html', {'title': 'Heat Transfer Calculator convection(newtons Law)'})

@login_required
@subscription_required(plan_type="corporate")
def fire_heat_detector_responsive_time_calculator(request):
    return render(request, 'qehsfcalculators/fire/heat_detector_responsive_time.html', {'title': 'Heat detector responsive time calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_huffs_relief_vent_rate_calculator(request):
    return render(request, 'qehsfcalculators/fire/huffs_relief_vent_rate.html')

@login_required
@subscription_required(plan_type="corporate")
def fire_homogeneous_vessel_venting_temperature_calculator(request):
    return render(request, 'qehsfcalculators/fire/homogeneous_vessel_venting_temperature.html', {'title': 'Homogeneous-Vessel Venting Temperature Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_lower_flammability_limit_lfl_for_mixtures_of_flammable_gases_le_chateliers_rule_calculator(request):
    return render(request, 'qehsfcalculators/fire/lower_flammability_limit_lfl_for_mixtures_of_flammable_gases_le_chateliers_rule.html', {'title': 'Lower Flammability Limit (LFL) for Mixtures of Flammable Gases (Le Chatelier’s Rule) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_modified_co_quantity_calculator(request):
    return render(request, 'qehsfcalculators/fire/modified_co₂_quantity.html', {'title': 'Modified CO₂ Quantity Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_nitrogen_equivalency_kik_calculator(request):
    return render(request, 'qehsfcalculators/fire/nitrogen_equivalency_kik.html', {'title': 'Nitrogen Equivalency (Kik) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_normalized_mass_flux_formula_high_quality_region_calculator(request):
    return render(request, 'qehsfcalculators/fire/normalized_mass_flux_formula_high_quality_region.html', {'title': 'Normalized Mass Flux Formula (High-Quality Region) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_pressure_factor_calculator(request):
    return render(request, 'qehsfcalculators/fire/pressure_factor.html', {'title': 'Pressure Factor Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_reached_concentration_calculator(request):
    return render(request, 'qehsfcalculators/fire/reached_concentration.html', {'title': 'Reached Concentration Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_relief_vent_rate_homogeneous_vessel_venting_calculator(request):
    return render(request, 'qehsfcalculators/fire/relief_vent_rate_homogeneous_vessel_venting.html', {'title': 'Relief Vent Rate (Homogeneous-Vessel Venting) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_relief_vent_rate_formula_external_heating_calculator(request):
    return render(request, 'qehsfcalculators/fire/relief_vent_rate_formula_external_heating.html', {'title': 'Relief Vent Rate Formula (External Heating) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_smoke_detector_quantity_calculator(request):
    return render(request, 'qehsfcalculators/fire/smoke_detector_quantity.html', {'title': 'Smoke detector quantity calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_smoke_detector_spacing_calculator(request):
    return render(request, 'qehsfcalculators/fire/smoke_detector_spacing.html', {'title': 'Smoke detector spacing calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_specific_volume_calculator(request):
    return render(request, 'qehsfcalculators/fire/specific_volume.html', {'title': 'Specific volume calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_sprinkler_flow_rate_calculator(request):
    return render(request, 'qehsfcalculators/fire/sprinkler_flow_rate.html', {'title': 'Sprinkler Flow Rate Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_scba_self_contained_breathing_apparatus_cylinder_breathing_duration_calculation_calculator(request):
    return render(request, 'qehsfcalculators/fire/scba_self_contained_breathing_apparatus_cylinder_breathing_duration_calculation.html', {'title': 'SCBA (Self-Contained Breathing Apparatus) Cylinder Breathing Duration Calculation'})

@login_required
@subscription_required(plan_type="corporate")
def fire_turnaround_time_calculator(request):
    return render(request, 'qehsfcalculators/fire/turnaround_time.html', {'title': 'Turnaround Time Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_temperature_history_equation_all_vapor_and_all_liquid_venting_calculator(request):
    return render(request, 'qehsfcalculators/fire/temperature_history_equation_all_vapor_and_all_liquid_venting.html', {'title': 'Temperature History Equation (All-Vapor and All-Liquid Venting) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_temperature_history_equation_external_heating_calculator(request):
    return render(request, 'qehsfcalculators/fire/temperature_history_equation_external_heating.html', {'title': 'Temperature History Equation (External Heating) Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_volumetric_flowrate_of_liquid_is_proportional_to_the_square_root_of_pressure_drop_calculator(request):
    return render(request, 'qehsfcalculators/fire/volumetric_flowrate_of_liquid_is_proportional_to_the_square_root_of_pressure_drop.html', {'title': 'Volumetric flowrate of liquid is proportional to the square root of pressure drop'})

@login_required
@subscription_required(plan_type="corporate")
def fire_venting_energy_balance_calculator(request):
    return render(request, 'qehsfcalculators/fire/venting_energy_balance.html', {'title': 'Venting Energy Balance Calculator'})

@login_required
@subscription_required(plan_type="corporate")
def fire_water_control_valve_capacity_calculator(request):
    return render(request, 'qehsfcalculators/fire/water_control_valve_capacity.html', {'title': 'Water Control Valve Capacity Calculator'})