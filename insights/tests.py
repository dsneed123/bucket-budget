from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

User = get_user_model()


class InsightsViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='insights@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User',
        )
        self.client.login(email='insights@example.com', password='testpass123')

    def test_redirects_when_not_logged_in(self):
        self.client.logout()
        response = self.client.get(reverse('insights'))
        self.assertEqual(response.status_code, 302)

    def test_renders_for_authenticated_user(self):
        response = self.client.get(reverse('insights'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'insights/insights.html')

    def test_context_keys_present(self):
        response = self.client.get(reverse('insights'))
        self.assertEqual(response.status_code, 200)
        for key in ('this_spending', 'last_spending', 'cur_savings_rate', 'quality_score'):
            self.assertIn(key, response.context)
