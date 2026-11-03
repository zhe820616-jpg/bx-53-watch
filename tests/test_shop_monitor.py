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
        {"@type":"Product","name":"Beyblade X BX-53","sku":"BX-53","offers":{"@type":"Offer","availability":"https://schema.org/OutOfStock"}}
        </script>
        """
        soup = BeautifulSoup(html, "html.parser")
        self.assertEqual(shop_monitor.structured_availability(soup, ["bx-53"]), ["outofstock"])

    def test_recommendation_product_stock_is_ignored(self):
        html = """
        <script type="application/ld+json">
        {"@graph":[
          {"@type":"Product","name":"Beyblade X BX-53","sku":"BX-53",
           "offers":{"availability":"https://schema.org/OutOfStock"}},
          {"@type":"Product","name":"Other Beyblade","sku":"BX-99",
           "offers":{"availability":"https://schema.org/InStock"}}
        ]}
        </script>
        """
        soup = BeautifulSoup(html, "html.parser")
        self.assertEqual(shop_monitor.structured_availability(soup, ["bx-53"]), ["outofstock"])

    def test_enabled_add_to_cart_button_is_detected(self):
        html = """<main><h1>BX-53</h1><button>カートに入れる</button></main>"""
        soup = BeautifulSoup(html, "html.parser")
        self.assertEqual(shop_monitor.active_purchase_controls(soup, {"id": "bic"}), ["カートに入れる"])

    def test_disabled_add_to_cart_button_is_not_detected(self):
        html = """<main><h1>BX-53</h1><button disabled>カートに入れる</button></main>"""
        soup = BeautifulSoup(html, "html.parser")
        self.assertEqual(shop_monitor.active_purchase_controls(soup, {"id": "bic"}), [])

    def test_retailer_specific_purchase_button_labels(self):
        cases = [
            ("yodobashi", "ショッピングカートに入れる"),
            ("hlj", "Add to Cart"),
            ("rakuten_kenbill", "買い物かごに入れる"),
        ]
        for source_id, label in cases:
            with self.subTest(source=source_id):
                soup = BeautifulSoup(f"<main><h1>BX-53</h1><button>{label}</button></main>", "html.parser")
                self.assertEqual(
                    shop_monitor.active_purchase_controls(soup, {"id": source_id}),
                    [label.lower()],
                )

    def test_recommendation_button_outside_main_product_is_ignored(self):
        html = """<main><h1>BX-53</h1><p>在庫なし</p></main>
                  <aside><button>カートに入れる</button></aside>"""
        soup = BeautifulSoup(html, "html.parser")
        self.assertEqual(shop_monitor.active_purchase_controls(soup, {"id": "bic"}), [])

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
