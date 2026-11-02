const $=id=>document.getElementById(id);
async function loadStatus(){
 $("label").textContent="讀取狀態中…";
 try{
  const r=await fetch("./status.json?t="+Date.now(),{cache:"no-store"});
  if(!r.ok)throw new Error("尚未有監控結果，請先在 GitHub Actions 手動執行一次。");
  const d=await r.json();$("label").textContent=d.label||"無法確認";
  $("checked").textContent="最後檢查："+(d.checked_at||"未知");$("message").textContent=d.message||"";
  $("dot").className="dot "+(d.status==="in_stock"?"good":d.status==="out_of_stock"?"bad":"");
  const box=$("offers");box.replaceChildren();
  if(d.offers?.length){d.offers.forEach(o=>{const el=document.createElement("div");el.className="offer";
   for(const [cls,val] of [["seller",o.seller||"賣家未辨識"],["price",o.price||"價格未辨識"],["source",o.source||"Amazon"]]){
    const n=document.createElement("div");n.className=cls;n.textContent=val;el.append(n);}box.append(el);});}
  else{const p=document.createElement("p");p.className="muted";p.textContent="目前沒有可確認的出品資料。";box.append(p);}
 }catch(e){$("label").textContent="尚未取得資料";$("checked").textContent="請稍後重試";$("message").textContent=e.message;$("dot").className="dot";}
}
$("refresh").addEventListener("click",loadStatus);loadStatus();
if("serviceWorker"in navigator)navigator.serviceWorker.register("./sw.js");