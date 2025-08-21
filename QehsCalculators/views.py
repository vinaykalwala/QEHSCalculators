from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
# from .models import Category, Calculator, Subscription, UsageHistory, Plan
import razorpay
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

def home(request):
    
    return render(request, 'home.html')

def about(request):
    return render(request, 'about.html')

from django.shortcuts import render

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
        # Handle form submission (e.g., send email)
        pass
    return render(request, 'contact.html')

# @login_required
# def category_detail(request, category_id):
#     category = get_object_or_404(Category, id=category_id)
#     calculators = Calculator.objects.filter(category=category)
#     sub = Subscription.objects.get(user=request.user)
#     if sub.is_expired():
#         return redirect('pricing')
#     limit = sub.plan.access_limit_per_category
#     if limit > 0:
#         calculators = calculators[:limit]
#     return render(request, 'category_detail.html', {'category': category, 'calculators': calculators})

# @login_required
# def calculator_detail(request, slug):
#     calculator = get_object_or_404(Calculator, slug=slug)
#     sub = Subscription.objects.get(user=request.user)
#     if sub.is_expired():
#         return redirect('pricing')
#     limit = sub.plan.access_limit_per_category
#     category_calcs = Calculator.objects.filter(category=calculator.category)
#     if limit > 0 and calculator not in category_calcs[:limit]:
#         return redirect('upgrade_required')
#     UsageHistory.objects.create(user=request.user, calculator=calculator)
#     return render(request, calculator.template_name, {'calculator': calculator})

# def pricing(request):
#     plans = Plan.objects.all()
#     return render(request, 'pricing.html', {'plans': plans})

# @login_required
# def create_order(request, plan_id):
#     plan = get_object_or_404(Plan, id=plan_id)
#     if plan.name == 'Free':
#         return redirect('dashboard')
#     amount = int(plan.price * 100)  # In paise
#     order = client.order.create({
#         'amount': amount,
#         'currency': 'INR',
#         'payment_capture': '1'
#     })
#     return render(request, 'payment.html', {
#         'order_id': order['id'],
#         'amount': amount,
#         'razorpay_key': settings.RAZORPAY_KEY_ID,
#         'plan_id': plan_id
#     })

# @csrf_exempt
# def payment_success(request):
#     if request.method == 'POST':
#         payment_id = request.POST.get('razorpay_payment_id')
#         order_id = request.POST.get('razorpay_order_id')
#         signature = request.POST.get('razorpay_signature')
#         plan_id = request.POST.get('plan_id')
#         params_dict = {
#             'razorpay_order_id': order_id,
#             'razorpay_payment_id': payment_id,
#             'razorpay_signature': signature
#         }
#         try:
#             client.utility.verify_payment_signature(params_dict)
#             plan = Plan.objects.get(id=plan_id)
#             sub, _ = Subscription.objects.get_or_create(user=request.user)
#             sub.plan = plan
#             sub.start_date = timezone.now()
#             sub.active = True
#             sub.save()
#             return redirect('dashboard')
#         except:
#             return JsonResponse({'status': 'Payment verification failed'}, status=400)
#     return redirect('pricing')

@login_required
def dashboard(request):
    # sub = Subscription.objects.get(user=request.user)
    # sub.is_expired()
    # history = UsageHistory.objects.filter(user=request.user)[:10]
    return render(request, 'dashboard.html')

def terms(request):
    return render(request, 'terms.html')

def privacy(request):
    return render(request, 'privacy.html')

def upgrade_required(request):
    return render(request, 'upgrade_required.html')