# BX-53 補貨監控

免費 Beta：以 GitHub Actions 定期讀取 Amazon 日本 BX-53 商品頁與出品列表，將狀態發布到 GitHub Pages，並可透過 ntfy 推播通知。

## 重要限制
- GitHub Actions 排程不保證每 5 分鐘準時執行；GitHub 高負載時可能延遲。
- Amazon 可能回傳 CAPTCHA、限制自動讀取或更改頁面結構。程式遇到無法辨識時會標示「無法確認」，不會把未知當成缺貨或補貨。
- 監控只依公開頁面訊號判斷「可能可購買」，不能保證結帳成功。
- 是否寄送台灣需登入 Amazon 並以台灣收件地址結帳確認。
- GitHub Pages 的 status.json 是公開的；不要把 ntfy topic 寫入程式或公開檔案。

## 設定
1. GitHub 專案 Settings → Pages → Build and deployment，選 Deploy from a branch，Branch 選 main，資料夾選 /docs，儲存。
2. Settings → Secrets and variables → Actions → New repository secret。
   - Name：NTFY_TOPIC
   - Secret：你自己建立的一段隨機且難猜的 topic 名稱。不要貼到公開 README 或聊天室。
3. 安裝 iPhone ntfy App，訂閱同一個 topic，並允許通知。
4. Actions → BX-53 stock watch → Run workflow，先手動執行一次。
5. Pages 部署完成後，Safari 開啟 https://zhe820616-jpg.github.io/bx-53-watch/ ，分享 → 加入主畫面。

## 排程
Workflow 設定為每小時第 2、7、12…57 分鐘觸發，理論上約每 5 分鐘一次，但不是即時保證。

## 商品
目前設定 ASIN：B0HJ75X3PN。若 ASIN 與目標商品不符，請先停止 workflow 並修正 monitor.py 與網站連結。


## BX-53 日本其他通路監控
除 Amazon 外，排程也會檢查以下公開商品頁，結果寫入 `docs/shop-status.json`：
- Bic Camera：商品代碼 15605654
- Yodobashi：商品代碼 100000001010200995
- HobbyLink Japan：商品代碼 TKT07373
- 樂天市場 kenbill-2：JAN 4904810073734

只有在前次已建立狀態基準後，偵測到「非有貨 → 可能有貨」才發送 ntfy；第一次執行只建立基準，避免把既有商品頁誤報為新補貨。網站若改版、擋自動讀取或庫存文字不明，會標示「無法確認」，不會視為有貨。通知是公開頁面文字判讀，請開啟商店頁確認實際庫存、價格與集運倉可否收貨。
