import json, os, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup

ASIN = "B0HJ75X3PN"
PRODUCT_URL = f"https://www.amazon.co.jp/dp/{ASIN}"
OFFERS_URL = f"https://www.amazon.co.jp/gp/offer-listing/{ASIN}"
STATUS_PATH = Path("docs/status.json")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "").strip()
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.7",
}

def fetch(url):
    response = requests.get(url, headers=HEADERS, timeout=25)
    response.raise_for_status()
    return response.text

def clean(value):
    return re.sub(r"\\s+", " ", value or "").strip()

def yen(value):
    match = re.search(r"[￥¥]\\s*([\\d,]+)", value or "")
    return "¥" + match.group(1) if match else ""

def blocked(soup, html):
    text = clean(soup.get_text(" ", strip=True)).lower()
    return any(token in text for token in (
        "robot check", "ロボット", "captcha", "enter the characters you see below",
        "sorry, we just need to make sure you're not a robot"
    )) or "api-services-support@amazon.com" in html.lower()

def positive_stock(text):
    return ("在庫あり" in text or "残りわずか" in text
            or bool(re.search(r"残り\\s*\\d+\\s*点", text))
            or bool(re.search(r"通常\\s*\\d+.*以内に発送", text)))

def negative_stock(text):
    return any(token in text for token in ("現在在庫切れ", "一時的に在庫切れ", "在庫切れ", "入荷未定"))

def seller_from(block):
    for selector in ("a.a-size-small.a-link-normal", "#sellerProfileTriggerId",
                     ".a-color-secondary a", "a[href*='seller=']"):
        element = block.select_one(selector)
        if element:
            value = clean(element.get_text(" ", strip=True))
            if value and len(value) < 100:
                return value
    text = clean(block.get_text(" ", strip=True))
    match = re.search(r"(?:販売元|出品者)[:：]\\s*([^|]{2,70})", text)
    return clean(match.group(1)) if match else "賣家未能辨識"

def parse_offers(html):
    soup = BeautifulSoup(html, "html.parser")
    if blocked(soup, html):
        return [], "captcha"
    offers = []
    blocks = soup.select("#aod-offer, .olpOffer, div[data-csa-c-content-id*='offer']")
    for block in blocks:
        text = clean(block.get_text(" ", strip=True))
        if not text:
            continue
        availability = " ".join(
            clean(el.get_text(" ", strip=True))
            for el in block.select(".aod-delivery-promise, .aod-availability, .olpAvailability, #aod-offer-shipsFrom")
        )
        signal = clean(availability + " " + text)
        if positive_stock(signal) and not negative_stock(signal):
            offers.append({
                "seller": seller_from(block), "price": yen(text) or "價格未辨識",
                "source": "offer-listing", "snippet": text[:240]
            })
    return offers, "ok"

def main():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    try:
        previous = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        previous = {}

    result = {
        "asin": ASIN, "product_url": PRODUCT_URL, "checked_at": now,
        "status": "unknown", "label": "無法確認", "amazon_direct": "unknown",
        "offers": [], "taiwan_shipping": "需登入 Amazon 並以台灣地址結帳確認", "message": ""
    }
    try:
        product_html = fetch(PRODUCT_URL)
        soup = BeautifulSoup(product_html, "html.parser")
        if blocked(soup, product_html):
            raise RuntimeError("Amazon 商品頁回傳 CAPTCHA / Robot Check")
        title_el = soup.select_one("#productTitle")
        title = clean(title_el.get_text(" ", strip=True)) if title_el else ""
        if title and "BX-53" not in title.upper():
            raise RuntimeError("商品標題未能確認為 BX-53，停止判讀以避免監控錯商品")
        result["title"] = title or "BX-53（標題未讀取）"

        availability = soup.select_one("#availability")
        buybox = soup.select_one("#desktop_buybox, #buybox, #tabular-buybox")
        full = clean((availability.get_text(" ", strip=True) if availability else "") + " "
                     + (buybox.get_text(" ", strip=True) if buybox else ""))
        price_el = soup.select_one("#corePrice_feature_div .a-offscreen, #priceblock_ourprice, #priceblock_dealprice")
        direct_price = clean(price_el.get_text(" ", strip=True)) if price_el else yen(full)
        seller_el = soup.select_one("#sellerProfileTriggerId, #merchant-info")
        direct_seller = clean(seller_el.get_text(" ", strip=True)) if seller_el else ""
        if positive_stock(full) and not negative_stock(full):
            if "Amazon.co.jp" in direct_seller or (buybox and "Amazon.co.jp" in buybox.get_text(" ", strip=True)):
                result["amazon_direct"] = "possible"
                result["offers"].append({"seller": "Amazon.co.jp（頁面辨識）",
                    "price": direct_price or "價格未辨識", "source": "product-page", "snippet": full[:220]})
            elif direct_seller or direct_price:
                result["offers"].append({"seller": direct_seller or "賣家未能辨識",
                    "price": direct_price or "價格未辨識", "source": "product-page", "snippet": full[:220]})

        offers, offer_status = parse_offers(fetch(OFFERS_URL))
        if offer_status == "captcha" and not result["offers"]:
            raise RuntimeError("Amazon 出品列表回傳 CAPTCHA / Robot Check")
        seen = {(o["seller"], o["price"]) for o in result["offers"]}
        for offer in offers:
            key = (offer["seller"], offer["price"])
            if key not in seen:
                result["offers"].append(offer)
                seen.add(key)

        if result["offers"]:
            result["status"], result["label"] = "in_stock", "找到可能可購買的出品"
        elif negative_stock(full):
            result["status"], result["label"] = "out_of_stock", "目前頁面顯示缺貨"
        else:
            result["status"], result["label"] = "unknown", "頁面未提供足夠庫存訊號"
        result["message"] = "僅依公開頁面判讀；請點商品頁確認賣家、庫存及台灣配送。"
    except Exception as error:
        result["status"], result["label"] = "unknown", "無法確認"
        result["message"] = str(error)

    old_status = previous.get("status")
    old_sig = sorted((o.get("seller", ""), o.get("price", "")) for o in previous.get("offers", []))
    new_sig = sorted((o.get("seller", ""), o.get("price", "")) for o in result["offers"])
    notify, title, body = False, "BX-53 監控更新", ""
    if result["status"] == "in_stock" and old_status != "in_stock":
        notify, title = True, "BX-53 可能補貨！"
        body = "\\n".join(f'{o["seller"]}｜{o["price"]}' for o in result["offers"][:5])
    elif result["status"] == "in_stock" and old_status == "in_stock" and new_sig != old_sig:
        notify, title = True, "BX-53 價格／賣家變動"
        body = "\\n".join(f'{o["seller"]}｜{o["price"]}' for o in result["offers"][:5])
    elif result["status"] == "out_of_stock" and old_status == "in_stock":
        notify, title, body = True, "BX-53 可能再次缺貨", "目前商品頁顯示缺貨。"

    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if notify and NTFY_TOPIC:
        try:
            requests.post("https://ntfy.sh/" + quote(NTFY_TOPIC, safe=""),
                data=(body + "\\n\\n" + PRODUCT_URL).encode("utf-8"),
                headers={"Title": title, "Priority": "urgent" if result["status"] == "in_stock" else "default",
                         "Click": PRODUCT_URL, "Tags": "shopping_bags"}, timeout=15).raise_for_status()
        except Exception as error:
            print("ntfy publish failed:", error)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
