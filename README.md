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
