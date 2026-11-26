from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

from .models import Customer, Vehicle, Rental, Payment


# 1. RENTAL REQUEST
@transaction.atomic
def request_rental(customer, vehicle, rental_days, start_date):
    """
    Create a pending rental request.

    The vehicle is not marked as rented until management
    approves the request.
    """

    if not isinstance(customer, Customer):
        raise ValueError("A valid customer profile is required.")

    if rental_days <= 0:
        raise ValueError("Rental days must be greater than zero.")

    if start_date < timezone.localdate():
        raise ValueError("The rental start date cannot be in the past.")

    if not customer.driving_licence.strip():
        raise ValueError("A valid driving licence is required.")

    # Re-fetch the vehicle inside the transaction.
    vehicle = Vehicle.objects.select_for_update().get(pk=vehicle.pk)

    if vehicle.status != Vehicle.Status.AVAILABLE:
        raise ValueError("This vehicle is no longer available.")

    # Do not allow another pending request for this vehicle
    # with an overlapping rental period.
    expected_return_date = start_date + timedelta(days=rental_days)

    overlapping_requests = Rental.objects.filter(
        vehicle=vehicle,
        status__in=[
            Rental.Status.PENDING,
            Rental.Status.ACTIVE,
        ],
        start_date__lt=expected_return_date,
        expected_return_date__gt=start_date,
    )

    if overlapping_requests.exists():
        raise ValueError(
            "This vehicle already has a request or rental " "covering those dates."
        )

    base_cost = vehicle.rental_cost(rental_days)

    rental = Rental.objects.create(
        customer=customer,
        vehicle=vehicle,
        rental_days=rental_days,
        start_date=start_date,
        expected_return_date=expected_return_date,
        daily_rate_snapshot=vehicle.daily_rate,
        base_cost=base_cost,
        total_cost=base_cost,
        status=Rental.Status.PENDING,
    )

    return rental


# 2. APPROVE RENTAL
@transaction.atomic
def approve_rental(rental):
    """
    Approve a pending rental request.

    Once approved:
    - Rental status becomes ACTIVE.
    - Vehicle status becomes RENTED.
    """

    rental = Rental.objects.select_for_update().get(pk=rental.pk)

    if rental.status != Rental.Status.PENDING:
        raise ValueError("Only pending rental requests can be approved.")

    vehicle = Vehicle.objects.select_for_update().get(pk=rental.vehicle_id)

    if vehicle.status != Vehicle.Status.AVAILABLE:
        raise ValueError("This vehicle is no longer available.")

    # Check for another active rental covering the same dates.
    conflicting_rentals = Rental.objects.filter(
        vehicle=vehicle,
        status=Rental.Status.ACTIVE,
        start_date__lt=rental.expected_return_date,
        expected_return_date__gt=rental.start_date,
    ).exclude(pk=rental.pk)

    if conflicting_rentals.exists():
        raise ValueError("This vehicle has another active rental during those dates.")

    vehicle.status = Vehicle.Status.RENTED
    vehicle.save(update_fields=["status"])

    rental.status = Rental.Status.ACTIVE
    rental.save(update_fields=["status"])

    return rental


# ==========================================================
# 3. COMPLETE RENTAL / PROCESS RETURN
# ==========================================================


@transaction.atomic
def complete_rental(rental, actual_return_date, damage_charge=Decimal("0.00")):
    """
    Complete an active rental.

    Calculates:
    - Late return fees.
    - Damage charges.
    - Final rental cost.

    The late fee is 20% of the agreed daily rate
    for every day returned late.
    """

    rental = Rental.objects.select_for_update().get(pk=rental.pk)

    if rental.status != Rental.Status.ACTIVE:
        raise ValueError("Only active rentals can be completed.")

    if actual_return_date < rental.start_date:
        raise ValueError("The return date cannot be before the rental start date.")

    if actual_return_date > timezone.localdate():
        raise ValueError("The return date cannot be in the future.")

    damage_charge = Decimal(str(damage_charge))

    if damage_charge < Decimal("0.00"):
        raise ValueError("Damage charges cannot be negative.")

    vehicle = Vehicle.objects.select_for_update().get(pk=rental.vehicle_id)

    rental.actual_return_date = actual_return_date
    rental.damage_charge = damage_charge

    rental.late_fee = rental.calculate_late_fee()
    rental.total_cost = rental.calculate_total()

    rental.status = Rental.Status.COMPLETED

    rental.save(
        update_fields=[
            "actual_return_date",
            "damage_charge",
            "late_fee",
            "total_cost",
            "status",
        ]
    )

    # The vehicle becomes available again after return.
    # A future maintenance workflow can change this behaviour.
    vehicle.status = Vehicle.Status.AVAILABLE
    vehicle.save(update_fields=["status"])

    return rental


# 4. RECORD PAYMENT
@transaction.atomic
def record_payment(rental, method, amount, reference=""):
    """
    Record a successful simulated payment.

    Business rules:
    - Rental must be completed.
    - Rental must not already be paid.
    - Payment amount must equal the final rental cost.
    - Payment method must be valid.
    """

    rental = Rental.objects.select_for_update().get(pk=rental.pk)

    if rental.status != Rental.Status.COMPLETED:
        raise ValueError("Payment can only be recorded for completed rentals.")

    if rental.is_paid:
        raise ValueError("This rental has already been paid.")

    if method not in Payment.Method.values:
        raise ValueError("Invalid payment method.")

    amount = Decimal(str(amount))

    if amount <= Decimal("0.00"):
        raise ValueError("Payment amount must be greater than zero.")

    if amount != rental.total_cost:
        raise ValueError(
            (
                f"Payment must equal the final rental cost "
                f"of KSh {rental.total_cost:,.2f}."
            )
        )

    payment = Payment.objects.create(
        rental=rental,
        method=method,
        amount=amount,
        transaction_reference=reference,
        status=Payment.Status.SUCCESSFUL,
    )

    rental.is_paid = True
    rental.save(update_fields=["is_paid"])

    return payment


# 5. CANCEL RENTAL REQUEST
@transaction.atomic
def cancel_rental(rental, customer=None):
    """
    Cancel a pending rental request.

    Customers may cancel only their own pending requests.
    Management may cancel any pending request.
    """

    rental = Rental.objects.select_for_update().get(pk=rental.pk)

    if rental.status != Rental.Status.PENDING:
        raise ValueError("Only pending rental requests can be cancelled.")

    if customer is not None and rental.customer_id != customer.pk:
        raise ValueError("You cannot cancel another customer's rental.")

    rental.status = Rental.Status.CANCELLED
    rental.save(update_fields=["status"])

    return rental
