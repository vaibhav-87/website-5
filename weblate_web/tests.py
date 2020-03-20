import os
import shutil
import tempfile
from datetime import timedelta
from xml.etree import ElementTree

import requests
import responses
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.core.signing import dumps
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import override

from payments.data import SUPPORTED_LANGUAGES
from payments.models import Customer, Payment

from .data import EXTENSIONS, VERSION
from .models import PAYMENTS_ORIGIN, Donation, Package, Post
from .remote import (
    ACTIVITY_URL,
    WEBLATE_CONTRIBUTORS_URL,
    get_activity,
    get_contributors,
)
from .templatetags.downloads import downloadlink, filesizeformat

TEST_DATA = os.path.join(os.path.dirname(__file__), "test-data")
TEST_FAKTURACE = os.path.join(TEST_DATA, "fakturace")
TEST_CONTRIBUTORS = os.path.join(TEST_DATA, "contributors.json")
TEST_ACTIVITY = os.path.join(TEST_DATA, "activity.json")
TEST_IMAGE = os.path.join(TEST_DATA, "weblate-html.png")

TEST_CUSTOMER = {
    "name": "Michal Čihař",
    "address": "Zdiměřická 1439",
    "city": "149 00 Praha 4",
    "country": "CZ",
    "vat_0": "CZ",
    "vat_1": "8003280318",
}


def fake_remote():
    cache.set("wlweb-contributors", [])
    cache.set("wlweb-activity-stats", [])
    cache.set(
        "wlweb-changes-list",
        [
            {
                "failing_percent": 0.4,
                "translated_percent": 20.3,
                "total_words": 12385202,
                "failing": 3708,
                "translated_words": 1773069,
                "url_translate": "https://hosted.weblate.org/projects/godot-engine/",
                "fuzzy_percent": 3.9,
                "recent_changes": 2401,
                "translated": 160302,
                "fuzzy": 31342,
                "total": 787070,
                "last_change": timezone.now(),
                "name": "Godot Engine",
                "url": "https://hosted.weblate.org/engage/godot-engine/",
            },
            {
                "failing_percent": 1.4,
                "translated_percent": 46.0,
                "total_words": 7482588,
                "failing": 14319,
                "translated_words": 2917305,
                "url_translate": "https://hosted.weblate.org/projects/phpmyadmin/",
                "fuzzy_percent": 12.3,
                "recent_changes": 3652,
                "translated": 465082,
                "fuzzy": 124794,
                "total": 1009956,
                "last_change": timezone.now() - timedelta(seconds=3600),
                "name": "phpMyAdmin",
                "url": "https://hosted.weblate.org/engage/phpmyadmin/",
            },
            {
                "failing_percent": 0.4,
                "translated_percent": 48.8,
                "total_words": 1386375,
                "failing": 1121,
                "translated_words": 586192,
                "url_translate": "https://hosted.weblate.org/projects/weblate/",
                "fuzzy_percent": 9.5,
                "recent_changes": 2864,
                "translated": 125298,
                "fuzzy": 24461,
                "total": 256275,
                "last_change": timezone.now() - timedelta(seconds=14400),
                "name": "Weblate",
                "url": "https://hosted.weblate.org/engage/weblate/",
            },
            {
                "failing_percent": 0.8,
                "translated_percent": 20.1,
                "total_words": 7707495,
                "failing": 4459,
                "translated_words": 1066440,
                "url_translate": "https://hosted.weblate.org/projects/f-droid/",
                "fuzzy_percent": 0.7,
                "recent_changes": 7080,
                "translated": 104941,
                "fuzzy": 4011,
                "total": 520867,
                "last_change": timezone.now() - timedelta(days=1),
                "name": "F-Droid",
                "url": "https://hosted.weblate.org/engage/f-droid/",
            },
            {
                "failing_percent": 1.0,
                "translated_percent": 72.9,
                "total_words": 324480,
                "failing": 883,
                "translated_words": 231003,
                "url_translate": "https://hosted.weblate.org/projects/freeplane/",
                "fuzzy_percent": 2.1,
                "recent_changes": 535,
                "translated": 61980,
                "fuzzy": 1787,
                "total": 84920,
                "last_change": timezone.now() - timedelta(days=4),
                "name": "Freeplane",
                "url": "https://hosted.weblate.org/engage/freeplane/",
            },
            {
                "failing_percent": 4.4,
                "translated_percent": 57.8,
                "total_words": 2016830,
                "failing": 25211,
                "translated_words": 1036249,
                "url_translate": "https://hosted.weblate.org/projects/osmand/",
                "fuzzy_percent": 3.0,
                "recent_changes": 3633,
                "translated": 325725,
                "fuzzy": 16981,
                "total": 562798,
                "last_change": timezone.now() - timedelta(days=30),
                "name": "OsmAnd",
                "url": "https://hosted.weblate.org/engage/osmand/",
            },
        ],
    )


def fake_payment(url):
    response = requests.get(url)
    response = requests.get(response.url[:-1] + "p")
    body = response.content.decode()
    for line in body.splitlines():
        if '<input type="hidden" name="id"' in line:
            payment_number = line.split('value="')[1].split('"')[0]
    # Confirm payment state
    response = requests.post(
        "https://www.thepay.cz/demo-gate/return.php",
        data={"state": 2, "underpaid_value": 1, "id": payment_number},
        allow_redirects=False,
    )
    return response.headers["Location"]


class PostTestCase(TestCase):
    @staticmethod
    def create_post(title="testpost", body="testbody", timestamp=None):
        if timestamp is None:
            timestamp = timezone.now() - relativedelta(days=1)
        return Post.objects.create(
            title=title, slug=title, body=body, timestamp=timestamp
        )


class ViewTestCase(PostTestCase):
    """Views testing."""

    def setUp(self):
        super().setUp()
        fake_remote()

    def test_index_redirect(self):
        response = self.client.get("/")
        self.assertRedirects(response, "/en/", 302)

    def test_index_en(self):
        response = self.client.get("/en/")
        self.assertContains(response, "Basic")

    def test_index_cs(self):
        response = self.client.get("/cs/")
        self.assertContains(response, "Základní")

    def test_index_he(self):
        response = self.client.get("/he/")
        self.assertContains(response, "בסיסית")

    def test_index_be(self):
        response = self.client.get("/be/")
        self.assertContains(response, "Базавы")

    def test_index_be_latin(self):
        response = self.client.get("/be@latin/")
        self.assertContains(response, "Prosty")

    def test_terms(self):
        response = self.client.get("/en/terms/")
        self.assertContains(response, "04705904")

    def test_security_txt(self):
        response = self.client.get("/security.txt")
        self.assertContains(response, "https://hackerone.com/weblate")

    @responses.activate
    def test_about(self):
        with open(TEST_CONTRIBUTORS) as handle:
            responses.add(responses.GET, WEBLATE_CONTRIBUTORS_URL, body=handle.read())
        get_contributors(force=True)
        response = self.client.get("/en/about/")
        self.assertContains(response, "comradekingu")
        # Test error handling, cached content should stay there
        responses.replace(responses.GET, WEBLATE_CONTRIBUTORS_URL, status=500)
        get_contributors(force=True)
        response = self.client.get("/en/about/")
        self.assertContains(response, "comradekingu")

    @responses.activate
    def test_activity(self):
        with open(TEST_ACTIVITY) as handle:
            responses.add(responses.GET, ACTIVITY_URL, body=handle.read())
        get_activity(force=True)
        response = self.client.get("/img/activity.svg")
        self.assertContains(response, "<svg")
        # Test error handling, cached content should stay there
        responses.replace(responses.GET, ACTIVITY_URL, status=500)
        get_activity(force=True)
        response = self.client.get("/img/activity.svg")
        self.assertContains(response, "<svg")

    def test_download_en(self):
        # create dummy files for testing
        filenames = ["Weblate-{0}.{1}".format(VERSION, ext) for ext in EXTENSIONS]
        filenames.append("Weblate-test-{0}.tar.xz".format(VERSION))

        temp_dir = tempfile.mkdtemp()

        try:
            with override_settings(FILES_PATH=temp_dir):
                for filename in filenames:
                    fullname = os.path.join(settings.FILES_PATH, filename)
                    with open(fullname, "w") as handle:
                        handle.write("test")

                response = self.client.get("/en/download/")
                self.assertContains(response, "Download Weblate")

        finally:
            shutil.rmtree(temp_dir)

    def test_sitemap_lang(self):
        response = self.client.get("/sitemap-es.xml")
        self.assertContains(response, "http://testserver/es/features/")

    def test_sitemap_news(self):
        self.create_post()
        response = self.client.get("/sitemap-news.xml")
        self.assertContains(response, "testpost")

    def test_sitemaps(self):
        # Get root sitemap
        response = self.client.get("/sitemap.xml")
        self.assertContains(response, "<sitemapindex")

        # Parse it
        tree = ElementTree.fromstring(response.content)
        sitemaps = tree.findall("{http://www.sitemaps.org/schemas/sitemap/0.9}sitemap")
        for sitemap in sitemaps:
            location = sitemap.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
            response = self.client.get(location.text)
            self.assertContains(response, "<urlset")
            # Try if it's a valid XML
            ElementTree.fromstring(response.content)


class UtilTestCase(TestCase):
    """Helper code testing."""

    def test_format(self):
        self.assertEqual(filesizeformat(0), "0 bytes")
        self.assertEqual(filesizeformat(1000), "1000 bytes")
        self.assertEqual(filesizeformat(1000000), "976.6 KiB")
        self.assertEqual(filesizeformat(1000000000), "953.7 MiB")
        self.assertEqual(filesizeformat(10000000000000), "9313.2 GiB")

    @override_settings(FILES_PATH=TEST_DATA)
    def test_downloadlink(self):
        self.assertEqual(
            "Sources tarball, gzip compressed", downloadlink("foo.tar.gz")["text"]
        )
        self.assertEqual(
            "Sources tarball, xz compressed", downloadlink("foo.tar.xz")["text"]
        )
        self.assertEqual(
            "Sources tarball, bzip2 compressed", downloadlink("foo.tar.bz2")["text"]
        )
        self.assertEqual("Sources, zip compressed", downloadlink("foo.zip")["text"])
        self.assertEqual("0 bytes", downloadlink("foo.pdf")["size"])
        self.assertEqual("0 bytes", downloadlink("foo.pdf", "text")["size"])
        self.assertEqual("text", downloadlink("foo.pdf", "text")["text"])


class FakturaceTestCase(TestCase):
    databases = "__all__"

    def setUp(self):
        super().setUp()
        dirs = ("contacts", "data", "pdf", "tex", "config")
        for name in dirs:
            full = os.path.join(TEST_FAKTURACE, name)
            if not os.path.exists(full):
                os.makedirs(full)

    @staticmethod
    def create_payment():
        customer = Customer.objects.create(
            email="weblate@example.com", user_id=1, origin=PAYMENTS_ORIGIN,
        )
        payment = Payment.objects.create(
            customer=customer,
            amount=100,
            description="Test payment",
            backend="pay",
            recurring="y",
        )
        return (
            payment,
            reverse("payment", kwargs={"pk": payment.pk}),
            reverse("payment-customer", kwargs={"pk": payment.pk}),
        )


class PaymentsTest(FakturaceTestCase):
    def setUp(self):
        super().setUp()
        fake_remote()

    def test_languages(self):
        self.assertEqual(
            set(SUPPORTED_LANGUAGES), {x[0] for x in settings.LANGUAGES},
        )

    def test_view(self):
        with override("en"):
            payment, url, customer_url = self.create_payment()
            response = self.client.get(url, follow=True)
            self.assertRedirects(response, customer_url)
            self.assertContains(response, "Please provide your billing")
            response = self.client.post(customer_url, TEST_CUSTOMER, follow=True,)
            self.assertRedirects(response, url)
            self.assertContains(response, "Test payment")
            self.assertContains(response, "121.0 EUR")
            return payment, url, customer_url

    def check_payment(self, payment, state):
        fresh = Payment.objects.get(pk=payment.pk)
        self.assertEqual(fresh.state, state)

    @override_settings(PAYMENT_DEBUG=True, PAYMENT_FAKTURACE=TEST_FAKTURACE)
    def test_pay(self):
        payment, url, dummy = self.test_view()
        response = self.client.post(url, {"method": "pay"})
        self.assertRedirects(
            response,
            "{}?payment={}".format(PAYMENTS_ORIGIN, payment.pk),
            fetch_redirect_response=False,
        )
        self.check_payment(payment, Payment.ACCEPTED)

    @override_settings(PAYMENT_DEBUG=True, PAYMENT_FAKTURACE=TEST_FAKTURACE)
    def test_invalid_vat(self):
        payment, url, customer_url = self.test_view()
        # Inject invalid VAT
        customer = Customer.objects.get(pk=payment.customer.pk)
        customer.vat = "CZ8003280317"
        customer.save()

        response = self.client.get(url, follow=True)
        self.assertRedirects(response, customer_url)
        self.assertContains(response, "The VAT ID is no longer valid")

    @override_settings(PAYMENT_DEBUG=True)
    def test_reject(self):
        payment, url, dummy = self.test_view()
        response = self.client.post(url, {"method": "reject"})
        self.assertRedirects(
            response,
            "{}?payment={}".format(PAYMENTS_ORIGIN, payment.pk),
            fetch_redirect_response=False,
        )
        self.check_payment(payment, Payment.REJECTED)

    @override_settings(PAYMENT_DEBUG=True, PAYMENT_FAKTURACE=TEST_FAKTURACE)
    def test_pending(self):
        payment, url, dummy = self.test_view()
        response = self.client.post(url, {"method": "pending"})
        complete_url = reverse("payment-complete", kwargs={"pk": payment.pk})
        self.assertRedirects(
            response,
            "https://cihar.com/?url=http://testserver" + complete_url,
            fetch_redirect_response=False,
        )
        self.check_payment(payment, Payment.PENDING)
        response = self.client.get(complete_url)
        self.assertRedirects(
            response,
            "{}?payment={}".format(PAYMENTS_ORIGIN, payment.pk),
            fetch_redirect_response=False,
        )
        self.check_payment(payment, Payment.ACCEPTED)


class DonationTest(FakturaceTestCase):
    credentials = {"username": "testuser", "password": "testpassword"}

    def setUp(self):
        super().setUp()
        fake_remote()

    def create_user(self):
        return User.objects.create_user(**self.credentials)

    def login(self):
        user = self.create_user()
        self.client.login(**self.credentials)
        return user

    def test_donate_page(self):
        response = self.client.get("/en/donate/")
        self.assertContains(response, "/donate/new/")
        self.login()

        # Check rewards on page
        response = self.client.get("/en/donate/new/")
        self.assertContains(response, "list of supporters")

    @override_settings(PAYMENT_FAKTURACE=TEST_FAKTURACE)
    def test_service_workflow_card(self):
        self.login()
        Package.objects.create(name="community", verbose="Community support", price=0)
        Package.objects.create(name="extended", verbose="Extended support", price=42)
        response = self.client.get("/en/subscription/new/?plan=extended", follow=True)
        self.assertContains(response, "Please provide your billing")
        payment = Payment.objects.all().get()
        self.assertEqual(payment.state, Payment.NEW)
        customer_url = reverse("payment-customer", kwargs={"pk": payment.uuid})
        payment_url = reverse("payment", kwargs={"pk": payment.uuid})
        self.assertRedirects(response, customer_url)
        response = self.client.post(customer_url, TEST_CUSTOMER, follow=True)
        self.assertContains(response, "Please choose payment method")
        response = self.client.post(payment_url, {"method": "thepay-card"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("https://www.thepay.cz/demo-gate/"))

        payment.refresh_from_db()
        self.assertEqual(payment.state, Payment.PENDING)

        # Perform the payment
        complete_url = fake_payment(response.url)

        # Back to our web
        response = self.client.get(complete_url, follow=True)
        self.assertRedirects(response, "/en/user/")
        self.assertContains(response, "Thank you for your subscription")

        payment.refresh_from_db()
        self.assertEqual(payment.state, Payment.PROCESSED)

    def test_donation_workflow_card_reward(self):
        self.test_donation_workflow_card(2)

    @override_settings(PAYMENT_FAKTURACE=TEST_FAKTURACE)
    def test_donation_workflow_card(self, reward=0):
        self.login()
        response = self.client.post(
            "/en/donate/new/",
            {"recurring": "y", "amount": 10, "reward": reward},
            follow=True,
        )
        self.assertContains(response, "Please provide your billing")
        payment = Payment.objects.all().get()
        self.assertEqual(payment.state, Payment.NEW)
        customer_url = reverse("payment-customer", kwargs={"pk": payment.uuid})
        payment_url = reverse("payment", kwargs={"pk": payment.uuid})
        self.assertRedirects(response, customer_url)
        response = self.client.post(customer_url, TEST_CUSTOMER, follow=True)
        self.assertContains(response, "Please choose payment method")
        response = self.client.post(payment_url, {"method": "thepay-card"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("https://www.thepay.cz/demo-gate/"))

        payment.refresh_from_db()
        self.assertEqual(payment.state, Payment.PENDING)

        # Perform the payment
        complete_url = fake_payment(response.url)

        # Back to our web
        response = self.client.get(complete_url, follow=True)
        donation = Donation.objects.all().get()
        if reward:
            redirect_url = "/en/donate/edit/{}/".format(donation.pk)
        else:
            redirect_url = "/en/user/"
        self.assertRedirects(response, redirect_url)
        self.assertContains(response, "Thank you for your donation")

        payment.refresh_from_db()
        self.assertEqual(payment.state, Payment.PROCESSED)

        # Manual renew
        response = self.client.post(
            reverse("donate-pay", kwargs={"pk": donation.pk}), follow=True
        )
        renew = Payment.objects.exclude(pk=payment.pk).get()
        self.assertEqual(renew.state, Payment.NEW)
        self.assertContains(response, "Please choose payment method")

        response = self.client.post(
            reverse("payment", kwargs={"pk": renew.uuid}), {"method": "thepay-card"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("https://www.thepay.cz/demo-gate/"))

        renew.refresh_from_db()
        self.assertEqual(renew.state, Payment.PENDING)

        # Perform the payment
        complete_url = fake_payment(response.url)

        # Back to our web
        response = self.client.get(complete_url, follow=True)
        self.assertRedirects(response, redirect_url)
        self.assertContains(response, "Thank you for your donation")

        renew.refresh_from_db()
        self.assertEqual(renew.state, Payment.PROCESSED)

    @override_settings(PAYMENT_FAKTURACE=TEST_FAKTURACE)
    def test_donation_workflow_bank(self):
        self.login()
        response = self.client.post(
            "/en/donate/new/",
            {"recurring": "y", "amount": 10, "reward": 0},
            follow=True,
        )
        self.assertContains(response, "Please provide your billing")
        payment = Payment.objects.all().get()
        self.assertEqual(payment.state, Payment.NEW)
        customer_url = reverse("payment-customer", kwargs={"pk": payment.uuid})
        payment_url = reverse("payment", kwargs={"pk": payment.uuid})
        self.assertRedirects(response, customer_url)
        response = self.client.post(customer_url, TEST_CUSTOMER, follow=True)
        self.assertContains(response, "Please choose payment method")
        response = self.client.post(payment_url, {"method": "fio-bank"}, follow=True)
        self.assertContains(response, "Payment Instructions")

        payment.refresh_from_db()
        self.assertEqual(payment.state, Payment.PENDING)

    def test_your_donations(self):
        # Check login link
        self.assertContains(self.client.get(reverse("donate")), "/sso-login/")
        user = self.login()

        # No login/donations
        response = self.client.get(reverse("donate"))
        self.assertNotContains(response, "/sso-login/")
        self.assertNotContains(response, "Your donations")

        # Donation show show up
        Donation.objects.create(
            reward=2,
            user=user,
            active=True,
            expires=timezone.now() + relativedelta(years=1),
            payment=self.create_payment()[0].pk,
        )
        self.assertContains(self.client.get(reverse("user")), "Your donations")

    def create_donation(self, years=1):
        return Donation.objects.create(
            reward=3,
            user=self.create_user(),
            active=True,
            expires=timezone.now() + relativedelta(years=years),
            payment=self.create_payment()[0].pk,
            link_url="https://example.com/weblate",
            link_text="Weblate donation test",
        )

    def test_link(self):
        self.create_donation()
        response = self.client.get("/en/thanks/", follow=True)
        self.assertContains(response, "https://example.com/weblate")
        self.assertContains(response, "Weblate donation test")

    @responses.activate
    @override_settings(
        PAYMENT_DEBUG=True, PAYMENT_REDIRECT_URL="http://example.com/payment",
    )
    def test_recurring(self):
        responses.add(
            responses.POST, "http://example.com/payment", body="",
        )
        donation = self.create_donation(-1)
        self.assertEqual(donation.payment_obj.payment_set.count(), 0)
        # The processing fails here, but new payment is created
        call_command("recurring_donations")
        self.assertEqual(donation.payment_obj.payment_set.count(), 1)
        # Flag it as paid
        donation.payment_obj.payment_set.update(state=Payment.ACCEPTED)

        # Process pending payments
        call_command("process_donations")
        old = donation.expires
        donation.refresh_from_db()
        self.assertGreater(donation.expires, old)


class PostTest(PostTestCase):
    def setUp(self):
        super().setUp()
        fake_remote()

    def test_future(self):
        past = self.create_post()
        future = self.create_post(
            "futurepost", "futurebody", timezone.now() + relativedelta(days=1)
        )
        response = self.client.get("/feed/")
        self.assertContains(response, "testpost")
        self.assertNotContains(response, "futurepost")
        response = self.client.get("/news/", follow=True)
        self.assertContains(response, "testpost")
        self.assertNotContains(response, "futurepost")
        response = self.client.get(past.get_absolute_url(), follow=True)
        self.assertContains(response, "testpost")
        self.assertContains(response, "testbody")
        response = self.client.get(future.get_absolute_url(), follow=True)
        self.assertEqual(response.status_code, 404)


class APITest(TestCase):
    databases = "__all__"

    def test_hosted(self):
        Package.objects.create(name="community", verbose="Community support", price=0)
        Package.objects.create(name="shared:test", verbose="Test package", price=0)
        response = self.client.post(
            "/api/hosted/",
            {
                "payload": dumps(
                    {
                        "billing": 42,
                        "package": "shared:test",
                        "projects": 1,
                        "languages": 1,
                        "source_strings": 1,
                        "components": 1,
                    },
                    key=settings.PAYMENT_SECRET,
                    salt="weblate.hosted",
                )
            },
            HTTP_USER_AGENT="weblate/1.2.3",
        )
        self.assertEquals(response.status_code, 200)

    def test_hosted_invalid(self):
        response = self.client.post("/api/hosted/", {"payload": dumps({}, key="dummy")})
        self.assertEquals(response.status_code, 400)

    def test_hosted_missing(self):
        response = self.client.post("/api/hosted/")
        self.assertEquals(response.status_code, 400)
