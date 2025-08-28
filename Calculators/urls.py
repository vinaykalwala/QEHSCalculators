from django.contrib import admin
from django.urls import include, path
from QehsCalculators.views import *
urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home, name='home'),
    path('about/', about, name='about'),
    path('contact/', contact, name='contact'),
    path('quality/', quality_calculators, name='quality_calculators'),
    path('environment/', environment_calculators, name='environment_calculators'),
    path('health/', health_calculators, name='health_calculators'),
    path('safety/', safety_calculators, name='safety_calculators'),
    path('fire/', fire_calculators, name='fire_calculators'),
    path('disclaimer/', disclaimer, name='disclaimer'),
    path('terms/', terms, name='terms'),
    path('privacy/', privacy, name='privacy'),
    path('dashboard/', dashboard, name='dashboard'),
    path('subscribe/<int:plan_id>/', subscribe_plan, name='subscribe_plan'),
     path('payment/success/', payment_success, name='payment_success'),
     path('payment/failed/', payment_failed, name='payment_failed'),
    path("signup/", signup_view, name="signup"),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path('fire/', fire_calculator, name='fire_calculator'),
    path('co2/', co2_calculator, name='co2_calculator'),
    path('profit/', profit_calculator, name='profit_calculator'),
]
