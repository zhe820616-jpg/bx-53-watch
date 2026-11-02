const $=id=>document.getElementById(id);
const timeText=value=>{if(!value)return "時間未知";const d=new Date(value);return Number.isNaN(d.getTime())?value:d.toLocaleString("zh-TW",{timeZone:"Asia/Taipei",hour12:false});};
async function loadAmazon(){
 try{
  const r=await fetch("./status.json?t="+Date.now(),{cache:"no-store"});if(!r.ok)throw new Error("目前讀取不到 Amazon 紀錄");
  const d=await r.json();$("label").textContent=d.label||"無法確認";$("checked").textContent="最後檢查："+timeText(d.checked_at);
  $("message").textContent=d.message||"";$("dot").className="dot "+(d.status==="in_stock"?"good":d.status==="out_of_stock"?"bad":"");
  const box=$("offers");box.replaceChildren();
  if(d.offers?.length){d.offers.forEach(o=>{const el=document.createElement("div");el.className="offer";
   for(const [cls,val] of [["seller",o.seller||"賣家未辨識"],["price",o.price||"價格未辨識"],["source",o.source||"Amazon"]]){const n=document.createElement("div");n.className=cls;n.textContent=val;el.append(n);}box.append(el);});}
  else{const p=document.createElement("p");p.className="muted";p.textContent="目前沒有可確認的出品資料。";box.append(p);}
 }catch(e){$("label").textContent="無法讀取";$("checked").textContent=e.message;$("dot").className="dot";}
}
async function loadShops(){
 const box=$("shops");box.replaceChildren();$("shop-checked").textContent="正在更新通路紀錄…";
 try{
  const r=await fetch("./shop-status.json?t="+Date.now(),{cache:"no-store"});if(!r.ok)throw new Error("讀取失敗，請稍後再試");
  const d=await r.json();$("shop-checked").textContent="通路資料更新時間："+timeText(d.checked_at);
  (d.sources||[]).forEach(s=>{
   const el=document.createElement("div");el.className="offer";
   const name=document.createElement("a");name.className="seller";name.textContent=s.name||s.id;name.href=s.url;name.target="_blank";name.rel="noopener";
   const status=document.createElement("div");status.className="price";status.textContent=s.label||s.status||"無法確認";
   const meta=document.createElement("div");meta.className="source";meta.textContent=[s.price,s.error?"原因："+s.error:"",s.matched_keyword?"命中："+s.matched_keyword:"","檢查："+timeText(s.checked_at)].filter(Boolean).join(" · ");
   el.append(name,status,meta);box.append(el);
  });
  if(!d.sources?.length){const p=document.createElement("p");p.className="muted";p.textContent="目前沒有通路資料。";box.append(p);}
 }catch(e){$("shop-checked").textContent=e.message;const p=document.createElement("p");p.className="muted";p.textContent=e.message;box.append(p);}
}
async function refreshAll(){ $("refresh").disabled=true;$("refresh").textContent="更新中…";await Promise.all([loadAmazon(),loadShops()]);$("refresh").disabled=false;$("refresh").textContent="重新整理";}
$("refresh").addEventListener("click",refreshAll);refreshAll();
if("serviceWorker"in navigator)navigator.serviceWorker.register("./sw.js");