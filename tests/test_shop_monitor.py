import unittest
from bs4 import BeautifulSoup
import shop_monitor


class ShopMonitorTests(unittest.TestCase):
    def test_clean_collapses_whitespace(self):
        self.assertEqual(shop_monitor.clean(" BX-53\\n在庫あり\\t¥ 7,480 "), "BX-53 在庫あり ¥ 7,480")

    def test_structured_availability_reads_nested_product(self):
        html = """
        <script type="application/ld+json">
        {"@type":"Product","offers":{"@type":"Offer","availability":"https://schema.org/InStock"}}
        </script>
        """
        soup = BeautifulSoup(html, "html.parser")
        self.assertEqual(shop_monitor.structured_availability(soup), ["instock"])

    def test_blocked_short_response_is_rejected(self):
        soup = BeautifulSoup("<html><body>ok</body></html>", "html.parser")
        self.assertTrue(shop_monitor.is_blocked(soup, "<html><body>ok</body></html>"))

    def test_stock_classification_keeps_unknown_when_no_signal(self):
        # The production parser must not infer stock from generic cart wording.
        source = next(item for item in shop_monitor.SOURCES if item["id"] == "bic")
        self.assertNotIn("カートに入れる", source["positive"])
        self.assertNotIn("購入する", source["positive"])


if __name__ == "__main__":
    unittest.main()
