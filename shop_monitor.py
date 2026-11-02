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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
}

SOURCES = [
    {
        "id": "bic",
        "name": "Bic Camera",
        "url": "https://www.biccamera.com/bc/item/15605654/",
        "positive": ["カートに入れる", "在庫あり", "在庫有り"],
        "negative": ["予約受付は終了", "予約受付終了", "この商品はご購入できません", "ご購入できません", "販売休止中", "在庫切れ", "在庫なし"],
    },
    {
        "id": "yodobashi",
        "name": "Yodobashi",
        "url": "https://www.yodobashi.com/product/100000001010200995/",
        "positive": ["在庫あり", "在庫残少", "残少", "在庫わずか"],
        "negative": ["販売を終了しました", "販売休止中", "在庫なし", "在庫切れ", "販売終了"],
    },
    {
        "id": "hlj",
        "name": "HobbyLink Japan",
        "url": "https://www.hlj.co.jp/product/TKT07373",
        "positive": ["in stock", "available now", "在庫あり"],
        "negative": ["out of stock", "temporarily out of stock", "backordered", "order stop", "discontinued", "在庫なし", "売り切れ"],
    },
    {
        "id": "rakuten_kenbill",
        "name": "Rakuten kenbill-2",
        "url": "https://item.rakuten.co.jp/kenbill-2/4904810073734/",
        "positive": ["在庫あり", "買い物かごに入れる", "商品をかごに追加", "商品をかごに追加する", "かごに入れる"],
        "negative": ["売り切れ", "売り切れました", "在庫切れ", "在庫なし", "販売期間外", "販売期間が終了"],
    },
]


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def page_text(soup):
    # Include visible text and common stock-related HTML attributes.
    parts = [soup.get_text(" ", strip=True)]
    for tag in soup.find_all(["meta", "button", "input", "a", "span", "div"]):
        for attr in (
            "content", "aria-label", "value", "title", "data-stock",
            "data-availability", "data-stock-status", "itemprop", "alt"
        ):
            value = tag.get(attr)
            if value:
                parts.append(str(value))

    # Some stores publish stock state in Schema.org JSON-LD even when the
    # visible stock label is rendered dynamically by JavaScript.
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue

        def collect(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key.lower() == "availability":
                        if isinstance(value, str):
                            parts.append(value)
                    collect(value)
            elif isinstance(node, list):
                for value in node:
                    collect(value)
        collect(data)

    return re.sub(r"\\s+", " ", " ".join(parts))


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


def get_status(source):
    # Retry once: intermittent retailer timeouts from hosted runners should stay unknown.
    last_error = None
    for attempt in range(2):
        try:
            response = requests.get(
                source["url"],
                headers={**HEADERS, "Referer": "https://www.google.com/"},
                timeout=(10, 25),
            )
            response.raise_for_status()
            break
        except requests.RequestException as error:
            last_error = error
            if attempt == 0:
                time.sleep(2)
    else:
        raise last_error
    soup = BeautifulSoup(response.text, "html.parser")
    text = page_text(soup)
    lower = text.lower()

    negative = next((word for word in source["negative"] if word.lower() in lower), None)
    positive = next((word for word in source["positive"] if word.lower() in lower), None)
    availability = structured_availability(soup)
    schema_out = next((v for v in availability if v in ("outofstock", "soldout", "discontinued")), None)
    schema_in = next((v for v in availability if v in ("instock", "limitedavailability", "onlineonly")), None)

    # Explicit sold-out text wins over generic cart labels; structured stock
    # state is used when the page exposes it.
    if negative or schema_out:
        status = "out_of_stock"
        matched = negative or f"schema:{schema_out}"
    elif schema_in:
        status = "in_stock"
        matched = f"schema:{schema_in}"
    elif positive:
        status = "in_stock"
        matched = positive
    else:
        status = "unknown"
        matched = ""

    price_match = re.search(r"[￥¥]\s*[0-9,]+", text)
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    return {
        "id": source["id"],
        "name": source["name"],
        "url": source["url"],
        "status": status,
        "label": {
            "in_stock": "可能有貨（請點頁面確認）",
            "out_of_stock": "缺貨／停止販售",
            "unknown": "無法確認（未找到庫存關鍵字）",
        }[status],
        "price": price_match.group(0) if price_match else "",
        "matched_keyword": matched,
        "http_status": response.status_code,
        "page_title": title[:180],
        "checked_at": now(),
    }


def failed_result(source, error):
    return {
        "id": source["id"],
        "name": source["name"],
        "url": source["url"],
        "status": "unknown",
        "label": "讀取失敗",
        "price": "",
        "error": str(error)[:500],
        "checked_at": now(),
    }


def main():
    try:
        old = json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        old = {}
    previous = {item.get("id"): item for item in old.get("sources", [])}

    # Check retailers concurrently so a slow site does not delay all other stores.
    results_by_id = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(get_status, source): source for source in SOURCES}
        for future in as_completed(futures):
            source = futures[future]
            try:
                item = future.result()
            except Exception as error:
                item = failed_result(source, error)
            results_by_id[source["id"]] = item

    results = [results_by_id[source["id"]] for source in SOURCES]
    alerts = [
        item for item in results
        if item["status"] == "in_stock"
        and previous.get(item["id"], {}).get("status") != "in_stock"
        and item.get("matched_keyword")
    ]

    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(
        json.dumps(
            {
                "product": "BX-53 All-in-One Set",
                "checked_at": now(),
                "sources": results,
                "note": "網頁文字／按鈕屬性關鍵字判讀；連線失敗會重試一次；in_stock 是可能有貨，仍需開啟商品頁確認；unknown 不代表缺貨。",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    for item in alerts:
        if not TOPIC:
            continue
        message = (
            f'{item["name"]}：{item.get("price") or "價格未辨識"}\n'
            f'{item["url"]}\n'
            f'辨識文字：{item.get("matched_keyword", "")}\n請開啟商品頁確認庫存。'
        )
        requests.post(
            "https://ntfy.sh/" + quote(TOPIC, safe=""),
            data=message.encode("utf-8"),
            headers={
                "Title": "BX-53 日本通路可能補貨",
                "Click": item["url"],
                "Priority": "high",
            },
            timeout=(5, 10),
        ).raise_for_status()

    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()
