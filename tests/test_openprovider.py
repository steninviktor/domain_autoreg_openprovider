import unittest

from domain_autoreg.config import OpenproviderConfig, RegistrationConfig
from domain_autoreg.domain import parse_domain
from domain_autoreg.openprovider import OpenproviderClient, build_check_payload, build_create_payload


class OpenproviderPayloadTest(unittest.TestCase):
    def test_client_uses_configured_timeout(self):
        client = OpenproviderClient(
            OpenproviderConfig(
                username="user",
                password="secret",
                timeout_seconds=90,
            )
        )

        self.assertEqual(client.timeout_seconds, 90)

    def test_build_check_payload_batches_domains_with_price(self):
        payload = build_check_payload([parse_domain("example.com")])

        self.assertEqual(payload["with_price"], True)
        self.assertEqual(payload["domains"], [{"name": "example", "extension": "com"}])

    def test_build_create_payload_includes_registration_profile(self):
        domain = parse_domain("example.com")
        profile = RegistrationConfig(
            enabled=True,
            period=1,
            autorenew="default",
            owner_handle="OWNER",
            admin_handle="ADMIN",
            tech_handle="TECH",
            billing_handle="BILL",
            ns_group="default",
        )

        payload = build_create_payload(
            domain,
            profile,
            check_result={"is_premium": False, "price": {"reseller": {"price": 10.0, "currency": "USD"}}},
        )

        self.assertEqual(payload["domain"], {"name": "example", "extension": "com"})
        self.assertEqual(payload["owner_handle"], "OWNER")
        self.assertEqual(payload["ns_group"], "default")

    def test_build_create_payload_accepts_known_premium_fee_within_price_limit(self):
        domain = parse_domain("premium.com")
        profile = RegistrationConfig(
            enabled=True,
            period=1,
            autorenew="default",
            owner_handle="OWNER",
            admin_handle="ADMIN",
            tech_handle="TECH",
            billing_handle="BILL",
        )
        check_result = {
            "is_premium": True,
            "price": {"reseller": {"price": 19.99, "currency": "EUR"}},
            "premium": {"currency": "USD", "price": {"create": 19.99}},
        }

        payload = build_create_payload(domain, profile, check_result)

        self.assertEqual(payload["accept_premium_fee"], 19.99)

    def test_build_create_payload_rejects_regular_domain_without_reseller_price(self):
        domain = parse_domain("product-only.cz")
        profile = RegistrationConfig(
            enabled=True,
            period=1,
            autorenew="default",
            owner_handle="OWNER",
            admin_handle="ADMIN",
            tech_handle="TECH",
            billing_handle="BILL",
        )
        check_result = {
            "is_premium": False,
            "price": {"product": {"price": 4.0, "currency": "EUR"}},
        }

        with self.assertRaises(ValueError):
            build_create_payload(domain, profile, check_result)

    def test_build_create_payload_rejects_premium_domain_without_reseller_price(self):
        domain = parse_domain("premium.com")
        profile = RegistrationConfig(
            enabled=True,
            period=1,
            autorenew="default",
            owner_handle="OWNER",
            admin_handle="ADMIN",
            tech_handle="TECH",
            billing_handle="BILL",
        )
        check_result = {
            "is_premium": True,
            "premium": {"currency": "USD", "price": {"create": 19.99}},
        }

        with self.assertRaises(ValueError):
            build_create_payload(domain, profile, check_result)

    def test_build_create_payload_rejects_regular_domain_above_price_limit(self):
        domain = parse_domain("expensive.com")
        profile = RegistrationConfig(
            enabled=True,
            period=1,
            autorenew="default",
            owner_handle="OWNER",
            admin_handle="ADMIN",
            tech_handle="TECH",
            billing_handle="BILL",
        )
        check_result = {
            "is_premium": False,
            "price": {"reseller": {"price": 21.0, "currency": "USD"}},
        }

        with self.assertRaises(ValueError):
            build_create_payload(domain, profile, check_result)

    def test_build_create_payload_rejects_premium_domain_above_price_limit(self):
        domain = parse_domain("premium.com")
        profile = RegistrationConfig(
            enabled=True,
            period=1,
            autorenew="default",
            owner_handle="OWNER",
            admin_handle="ADMIN",
            tech_handle="TECH",
            billing_handle="BILL",
        )
        check_result = {
            "is_premium": True,
            "premium": {"currency": "USD", "price": {"create": 21.0}},
        }

        with self.assertRaises(ValueError):
            build_create_payload(domain, profile, check_result)

    def test_build_create_payload_rejects_missing_regular_price(self):
        domain = parse_domain("unknown-price.com")
        profile = RegistrationConfig(
            enabled=True,
            period=1,
            autorenew="default",
            owner_handle="OWNER",
            admin_handle="ADMIN",
            tech_handle="TECH",
            billing_handle="BILL",
        )

        with self.assertRaises(ValueError):
            build_create_payload(domain, profile, {"is_premium": False})

    def test_build_create_payload_rejects_unknown_premium_fee(self):
        domain = parse_domain("premium.com")
        profile = RegistrationConfig(
            enabled=True,
            period=1,
            autorenew="default",
            owner_handle="OWNER",
            admin_handle="ADMIN",
            tech_handle="TECH",
            billing_handle="BILL",
        )

        with self.assertRaises(ValueError):
            build_create_payload(domain, profile, {"is_premium": True, "premium": {}})


if __name__ == "__main__":
    unittest.main()
