import json, os, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup

TOPIC=os.getenv("NTFY_TOPIC","").strip()
PATH=Path("docs/shop-status.json")
HEADERS={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36","Accept-Language":"ja-JP,ja;q=0.9"}
SOURCES=[
 {"id":"bic","name":"Bic Camera","url":"https://www.biccamera.com/bc/item/15605654/","positive":["カートに入れる","在庫あり","販売中"],"negative":["予約受付は終了","ご購入できません","販売休止中","在庫切れ"]},
 {"id":"yodobashi","name":"Yodobashi","url":"https://www.yodobashi.com/product/100000001010200995/","positive":["在庫あり","在庫残少","残少"],"negative":["販売を終了しました","販売休止中","在庫なし","在庫切れ"]},
 {"id":"hlj","name":"HobbyLink Japan","url":"https://www.hlj.co.jp/product/TKT07373","positive":["in stock"],"negative":["out of stock","order stop","discontinued"]},
 {"id":"rakuten_kenbill","name":"Rakuten kenbill-2","url":"https://item.rakuten.co.jp/kenbill-2/4904810073734/","positive":["在庫あり","買い物かごに入れる"],"negative":["売り切れ","在庫切れ","在庫なし"]},
]
def get_status(s):
 r=requests.get(s["url"],headers=HEADERS,timeout=25); r.raise_for_status()
 soup=BeautifulSoup(r.text,"html.parser"); text=re.sub(r"\s+"," ",soup.get_text(" ",strip=True))
 if any(x.lower() in text.lower() for x in s["negative"]): state="out_of_stock"
 elif any(x.lower() in text.lower() for x in s["positive"]): state="in_stock"
 else: state="unknown"
 m=re.search(r"[￥¥]\s*[0-9,]+",text)
 return {"id":s["id"],"name":s["name"],"url":s["url"],"status":state,"label":{"in_stock":"可能有貨","out_of_stock":"缺貨／停止販售","unknown":"無法確認"}[state],"price":m.group(0) if m else "","checked_at":datetime.now(timezone.utc).isoformat(timespec="seconds")}
def main():
 try: old=json.loads(PATH.read_text(encoding="utf-8"))
 except Exception: old={}
 prev={x.get("id"):x for x in old.get("sources",[])}
 results=[]; alerts=[]
 for s in SOURCES:
  try: item=get_status(s)
  except Exception as e: item={"id":s["id"],"name":s["name"],"url":s["url"],"status":"unknown","label":"讀取失敗","price":"","error":str(e)}
  before=prev.get(s["id"],{})
  if item["status"]=="in_stock" and before.get("status")!="in_stock" and before:
   alerts.append(item)
  results.append(item)
 PATH.parent.mkdir(parents=True,exist_ok=True)
 PATH.write_text(json.dumps({"product":"BX-53 All-in-One Set","checked_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),"sources":results,"note":"公開網頁文字判讀，unknown 不代表缺貨；請開啟商品頁確認。"},ensure_ascii=False,indent=2),encoding="utf-8")
 for x in alerts:
  if TOPIC:
   msg=f'{x["name"]}：{x.get("price") or "價格未辨識"}\\n{x["url"]}\\n請確認商品頁庫存。'
   requests.post("https://ntfy.sh/"+quote(TOPIC,safe=""),data=msg.encode(),headers={"Title":"BX-53 日本通路可能補貨","Click":x["url"],"Priority":"high"},timeout=15).raise_for_status()
 print(json.dumps(results,ensure_ascii=False))
if __name__=="__main__": main()
