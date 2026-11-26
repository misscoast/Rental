from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import User, Customer, Vehicle, Rental, Payment

# SHARED FORM STYLING
INPUT_CLASS = (
    "w-full rounded-lg border border-gray-300 px-4 py-2 "
    "focus:outline-none focus:ring-2 focus:ring-blue-500"
)

SELECT_CLASS = (
    "w-full rounded-lg border border-gray-300 px-4 py-2 "
    "bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
)


def apply_form_styling(form):
    """
    Apply consistent CSS classes to form widgets.
    """
    for field in form.fields.values():

        if isinstance(field.widget, forms.Select):
            field.widget.attrs["class"] = SELECT_CLASS

        elif isinstance(field.widget, forms.CheckboxInput):
            field.widget.attrs["class"] = "rounded border-gray-300"

        else:
            field.widget.attrs["class"] = INPUT_CLASS


# 1. CUSTOMER REGISTRATION
class RegisterForm(UserCreationForm):
    """
    Register a user and create their associated Customer profile.
    """

    email = forms.EmailField(required=True)
    phone_number = forms.CharField(max_length=20, required=True, label="Phone number")
    national_id = forms.CharField(max_length=30, required=False, label="National ID")
    driving_licence = forms.CharField(
        max_length=50, required=True, label="Driving licence number"
    )

    class Meta:
        model = User

        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "phone_number",
            "national_id",
            "driving_licence",
            "password1",
            "password2",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_form_styling(self)

        self.fields["username"].help_text = "Choose a unique username."

        self.fields["password1"].help_text = (
            "Use a strong password that you have not used elsewhere."
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()

        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email address already exists.")

        return email

    def clean_phone_number(self):
        phone = self.cleaned_data["phone_number"].strip()

        if len(phone) < 9:
            raise ValidationError("Enter a valid phone number.")

        return phone

    def clean_driving_licence(self):
        licence = self.cleaned_data["driving_licence"].strip()

        if not licence:
            raise ValidationError("A driving licence is required to register.")

        return licence

    def save(self, commit=True):
        """
        Save the user and create their customer profile.

        Supports Django's normal commit=False pattern:
        call save_m2m() after saving the user instance.
        """

        user = super().save(commit=False)

        user.email = self.cleaned_data["email"]
        user.role = User.Role.CUSTOMER

        customer_data = {
            "phone_number": self.cleaned_data["phone_number"],
            "national_id": self.cleaned_data["national_id"],
            "driving_licence": self.cleaned_data["driving_licence"],
        }

        self._customer_data = customer_data

        if commit:
            user.save()
            self.save_m2m()

        return user

    def save_m2m(self):
        """
        Create the Customer profile after the User is saved.
        """
        super().save_m2m()

        if getattr(self, "_customer_data", None):
            if not hasattr(self.instance, "customer_profile"):
                Customer.objects.create(user=self.instance, **self._customer_data)

            self._customer_data = None


class CustomerProfileForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["phone_number", "national_id", "driving_licence"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_form_styling(self)


# 2. VEHICLE FORM
class VehicleForm(forms.ModelForm):
    """
    Create and update vehicles in the fleet.
    """

    class Meta:
        model = Vehicle

        fields = [
            "registration_number",
            "make",
            "model",
            "year",
            "category",
            "daily_rate",
            "status",
            "description",
        ]

        widgets = {
            "description": forms.Textarea(
                attrs={"rows": 4, "placeholder": "Vehicle description..."}
            ),
            "daily_rate": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "year": forms.NumberInput(attrs={"min": 1900, "max": 2100}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_form_styling(self)


# 3. RENTAL REQUEST FORM
class RentalRequestForm(forms.Form):
    """
    Capture a customer's vehicle rental request.
    """

    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.none(), empty_label="Select a vehicle"
    )

    rental_days = forms.IntegerField(
        min_value=1,
        max_value=365,
        label="Number of rental days",
        widget=forms.NumberInput(attrs={"min": 1, "max": 365}),
    )

    start_date = forms.DateField(
        initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["vehicle"].queryset = Vehicle.objects.filter(
            status=Vehicle.Status.AVAILABLE
        )

        apply_form_styling(self)

    def clean_start_date(self):
        start_date = self.cleaned_data["start_date"]

        if start_date < timezone.localdate():
            raise ValidationError("The rental start date cannot be in the past.")

        return start_date

    def clean(self):
        cleaned_data = super().clean()

        vehicle = cleaned_data.get("vehicle")
        rental_days = cleaned_data.get("rental_days")

        if vehicle and rental_days:
            try:
                vehicle.rental_cost(rental_days)
            except ValueError as error:
                raise ValidationError(str(error))

        return cleaned_data



# 4. RENTAL RETURN FORM
class ReturnForm(forms.Form):
    """
    Capture return details and any damage charges.
    """

    actual_return_date = forms.DateField(initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}))

    damage_charge = forms.DecimalField(
        min_value=0,
        max_digits=12,
        decimal_places=2,
        initial=0,
        required=True,
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
    )

    def __init__(self, *args, rental=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.rental = rental

        apply_form_styling(self)

    def clean_actual_return_date(self):
        return_date = self.cleaned_data["actual_return_date"]

        if return_date > timezone.localdate():
            raise ValidationError("The return date cannot be in the future.")

        if self.rental and return_date < self.rental.start_date:
            raise ValidationError(
                "The return date cannot be before the rental start date."
            )

        return return_date

    def clean_damage_charge(self):
        damage_charge = self.cleaned_data["damage_charge"]

        if damage_charge < 0:
            raise ValidationError("Damage charges cannot be negative.")

        return damage_charge


# 5. PAYMENT FORM
class PaymentForm(forms.Form):
    """
    Capture simulated payment details.
    """
    method = forms.ChoiceField(choices=Payment.Method.choices, label="Payment method")
    amount = forms.DecimalField(
        min_value=0.01,
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
    )

    transaction_reference = forms.CharField(
        max_length=100,
        required=False,
        label="Transaction reference",
        help_text="For example, an M-Pesa confirmation code.",
    )

    def __init__(self, *args, rental=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.rental = rental

        apply_form_styling(self)

    def clean_amount(self):
        amount = self.cleaned_data["amount"]

        if amount <= 0:
            raise ValidationError("Payment amount must be greater than zero.")

        if self.rental and amount != self.rental.total_cost:
            raise ValidationError(
                (
                    f"The amount must equal the outstanding rental cost "
                    f"of KSh {self.rental.total_cost:,.2f}."
                )
            )

        return amount

    def clean_transaction_reference(self):
        reference = self.cleaned_data["transaction_reference"].strip()

        return reference
