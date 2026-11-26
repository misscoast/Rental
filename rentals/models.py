from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone 
import uuid 
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal

# Create your models here.
class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Administrator"
        STAFF = "STAFF", "Staff"
        CUSTOMER = "CUSTOMER", "Customer"

    role = models.CharField(
        max_length=12,
        choices=Role.choices,
        default=Role.CUSTOMER
    )

    @property
    def is_management(self):
        return (
            self.is_superuser
            or self.role in {self.Role.ADMIN, self.Role.STAFF}
        )

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

    

# ==========================================================
# 2. CUSTOMER MODEL
# ==========================================================

class Customer(models.Model):

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="customer_profile"
    )

    customer_id = models.CharField(
        max_length=20,
        unique=True,
        blank=True
    )

    phone_number = models.CharField(max_length=20)

    national_id = models.CharField(
        max_length=30,
        blank=True
    )

    driving_licence = models.CharField(max_length=50)

    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.customer_id:
            self.customer_id = (
                f"CUS-{uuid.uuid4().hex[:8].upper()}"
            )

        super().save(*args, **kwargs)

    def __str__(self):
        name = self.user.get_full_name() or self.user.username
        return f"{name} ({self.customer_id})"

# ==========================================================
# 3. VEHICLE MODEL
# ==========================================================

class Vehicle(models.Model):

    class Category(models.TextChoices):
        ECONOMY = "ECONOMY", "Economy"
        SUV = "SUV", "SUV"
        LUXURY = "LUXURY", "Luxury"

    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Available"
        RENTED = "RENTED", "Rented"
        MAINTENANCE = "MAINTENANCE", "Maintenance"

    registration_number = models.CharField(
        max_length=20,
        unique=True
    )

    make = models.CharField(max_length=60)

    model = models.CharField(max_length=60)

    year = models.PositiveIntegerField(
        validators=[
            MinValueValidator(1900),
            MaxValueValidator(2100)
        ]
    )

    category = models.CharField(
        max_length=10,
        choices=Category.choices
    )

    daily_rate = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))]
    )

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.AVAILABLE
    )

    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["make", "model"]

    def __str__(self):
        return (
            f"{self.make} {self.model} "
            f"({self.registration_number})"
        )

    def rental_cost(self, days):
        """
        Calculate rental cost based on vehicle category.

        Economy:
            Daily rate * days

        SUV:
            Daily rate * days + KSh 2,000 service charge

        Luxury:
            Daily rate * days + 10% insurance
        """

        if days <= 0:
            raise ValueError("Rental days must be greater than zero.")

        base_cost = self.daily_rate * days

        if self.category == self.Category.SUV:
            return base_cost + Decimal("2000.00")

        if self.category == self.Category.LUXURY:
            return base_cost * Decimal("1.10")

        return base_cost

# ==========================================================
# 4. RENTAL MODEL
# ==========================================================

class Rental(models.Model):

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending approval"
        ACTIVE = "ACTIVE", "Active"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    rental_id = models.CharField(
        max_length=20,
        unique=True,
        blank=True
    )

    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="rentals"
    )

    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.PROTECT,
        related_name="rentals"
    )

    rental_days = models.PositiveIntegerField(
        validators=[MinValueValidator(1)]
    )

    start_date = models.DateField(
        default=timezone.localdate
    )

    expected_return_date = models.DateField()

    actual_return_date = models.DateField(
        null=True,
        blank=True
    )

    # Snapshot the agreed rate so future price changes
    # do not affect historical rentals.
    daily_rate_snapshot = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    base_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00")
    )

    late_fee = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00")
    )

    damage_charge = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00")
    )

    total_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00")
    )

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING
    )

    is_paid = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.rental_id:
            self.rental_id = (
                f"RNT-{uuid.uuid4().hex[:8].upper()}"
            )

        super().save(*args, **kwargs)

    @property
    def late_days(self):
        if not self.actual_return_date:
            return 0

        difference = (
            self.actual_return_date - self.expected_return_date
        ).days

        return max(difference, 0)

    def calculate_late_fee(self):
        """
        Late fee = 20% of agreed daily rate per late day.
        """

        fee = (
            self.daily_rate_snapshot
            * Decimal("0.20")
            * self.late_days
        )

        return fee.quantize(Decimal("0.01"))

    def calculate_total(self):
        return (
            self.base_cost
            + self.late_fee
            + self.damage_charge
        )

    def __str__(self):
        return self.rental_id or f"Rental {self.pk}"