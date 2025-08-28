from django.contrib import admin
from django.urls import include, path
from QehsCalculators.views import *
urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),
    path('', home, name='home'),
    path('about/', about, name='about'),
    path('contact/', contact, name='contact'),
    path('quality/', quality_calculators, name='quality_calculators'),
    path('environment/', environment_calculators, name='environment_calculators'),
    path('health/', health_calculators, name='health_calculators'),
    path('safety/', safety_calculators, name='safety_calculators'),
    path('fire/', fire_calculators, name='fire_calculators'),
    path('/disclaimer/', disclaimer, name='disclaimer'),
    # path('category/<int:category_id>/',category_detail, name='category_detail'),
    # path('calculator/<slug:slug>/', calculator_detail, name='calculator_detail'),
    # path('pricing/', pricing, name='pricing'),
    # path('create_order/<int:plan_id>/', create_order, name='create_order'),
    # path('payment_success/', payment_success, name='payment_success'),
    path('dashboard/', dashboard, name='dashboard'),
    path('terms/', terms, name='terms'),
    path('privacy/', privacy, name='privacy'),
    path('accident_rate_calculator/', accident_rate_calculator, name='accident_rate_calculator'),

]
