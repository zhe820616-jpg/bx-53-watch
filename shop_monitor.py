import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

TOPIC = os.getenv("NTFY_TOPIC", "").strip()
BROWSER_FALLBACK_IDS = ("bic", "yodobashi", "rakuten_kenbill", "rakuten_premoa", "rakuten_sakura")
PATH = Path("docs/shop-status.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
SOURCES = [
    {"id":"bic","name":"Bic Camera","url":"https://www.biccamera.com/bc/item/15605654/",
     "identity":["bx-53","4904810073734"],"positive":["在庫あり","在庫有り","在庫残少","残りわずか"],
     "negative":["予約受付は終了","予約受付終了","この商品はご購入できません","ご購入できません","販売休止中","在庫切れ","在庫なし"]},
    {"id":"yodobashi","name":"Yodobashi","url":"https://www.yodobashi.com/product/100000001010200995/",
     "identity":["bx-53","4904810073734"],"positive":["在庫あり","在庫残少","残少","在庫わずか"],
     "negative":["販売を終了しました","販売休止中","在庫なし","在庫切れ","販売終了"]},
    {"id":"hlj","name":"HobbyLink Japan","url":"https://www.hlj.co.jp/product/TKT07373",
     "identity":["bx-53","tkt07373","4904810073734"],"positive":["in stock","available now","在庫あり"],
     "negative":["out of stock","temporarily out of stock","backordered","order stop","discontinued","在庫なし","売り切れ"]},
    {"id":"rakuten_kenbill","name":"Rakuten kenbill-2","url":"https://item.rakuten.co.jp/kenbill-2/4904810073734/",
     "identity":["bx-53","4904810073734"],"positive":["在庫あり","在庫有り","在庫残少","残りわずか","残り僅か"],
     "negative":["売り切れ","売り切れました","在庫切れ","在庫なし","販売期間外","販売期間が終了"]},
    {"id":"rakuten_premoa","name":"Rakuten PREMOA","url":"https://item.rakuten.co.jp/premoa/4904810073734/",
     "identity":["bx-53","4904810073734"],"positive":["在庫あり","在庫有り","在庫残少","残りわずか","残り僅か"],
     "negative":["売り切れ","売り切れました","在庫切れ","在庫なし","販売期間外","販売期間が終了"]},
    {"id":"rakuten_sakura","name":"Rakuten トイランドクローバー","url":"https://item.rakuten.co.jp/sakurayashouten/4904810073734/",
     "identity":["bx-53","4904810073734"],"positive":["在庫あり","在庫有り","在庫残少","残りわずか","残り僅か"],
     "negative":["売り切れ","売り切れました","在庫切れ","在庫なし","販売期間外","販売期間が終了"]},
]

def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()

def structured_availability(soup, identity_tokens=None):
    # Ignore stock signals from recommended products and ads.
    values = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key.lower() == "availability" and isinstance(value, str):
                    values.append(value.rsplit("/", 1)[-1].lower())
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    def products(node):
        if isinstance(node, dict):
            node_type = node.get("@type", [])
            types = node_type if isinstance(node_type, list) else [node_type]
            if any(str(value).lower() == "product" for value in types):
                yield node
            for value in node.values():
                yield from products(value)
        elif isinstance(node, list):
            for value in node:
                yield from products(value)

    tokens = [str(token).lower() for token in (identity_tokens or [])]
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        if not tokens:
            walk(data)
            continue
        for product in products(data):
            identity = " ".join(str(product.get(key, "")) for key in
                                ("name", "sku", "mpn", "gtin", "gtin13", "gtin14", "url")).lower()
            if any(token in identity for token in tokens):
                walk(product)
    return values

def is_blocked(soup, html):
    text = clean(soup.get_text(" ", strip=True)).lower()
    markers = ("robot check", "captcha", "アクセスが集中", "ただいまアクセス", "リクエストをブロック",
               "access denied", "attention required", "cloudflare")
    return any(marker in text for marker in markers) or len(html) < 500

def relevant_text(soup):
    # Restrict stock matching to the product page's main content where possible.
    candidates = []
    for selector in ("main", "#main", "#contents", "#container", ".productDetail", ".product-detail",
                     "#productDetails", ".product"):
        for node in soup.select(selector)[:2]:
            text = clean(node.get_text(" ", strip=True))
            if len(text) > 80:
                candidates.append(text)
    if candidates:
        return max(candidates, key=len)
    return clean(soup.get_text(" ", strip=True))

def active_purchase_controls(soup):
    """Detect enabled purchase controls in the primary product content only."""
    scopes = []
    for selector in ("main", "#main", "#contents", "#container", ".productDetail",
                     ".product-detail", "#productDetails", ".product"):
        scopes.extend(soup.select(selector)[:2])
    scope = max(scopes, key=lambda node: len(node.get_text(" ", strip=True))) if scopes else soup
    words = ("カートに入れる", "買い物かごに入れる", "今すぐ買う", "注文する")
    matches = []
    for element in scope.select("button, input[type='submit'], input[type='button'], [role='button']"):
        label = clean(" ".join((element.get_text(" ", strip=True),
                                str(element.get("aria-label", "")),
                                str(element.get("title", "")),
                                str(element.get("value", "")))))
        word = next((item for item in words if item in label), None)
        if not word:
            continue
        classes = " ".join(element.get("class", [])).lower()
        disabled = (element.has_attr("disabled")
                    or str(element.get("aria-disabled", "")).lower() == "true"
                    or "disabled" in classes or "soldout" in classes)
        if not disabled:
            matches.append(word)
    return list(dict.fromkeys(matches))


def get_status(source):
    last_error = None
    referer = {
        "bic":"https://www.biccamera.com/", "yodobashi":"https://www.yodobashi.com/",
        "rakuten_kenbill":"https://www.rakuten.co.jp/", "rakuten_premoa":"https://www.rakuten.co.jp/",
        "rakuten_sakura":"https://www.rakuten.co.jp/", "hlj":"https://www.hlj.co.jp/",
    }[source["id"]]
    response = None
    html = ""
    content_type = ""
    fetch_method = "requests"
    with requests.Session() as session:
        for attempt in range(2):
            try:
                response = session.get(source["url"], headers={**HEADERS, "Referer":referer},
                                       timeout=(8, 15), allow_redirects=True)
                response.raise_for_status()
                html = response.text
                content_type = response.headers.get("Content-Type", "").lower()
                if "html" in content_type and len(html) >= 500 and not is_blocked(
                        BeautifulSoup(html, "html.parser"), html):
                    break
                last_error = ValueError("requests 回傳非完整商品頁或驗證頁")
                response = None
            except requests.RequestException as error:
                last_error = error
                response = None
            if attempt == 0:
                time.sleep(2)

    # Bic Camera, Yodobashi, and Rakuten product pages may block plain HTTP or need browser rendering.
    # Use Chromium as a fallback for these sources; this does not bypass CAPTCHA or access controls.
    if response is None and source["id"] in BROWSER_FALLBACK_IDS and sync_playwright:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox", "--disable-http2"])
            try:
                page = browser.new_page(
                    user_agent=HEADERS["User-Agent"],
                    locale="ja-JP",
                    extra_http_headers={"Accept-Language": HEADERS["Accept-Language"]},
                )
                navigation_warning = ""
                navigation_response = None
                # Do not wait indefinitely for analytics/ads or a stalled DOMContentLoaded event.
                # "commit" returns as soon as response headers arrive; the DOM can still be
                # inspected even if the subsequent load-state wait times out.
                try:
                    navigation_response = page.goto(
                        source["url"], wait_until="commit", timeout=25000
                    )
                except Exception as error:
                    navigation_warning = f"navigation commit warning: {str(error)[:180]}"
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=8000)
                except Exception as error:
                    warning = f"DOMContentLoaded wait timed out: {str(error)[:140]}"
                    navigation_warning = (navigation_warning + "; " + warning).strip("; ")
                page.wait_for_timeout(1500)
                html = page.content()
                content_type = "text/html; browser-rendered"
                fetch_method = "playwright"
                if len(html) < 500:
                    raise ValueError(
                        "瀏覽器取得的頁面內容過短；" + (navigation_warning or "頁面未載入")
                    )
            finally:
                browser.close()
    elif response is None:
        raise last_error or RuntimeError("無法取得商品頁")

    soup = BeautifulSoup(html, "html.parser")
    title = clean(soup.title.get_text(" ", strip=True)) if soup.title else ""
    if "html" not in content_type or is_blocked(soup, html):
        final_url = response.url if response is not None else source["url"]
        status_code = response.status_code if response is not None else "browser"
        preview = clean(soup.get_text(" ", strip=True))[:180]
        raise ValueError(
            f"無效／受阻回應：HTTP={status_code}, Content-Type={content_type or 'unknown'}, "
            f"bytes={len(html.encode('utf-8'))}, final_url={final_url}, preview={preview!r}"
        )
    body = relevant_text(soup)
    final_url = response.url if response is not None else source["url"]
    identity_blob = (title + " " + body + " " + final_url).lower()
    if not any(token in identity_blob for token in source["identity"]):
        raise ValueError("頁面未能確認為 BX-53 商品，停止庫存判讀")
    lower = body.lower()
    negative = next((word for word in source["negative"] if word.lower() in lower), None)
    positive = next((word for word in source["positive"] if word.lower() in lower), None)
    availability = structured_availability(soup, source['identity'])
    schema_out = next((v for v in availability if v in ("outofstock","soldout","discontinued")), None)
    schema_in = next((v for v in availability if v in ("instock","limitedavailability")), None)

    purchase_controls = active_purchase_controls(soup)
    if (negative or schema_out) and purchase_controls:
        status, matched = "unknown", "庫存文字與可購買按鈕訊號衝突"
    elif negative or schema_out:
        status, matched = "out_of_stock", negative or "schema:" + schema_out
    elif purchase_controls:
        status, matched = "in_stock", "enabled_button:" + purchase_controls[0]
    elif schema_in:
        status, matched = "in_stock", "schema:" + schema_in
    elif positive:
        status, matched = "in_stock", positive
    else:
        status, matched = "unknown", ""

    price_match = re.search(r"[￥¥]\s*[0-9,]+", body)
    return {
        "id":source["id"], "name":source["name"], "url":source["url"],
        "status":status,
        "label":{"in_stock":"可能有貨（請點頁面確認）","out_of_stock":"缺貨／停止販售",
                 "unknown":"無法確認（未找到明確庫存訊號）"}[status],
        "price":price_match.group(0) if price_match else "", "matched_keyword":matched,
        "http_status":response.status_code if response is not None else 200, "content_type":content_type,
        "fetch_method":fetch_method, "content_length":len(html.encode("utf-8")), "page_title":title[:180],
        "checked_at":now(),
    }

def failed_result(source, error):
    return {"id":source["id"],"name":source["name"],"url":source["url"],
            "status":"unknown","label":"無法確認（讀取／驗證失敗）","price":"",
            "error":str(error)[:500],"checked_at":now()}

def notify_restock(item):
    if not TOPIC:
        return
    message = (f'{item["name"]}：{item.get("price") or "價格未辨識"}\n'
               f'{item["url"]}\n辨識訊號：{item.get("matched_keyword", "")}\n請開啟商品頁確認庫存。')
    response = requests.post("https://ntfy.sh/" + quote(TOPIC, safe=""),
        data=message.encode("utf-8"),
        headers={"Title":"BX-53 日本通路可能補貨","Click":item["url"],"Priority":"high"},
        timeout=(5,10))
    response.raise_for_status()

def main():
    try:
        old = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        old = {}
    previous = {item.get("id"):item for item in old.get("sources",[]) if isinstance(item,dict)}
    results_by_id = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(get_status, source):source for source in SOURCES}
        for future in as_completed(futures):
            source = futures[future]
            try:
                results_by_id[source["id"]] = future.result()
            except Exception as error:
                results_by_id[source["id"]] = failed_result(source,error)
    results = [results_by_id[source["id"]] for source in SOURCES]
    alerts = [item for item in results
              if item["status"] == "in_stock"
              and previous.get(item["id"],{}).get("status") != "in_stock"
              and item.get("matched_keyword")]

    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps({
        "product":"BX-53 All-in-One Set","checked_at":now(),"sources":results,
        "summary":{"in_stock":sum(x["status"]=="in_stock" for x in results),
                   "out_of_stock":sum(x["status"]=="out_of_stock" for x in results),
                   "unknown":sum(x["status"]=="unknown" for x in results)},
        "note":"只在確認頁面為 BX-53 後判讀；優先使用商品主內容及結構化庫存資料；unknown 不代表缺貨。"
    },ensure_ascii=False,indent=2),encoding="utf-8")

    for item in alerts:
        try:
            notify_restock(item)
        except requests.RequestException as error:
            print("ntfy publish failed for",item["id"],str(error))
    print(json.dumps(results,ensure_ascii=False))

if __name__ == "__main__":
    main()
