import unittest
from unittest.mock import Mock, patch
import validation_monitor


class ValidationMonitorTests(unittest.TestCase):
    def test_all_targets_are_separate_from_bx53(self):
        for target in validation_monitor.TARGETS:
            self.assertNotIn("BX-53", target["url"].upper())
            self.assertTrue(target["identity"])
    def test_clean_collapses_whitespace(self):
        self.assertEqual(validation_monitor.clean("BX-53\n  在庫あり\t"), "BX-53 在庫あり")

    @patch("validation_monitor.requests.get")
    def test_explicit_stock_and_identity_pass(self, get):
        html = "<html><head><title>BEYBLADE X 1巻</title></head><body>在庫あり " + ("商品説明 " * 100) + "</body></html>"
        response = Mock(status_code=200, text=html, content=html.encode(),
                        headers={"Content-Type": "text/html; charset=utf-8"},
                        url="https://www.biccamera.com/bc/item/12189630/")
        response.raise_for_status.return_value = None
        get.return_value = response
        result = validation_monitor.check(validation_monitor.TARGETS[0])
        self.assertTrue(result["passed"])

    @patch("validation_monitor.requests.get")
    def test_wrong_identity_does_not_pass_even_if_stock_text_exists(self, get):
        html = "<html><head><title>Different item</title></head><body>在庫あり " + ("商品説明 " * 100) + "</body></html>"
        response = Mock(status_code=200, text=html, content=html.encode(),
                        headers={"Content-Type": "text/html"},
                        url="https://example.com/")
        response.raise_for_status.return_value = None
        get.return_value = response
        result = validation_monitor.check(validation_monitor.TARGETS[0])
        self.assertFalse(result["passed"])
        self.assertEqual(result["reason"], "expected page identity missing")

    @patch("validation_monitor.requests.get")
    def test_captcha_does_not_pass(self, get):
        html = "<html><head><title>Robot Check</title></head><body>CAPTCHA</body></html>"
        response = Mock(status_code=200, text=html, content=html.encode(),
                        headers={"Content-Type": "text/html"},
                        url="https://example.com/")
        response.raise_for_status.return_value = None
        get.return_value = response
        result = validation_monitor.check(validation_monitor.TARGETS[0])
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
