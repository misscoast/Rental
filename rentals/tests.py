from django.test import TestCase
from django.urls import reverse

from .models import Customer, User, Vehicle


class RentalRequestProfileTests(TestCase):
	def test_customer_without_profile_can_complete_profile_from_request(self):
		user = User.objects.create_user(username="legacy-customer", password="test-pass")
		Vehicle.objects.create(
			id=8,
			registration_number="KAA-123A",
			make="Toyota",
			model="Corolla",
			year=2024,
			category=Vehicle.Category.ECONOMY,
			daily_rate="5000.00",
		)
		self.client.force_login(user)

		response = self.client.get(reverse("rental_request_vehicle", args=[8]))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Complete Your Customer Profile")

		response = self.client.post(
			reverse("rental_request_vehicle", args=[8]),
			{
				"phone_number": "0712345678",
				"national_id": "12345678",
				"driving_licence": "DL-12345",
			},
		)

		self.assertRedirects(response, reverse("rental_request_vehicle", args=[8]))
		self.assertTrue(Customer.objects.filter(user=user).exists())
