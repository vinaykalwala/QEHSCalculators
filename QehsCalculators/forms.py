from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import *

class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    phone = forms.CharField(required=False)
    company_name = forms.CharField(required=False)
    designation = forms.CharField(required=False)
    address = forms.CharField(widget=forms.Textarea, required=False)
    industry = forms.CharField(required=False)
    purpose = forms.CharField(required=False)

    class Meta:
        model = CustomUser
        fields = ("username", "email", "phone", "company_name", "designation", "address", "industry", "purpose", "password1", "password2")


class CustomAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(label="Email")


class ContactForm(forms.ModelForm):
    class Meta:
        model = Contact
        fields = ['name', 'email', 'phone', 'subject', 'message']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your Name'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Your Email'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your Phone Number'}),
            'subject': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Subject'}),
            'message': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Your Message'}),
        }


from django import forms
from .models import CustomUser

class UserEditForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ['email', 'phone', 'company_name', 'designation', 'address', 'industry', 'purpose']


from .models import SubscriptionPlan

class SubscriptionPlanForm(forms.ModelForm):
    class Meta:
        model = SubscriptionPlan
        fields = ['name', 'price', 'calculators_per_category', 'device_limit', 'duration_days', 'is_active']




from django.contrib.auth.forms import SetPasswordForm, AuthenticationForm
from django.contrib.auth import get_user_model

User = get_user_model()

class ForgotPasswordForm(forms.Form):
    email = forms.EmailField(label="Registered Email")

class VerificationCodeForm(forms.Form):
    code = forms.CharField(label="Verification Code", max_length=6)

class CustomSetPasswordForm(SetPasswordForm):
    # Inherits password1 and password2 fields
    pass



from .models import CustomUser

class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = [
            "first_name",
            "last_name",
            "phone",
            "company_name",
            "designation",
            "address",
            "industry",
            "purpose",
            "profile_image",
        ]
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "company_name": forms.TextInput(attrs={"class": "form-control"}),
            "designation": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "industry": forms.TextInput(attrs={"class": "form-control"}),
            "purpose": forms.TextInput(attrs={"class": "form-control"}),
            "profile_image": forms.FileInput(attrs={"class": "form-control"}),
        }
