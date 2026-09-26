"""Verify packaged web assets without a database or exchange connection."""

import unittest

from quantitative_trading.dashboard import app


class DashboardAssetsTests(unittest.TestCase):
    def test_page_and_external_assets_are_served(self):
        client = app.test_client()
        with client.get("/") as page:
            self.assertEqual(page.status_code, 200)
            self.assertIn(b"/assets/app.js", page.data)
        for path in ("/assets/app.js", "/assets/styles.css"):
            with self.subTest(path=path):
                with client.get(path) as response:
                    self.assertEqual(response.status_code, 200)
                    self.assertGreater(len(response.data), 100)

    def test_invalid_symbol_is_rejected_before_database_access(self):
        response = app.test_client().get("/api/dashboard?symbol=INVALID")
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
