from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import CustomUser

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
