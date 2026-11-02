import unittest
from unittest.mock import patch
from bs4 import BeautifulSoup
import shop_monitor


class ShopMonitorTests(unittest.TestCase):
    def test_clean_collapses_real_whitespace(self):
        self.assertEqual(
            shop_monitor.clean(" BX-53\n在庫あり\t¥ 7,480 "),
            "BX-53 在庫あり ¥ 7,480",
        )

    def test_structured_availability_reads_nested_product(self):
        html = """
        <script type="application/ld+json">
        {"@type":"Product","offers":{"@type":"Offer","availability":"https://schema.org/InStock"}}
        </script>
        """
        soup = BeautifulSoup(html, "html.parser")
        self.assertEqual(shop_monitor.structured_availability(soup), ["instock"])

    def test_blocked_short_response_is_rejected(self):
        html = "<html><body>ok</body></html>"
        soup = BeautifulSoup(html, "html.parser")
        self.assertTrue(shop_monitor.is_blocked(soup, html))

    def test_all_browser_fallback_sources_are_configured(self):
        expected = {"bic", "yodobashi", "rakuten_kenbill", "rakuten_premoa", "rakuten_sakura"}
        self.assertEqual(set(shop_monitor.BROWSER_FALLBACK_IDS), expected)
        configured = {source["id"] for source in shop_monitor.SOURCES}
        self.assertTrue(expected.issubset(configured))

    def test_stock_classification_keeps_unknown_when_no_signal(self):
        source = next(item for item in shop_monitor.SOURCES if item["id"] == "bic")
        self.assertNotIn("カートに入れる", source["positive"])
        self.assertNotIn("購入する", source["positive"])

    @patch("shop_monitor.requests.post")
    def test_restock_notification_uses_real_newlines(self, post):
        original_topic = shop_monitor.TOPIC
        shop_monitor.TOPIC = "unit-test-topic"
        post.return_value.raise_for_status.return_value = None
        try:
            shop_monitor.notify_restock({
                "name": "Bic Camera",
                "price": "¥7,480",
                "url": "https://example.com/bx-53",
                "matched_keyword": "在庫あり",
            })
        finally:
            shop_monitor.TOPIC = original_topic
        payload = post.call_args.kwargs["data"].decode("utf-8")
        self.assertIn("\n", payload)
        self.assertNotIn("\\n", payload)


if __name__ == "__main__":
    unittest.main()
