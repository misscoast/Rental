from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import (
    RegisterForm,
    CustomerProfileForm,
    VehicleForm,
    RentalRequestForm,
    ReturnForm,
    PaymentForm,
)

from .models import User, Customer, Vehicle, Rental, Payment

from .services import (
    request_rental,
    approve_rental,
    complete_rental,
    record_payment,
)

# Create your views here.
# 1. ACCESS CONTROL
def management_required(view_func):
    """
    Restrict a view to staff, administrators and superusers.
    Customers are redirected to their dashboard.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login")

        if not request.user.is_management:
            messages.error(request, "You do not have permission to access that page.")
            return redirect("dashboard")

        return view_func(request, *args, **kwargs)
    return wrapper


# 2. PUBLIC PAGES
def home(request):
    """
    Landing page.
    """
    featured_vehicles = Vehicle.objects.filter(status=Vehicle.Status.AVAILABLE)[:6]

    context = {
        "featured_vehicles": featured_vehicles,
        "available_count": Vehicle.objects.filter(
            status=Vehicle.Status.AVAILABLE
        ).count(),
    }

    return render(request, "home.html", context)


def vehicle_list(request):
    """
    Display available vehicles to customers.
    Supports filtering by category and searching by
    make, model or registration number.
    """

    vehicles = Vehicle.objects.filter(status=Vehicle.Status.AVAILABLE)
    category = request.GET.get("category")
    search_query = request.GET.get("q")

    if category:
        vehicles = vehicles.filter(category=category)

    if search_query:
        vehicles = vehicles.filter(
            Q(make__icontains=search_query)
            | Q(model__icontains=search_query)
            | Q(registration_number__icontains=search_query)
        )

    context = {
        "vehicles": vehicles,
        "categories": Vehicle.Category.choices,
        "selected_category": category,
        "search_query": search_query,
    }
    return render(request, "vehicles/list.html", context)


# 3. AUTHENTICATION
def register(request):
    """
    Register a new customer.

    RegisterForm is responsible for creating the User
    and associated Customer profile.
    """

    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        form = RegisterForm(request.POST)

        if form.is_valid():
            form.save()

            messages.success(request, "Your account has been created. You can now log in.")

            return redirect("login")
    else:
        form = RegisterForm()
    return render(request, "accounts/register.html", {"form": form})


def login_view(request):
    """
    Authenticate a user using their username and password.
    """
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":

        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            messages.success(request, f"Welcome back, {user.get_short_name() or user.username}.")

            next_url = request.GET.get("next")

            if next_url:
                return redirect(next_url)

            return redirect("dashboard")

        messages.error(request, "Invalid username or password.")
    return render(request, "accounts/login.html")


@login_required
def logout_view(request):
    """
    Log out the current user.
    """

    logout(request)
    messages.success(request, "You have been logged out.")
    return redirect("home")


# 4. DASHBOARD
@login_required
def dashboard(request):
    """
    Display different dashboard information depending
    on whether the user is a customer or management user.
    """

    if request.user.is_management:
        vehicle_count = Vehicle.objects.count()
        available_count = Vehicle.objects.filter(status=Vehicle.Status.AVAILABLE).count()
        active_count = Rental.objects.filter(status=Rental.Status.ACTIVE).count()
        pending_count = Rental.objects.filter(status=Rental.Status.PENDING).count()
        completed_count = Rental.objects.filter(status=Rental.Status.COMPLETED).count()
        revenue = Payment.objects.filter(status=Payment.Status.SUCCESSFUL).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        recent_rentals = Rental.objects.select_related("customer__user", "vehicle").order_by("-created_at")[:8]

        metrics = [
            ("Total vehicles", vehicle_count),
            ("Available vehicles", available_count),
            ("Active rentals", active_count),
            ("Pending requests", pending_count),
            ("Completed rentals", completed_count),
        ]

        context = {
            "vehicle_count": vehicle_count,
            "available_count": available_count,
            "active_count": active_count,
            "pending_count": pending_count,
            "completed_count": completed_count,
            "revenue": revenue,
            "recent_rentals": recent_rentals,
            "metrics": metrics,
        }

    else:

        customer = get_object_or_404(Customer, user=request.user)
        customer_rentals = Rental.objects.filter(customer=customer).select_related("vehicle")
        active_rentals = customer_rentals.filter(status=Rental.Status.ACTIVE)
        pending_rentals = customer_rentals.filter(status=Rental.Status.PENDING)
        completed_rentals = customer_rentals.filter(status=Rental.Status.COMPLETED)
        recent_rentals = customer_rentals.order_by("-created_at")[:5]

        context = {
            "customer": customer,
            "active_rentals": active_rentals,
            "pending_rentals": pending_rentals,
            "completed_rentals": completed_rentals,
            "recent_rentals": recent_rentals,
            "active_count": active_rentals.count(),
            "pending_count": pending_rentals.count(),
            "completed_count": completed_rentals.count(),
        }

    return render(request, "dashboard/index.html", context)


# 5. CUSTOMER RENTAL REQUESTS
@login_required
def rental_request(request, vehicle_id=None):
    """
    Allow a customer to request a vehicle.

    The request is created with PENDING status.
    Management must approve it before the rental becomes active.
    """

    if request.user.is_management:
        messages.info(request, "Management accounts cannot request customer rentals.")
        return redirect("dashboard")

    customer = Customer.objects.filter(user=request.user).first()
    if customer is None:
        profile_form = CustomerProfileForm(request.POST or None)

        if request.method == "POST" and profile_form.is_valid():
            customer = profile_form.save(commit=False)
            customer.user = request.user
            customer.save()
            messages.success(request, "Your customer profile has been completed.")
            return redirect(request.path)

        return render(
            request,
            "rentals/request.html",
            {"profile_form": profile_form},
        )

    initial = {}

    if vehicle_id:
        vehicle = get_object_or_404(Vehicle, pk=vehicle_id, status=Vehicle.Status.AVAILABLE)
        initial["vehicle"] = vehicle

    if request.method == "POST":
        form = RentalRequestForm(request.POST, initial=initial)

        if form.is_valid():
            vehicle = form.cleaned_data["vehicle"]
            rental_days = form.cleaned_data["rental_days"]
            start_date = form.cleaned_data["start_date"]

            try:
                rental = request_rental(
                    customer=customer,
                    vehicle=vehicle,
                    rental_days=rental_days,
                    start_date=start_date,
                )

                messages.success(
                    request,
                    (
                        f"Your rental request {rental.rental_id} "
                        "has been submitted for approval."
                    ),
                )
                return redirect("my_rentals")
            except ValueError as error:
                form.add_error(None, str(error))

    else:
        form = RentalRequestForm(initial=initial)
    return render(request, "rentals/request.html", {"form": form})


@login_required
def my_rentals(request):
    """
    Show a customer only their own rental history.
    """

    customer = get_object_or_404(Customer, user=request.user)

    rentals = (
        Rental.objects.filter(customer=customer)
        .select_related("vehicle")
        .prefetch_related("payments")
    )

    context = {
        "rentals": rentals,
    }
    return render(request, "rentals/my_rentals.html", context)


# 6. VEHICLE MANAGEMENT
@management_required
def manage_vehicles(request):
    """
    Display the fleet and provide a vehicle creation form.
    """

    if request.method == "POST":

        form = VehicleForm(request.POST)

        if form.is_valid():
            vehicle = form.save()

            messages.success(request, f"{vehicle} has been added to the fleet.")
            return redirect("manage_vehicles")

    else:
        form = VehicleForm()

    vehicles = Vehicle.objects.all()

    context = {
        "form": form,
        "vehicles": vehicles,
    }
    return render(request, "vehicles/manage.html", context)


@management_required
def edit_vehicle(request, vehicle_id):
    """
    Edit an existing vehicle.
    """

    vehicle = get_object_or_404(Vehicle, pk=vehicle_id)
    if request.method == "POST":

        form = VehicleForm(request.POST, instance=vehicle)

        if form.is_valid():
            form.save()

            messages.success(request, "Vehicle details have been updated.")

            return redirect("manage_vehicles")

    else:
        form = VehicleForm(instance=vehicle)

    return render(
        request,
        "vehicles/edit.html",
        {
            "form": form,
            "vehicle": vehicle,
        },
    )


# 7. RENTAL APPROVAL
@management_required
def rental_queue(request):
    """
    Display pending rental requests for management review.
    """
    rentals = (
        Rental.objects.filter(status=Rental.Status.PENDING)
        .select_related("customer__user", "vehicle")
        .order_by("created_at")
    )
    return render(request, "rentals/queue.html", {"rentals": rentals})


@management_required
def approve_rental_view(request, rental_id):
    """
    Approve a pending rental request.

    Approval must be submitted using POST.
    """

    if request.method != "POST":
        return redirect("rental_queue")

    rental = get_object_or_404(Rental, pk=rental_id, status=Rental.Status.PENDING)

    try:
        approve_rental(rental)

        messages.success(request, f"Rental {rental.rental_id} has been approved.")

    except ValueError as error:
        messages.error(request, str(error))

    return redirect("rental_queue")


# ==========================================================
# 8. VEHICLE RETURNS
# ==========================================================


@management_required
def return_rental(request, rental_id):
    """
    Process the return of an active rental.

    The service calculates the final rental cost,
    including late fees and damage charges.
    """

    rental = get_object_or_404(
        Rental.objects.select_related("vehicle", "customer__user"),
        pk=rental_id,
        status=Rental.Status.ACTIVE,
    )

    if request.method == "POST":

        form = ReturnForm(request.POST, rental=rental)

        if form.is_valid():

            actual_return_date = form.cleaned_data["actual_return_date"]

            damage_charge = form.cleaned_data.get("damage_charge", Decimal("0.00"))

            try:
                complete_rental(
                    rental=rental,
                    actual_return_date=actual_return_date,
                    damage_charge=damage_charge,
                )

                rental.refresh_from_db()

                messages.success(
                    request,
                    (
                        f"Rental {rental.rental_id} completed. "
                        f"Final amount due: KSh {rental.total_cost:,.2f}"
                    ),
                )

                return redirect("record_payment", rental_id=rental.pk)

            except ValueError as error:
                form.add_error(None, str(error))

    else:
        form = ReturnForm( 
            rental=rental,
            initial={
                "actual_return_date": timezone.localdate(),
                "damage_charge": Decimal("0.00"),
            }
        )

    context = {
        "form": form,
        "rental": rental,
    }

    return render(request, "rentals/return.html", context)


# ==========================================================
# 9. PAYMENT PROCESSING
# ==========================================================


@management_required
def record_payment_view(request, rental_id):
    """
    Record a payment for a completed rental.

    This is a simulated payment process. It does not
    connect to the live M-Pesa or card payment networks.
    """

    rental = get_object_or_404(
        Rental.objects.select_related("customer__user", "vehicle"),
        pk=rental_id,
        status=Rental.Status.COMPLETED,
        is_paid=False,
    )

    if request.method == "POST":

        form = PaymentForm(request.POST, rental=rental)

        if form.is_valid():

            method = form.cleaned_data["method"]
            amount = form.cleaned_data["amount"]
            reference = form.cleaned_data.get("transaction_reference", "")

            try:
                payment = record_payment(
                    rental=rental, method=method, amount=amount, reference=reference
                )

                messages.success(
                    request,
                    (f"Payment {payment.payment_id} " "was recorded successfully."),
                )

                return redirect("dashboard")

            except ValueError as error:
                form.add_error(None, str(error))

    else:
        form = PaymentForm(
            rental=rental,
            initial={
                "amount": rental.total_cost,
            }
        )

    context = {
        "form": form,
        "rental": rental,
    }

    return render(request, "payments/record.html", context)


# 10. REPORTS
@management_required
def reports(request):
    """
    Display fleet, rental and revenue reports.
    """
    total_vehicles = Vehicle.objects.count()
    available_vehicles = Vehicle.objects.filter(status=Vehicle.Status.AVAILABLE).count()
    rented_vehicles = Vehicle.objects.filter(status=Vehicle.Status.RENTED).count()
    maintenance_vehicles = Vehicle.objects.filter(status=Vehicle.Status.MAINTENANCE).count()
    total_rentals = Rental.objects.count()
    active_rentals = Rental.objects.filter(status=Rental.Status.ACTIVE).count()
    completed_rentals = Rental.objects.filter(status=Rental.Status.COMPLETED).count()
    cancelled_rentals = Rental.objects.filter(status=Rental.Status.CANCELLED).count()
    pending_rentals = Rental.objects.filter(status=Rental.Status.PENDING).count()
    successful_payments = Payment.objects.filter(status=Payment.Status.SUCCESSFUL)
    total_revenue = successful_payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    payment_count = successful_payments.count()
    revenue_by_method = (
        successful_payments.values("method")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("-total")
    )

    popular_vehicles = Vehicle.objects.annotate(rental_count=Count("rentals")).order_by(
        "-rental_count")[:5]

    recent_payments = Payment.objects.select_related(
        "rental__customer__user", "rental__vehicle").order_by("-created_at")[:10]

    context = {
        "total_vehicles": total_vehicles,
        "available_vehicles": available_vehicles,
        "rented_vehicles": rented_vehicles,
        "maintenance_vehicles": maintenance_vehicles,
        "total_rentals": total_rentals,
        "active_rentals": active_rentals,
        "completed_rentals": completed_rentals,
        "cancelled_rentals": cancelled_rentals,
        "pending_rentals": pending_rentals,
        "total_revenue": total_revenue,
        "payment_count": payment_count,
        "revenue_by_method": revenue_by_method,
        "popular_vehicles": popular_vehicles,
        "recent_payments": recent_payments,
    }

    return render(request, "dashboard/reports.html", context)
