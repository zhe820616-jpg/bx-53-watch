import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

OUT = Path("docs/test-status.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
}
# Live control pages/products are deliberately separate from BX-53 production URLs.
# A target passes only when the expected non-BX53 product/store identity and an
# explicit stock-state signal (in-stock or out-of-stock) are both present in the same response.
TARGETS = [
    {
        "id": "bic", "name": "Bic Camera", "kind": "product",
        "url": "https://www.biccamera.com/bc/item/12189630/",
        "identity": ["beyblade x 1巻"], "positive": ["在庫あり"],
        "negative": ["在庫なし", "在庫切れ", "販売休止中"],
    },
    {
        "id": "yodobashi", "name": "Yodobashi", "kind": "product",
        "url": "https://www.yodobashi.com/product/100000009003740957/",
        "identity": ["beyblade x", "コロコロコミックス"], "positive": ["在庫あり"],
        "negative": ["在庫なし", "在庫切れ", "販売終了"],
    },
    {
        "id": "hlj", "name": "HobbyLink Japan", "kind": "stock-filter listing",
        "url": "https://www.hlj.co.jp/search/?Page=1&inStock=1",
        "identity": ["hlj", "検索結果"], "positive": ["在庫あり"],
        "negative": ["在庫なし", "オーダーストップ"],
    },
    {
        "id": "rakuten_kenbill", "name": "Rakuten kenbill-2", "kind": "store listing",
        "url": "https://item.rakuten.co.jp/kenbill-2/c/0000000703/",
        "identity": ["kenbill-2", "bx-56"], "positive": ["在庫あり"],
        "negative": ["売り切れ", "在庫切れ"],
    },
]

def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()

def check(target):
    try:
        response = requests.get(target["url"], headers=HEADERS, timeout=(10, 25), allow_redirects=True)
        response.raise_for_status()
        html = response.text
        content_type = response.headers.get("Content-Type", "").lower()
        soup = BeautifulSoup(html, "html.parser")
        title = clean(soup.title.get_text(" ", strip=True)) if soup.title else ""
        body = clean(soup.get_text(" ", strip=True))
        low = (title + " " + body + " " + response.url).lower()
        blocked = (
            "html" not in content_type or len(html) < 500 or
            any(x in low for x in ("robot check", "captcha", "access denied", "cloudflare",
                                   "アクセスが集中", "リクエストをブロック"))
        )
        identity_ok = all(token.lower() in low for token in target["identity"])
        positive = next((x for x in target["positive"] if x.lower() in low), "")
        negative = next((x for x in target["negative"] if x.lower() in low), "")
        # Either explicit stock state validates the parser; the control product need not
        # happen to be in stock when this scheduled test runs.
        stock_signal = positive or negative
        passed = not blocked and identity_ok and bool(stock_signal)
        return {
            "id": target["id"], "name": target["name"], "kind": target["kind"],
            "url": target["url"], "passed": passed,
            "status": "pass" if passed else "fail",
            "reason": ("explicit stock signal and identity confirmed" if passed else
                       "blocked/invalid response" if blocked else
                       "expected page identity missing" if not identity_ok else
                       "no explicit stock signal"),
            "matched_positive": positive, "matched_negative": negative, "stock_signal": stock_signal,
            "http_status": response.status_code, "content_type": content_type,
            "content_length": len(response.content), "page_title": title[:180],
            "checked_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        }
    except Exception as error:
        return {
            "id": target["id"], "name": target["name"], "kind": target["kind"],
            "url": target["url"], "passed": False, "status": "fail",
            "reason": str(error)[:400],
            "checked_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        }

def main():
    results_by_id = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(check, target): target for target in TARGETS}
        for future in as_completed(futures):
            target = futures[future]
            results_by_id[target["id"]] = future.result()
    results = [results_by_id[x["id"]] for x in TARGETS]
    passed = all(x["passed"] for x in results)
    report = {
        "mode": "production" if passed else "testing",
        "all_passed": passed,
        "passed": sum(x["passed"] for x in results),
        "total": len(results),
        "checked_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "results": results,
        "note": "This test uses non-BX53 control pages. It validates live page access and explicit stock-state signals (in-stock or out-of-stock); it does not prove BX-53 product-page selectors. BX-53 identity checks remain mandatory in production.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write("mode=" + report["mode"] + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not passed:
        print("At least one live control-page test did not pass; keep test mode and do not change BX-53 production targets.")

if __name__ == "__main__":
    main()
