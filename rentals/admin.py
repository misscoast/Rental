from django.contrib import admin
from .models import User, Customer, Rental,Vehicle

# Register your models here.
admin.site.register(User)
admin.site.register(Customer)
admin.site.register(Rental)
admin.site.register(Vehicle)
