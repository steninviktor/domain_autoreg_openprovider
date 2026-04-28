import unittest

from domain_autoreg.domain import parse_domain


class DomainParsingTest(unittest.TestCase):
    def test_parse_domain_splits_name_and_extension(self):
        parsed = parse_domain("Example.COM")

        self.assertEqual(parsed.fqdn, "example.com")
        self.assertEqual(parsed.name, "example")
        self.assertEqual(parsed.extension, "com")

    def test_parse_domain_rejects_invalid_domain(self):
        with self.assertRaises(ValueError):
            parse_domain("localhost")


if __name__ == "__main__":
    unittest.main()
