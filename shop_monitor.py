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

TOPIC = os.getenv("NTFY_TOPIC", "").strip()
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
]

def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def clean(value):
    return re.sub(r"\\s+", " ", value or "").strip()

def structured_availability(soup):
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
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            walk(json.loads(script.string or script.get_text()))
        except (json.JSONDecodeError, TypeError):
            continue
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

def get_status(source):
    last_error = None
    referer = {
        "bic":"https://www.biccamera.com/", "yodobashi":"https://www.yodobashi.com/",
        "rakuten_kenbill":"https://www.rakuten.co.jp/", "hlj":"https://www.hlj.co.jp/",
    }[source["id"]]
    with requests.Session() as session:
        for attempt in range(3):
            try:
                response = session.get(source["url"], headers={**HEADERS, "Referer":referer},
                                       timeout=(10, 25), allow_redirects=True)
                response.raise_for_status()
                break
            except requests.RequestException as error:
                last_error = error
                if attempt < 2:
                    time.sleep(2 ** (attempt + 1))
        else:
            raise last_error

    content_type = response.headers.get("Content-Type", "").lower()
    soup = BeautifulSoup(response.text, "html.parser")
    title = clean(soup.title.get_text(" ", strip=True)) if soup.title else ""
    if "html" not in content_type or is_blocked(soup, response.text):
        raise ValueError("回應不是有效商品 HTML，或網站回傳封鎖／驗證頁")
    body = relevant_text(soup)
    identity_blob = (title + " " + body + " " + response.url).lower()
    if not any(token in identity_blob for token in source["identity"]):
        raise ValueError("頁面未能確認為 BX-53 商品，停止庫存判讀")
    lower = body.lower()
    negative = next((word for word in source["negative"] if word.lower() in lower), None)
    positive = next((word for word in source["positive"] if word.lower() in lower), None)
    availability = structured_availability(soup)
    schema_out = next((v for v in availability if v in ("outofstock","soldout","discontinued")), None)
    schema_in = next((v for v in availability if v in ("instock","limitedavailability")), None)

    if negative or schema_out:
        status, matched = "out_of_stock", negative or "schema:" + schema_out
    elif schema_in:
        status, matched = "in_stock", "schema:" + schema_in
    elif positive:
        status, matched = "in_stock", positive
    else:
        status, matched = "unknown", ""

    price_match = re.search(r"[￥¥]\\s*[0-9,]+", body)
    return {
        "id":source["id"], "name":source["name"], "url":source["url"],
        "status":status,
        "label":{"in_stock":"可能有貨（請點頁面確認）","out_of_stock":"缺貨／停止販售",
                 "unknown":"無法確認（未找到明確庫存訊號）"}[status],
        "price":price_match.group(0) if price_match else "", "matched_keyword":matched,
        "http_status":response.status_code, "content_type":content_type,
        "content_length":len(response.content), "page_title":title[:180],
        "checked_at":now(),
    }

def failed_result(source, error):
    return {"id":source["id"],"name":source["name"],"url":source["url"],
            "status":"unknown","label":"無法確認（讀取／驗證失敗）","price":"",
            "error":str(error)[:500],"checked_at":now()}

def notify_restock(item):
    if not TOPIC:
        return
    message = (f'{item["name"]}：{item.get("price") or "價格未辨識"}\\n'
               f'{item["url"]}\\n辨識訊號：{item.get("matched_keyword", "")}\\n請開啟商品頁確認庫存。')
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
