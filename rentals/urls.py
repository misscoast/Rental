from django.urls import path

from . import views


urlpatterns = [
    path("", views.home, name="home"),
    path("vehicles/", views.vehicle_list, name="vehicle_list"),

    path("register/", views.register, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    path("dashboard/", views.dashboard, name="dashboard"),

    path("rentals/request/", views.rental_request, name="rental_request"),
    path("rentals/request/<int:vehicle_id>/", views.rental_request, name="rental_request_vehicle"),
    path("rentals/my/", views.my_rentals, name="my_rentals"),

    path("manage/vehicles/", views.manage_vehicles, name="manage_vehicles"),
    path("manage/vehicles/<int:vehicle_id>/edit/", views.edit_vehicle, name="edit_vehicle"),

    path("manage/rentals/queue/", views.rental_queue, name="rental_queue"),
    path("manage/rentals/<int:rental_id>/approve/", views.approve_rental_view, name="approve_rental"),
    path("manage/rentals/<int:rental_id>/return/", views.return_rental, name="return_rental"),
    path("manage/rentals/<int:rental_id>/payment/", views.record_payment_view, name="record_payment"),

    path("manage/reports/", views.reports, name="reports"),
]
