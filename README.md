# WaySim 旅遊網卡推薦機器人

依使用者旅遊使用習慣（重 / 中 / 輕度）× 旅行天數，估算需要的流量並推薦最合適的 WaySim 方案。
支援 eSIM 與實體上網卡兩種卡別、固定流量與吃到飽兩種計費方式，並提供跨類型第二推薦。

**兩個前端共用同一份資料：**
- 🤖 [bot.py](bot.py) — Telegram Bot（長輪詢，Zeabur worker 服務）
- 💚 [line_bot.py](line_bot.py) — LINE Messaging API Bot（webhook，Zeabur web 服務）

## 關於 WaySim 威訊旅遊網卡

[WaySim 威訊](https://waysim.net) 是台灣的旅遊上網解決方案品牌，提供出國旅遊用的 **eSIM** 與 **實體 SIM 上網卡**，涵蓋日本、韓國、東南亞、港澳、中國、美洲、紐澳、歐洲、中東、南亞等多個地區，計費方式包含固定流量與每日高速吃到飽兩種。客服：LINE 官方帳號 [@waysim](https://line.me/R/ti/p/@waysim)。

本機器人為非官方推薦工具，僅依據 WaySim 官網公開的產品資訊（透過 `scraper.py` 抓取）協助使用者依需求快速挑選方案，最終購買請至 [waysim.net](https://waysim.net) 官網下單。

## 功能

- 主選單依使用習慣分流（重 / 中 / 輕度）
- 旅行天數 × 使用習慣自動估算每日 / 總流量
- 不會安裝 eSIM 入口 → 引導至實體卡推薦
- 依國家、卡別、計費方式過濾產品
- ⭐ 標示最適合的子方案
- 🔹 自動跨類型第二推薦（固定 ↔ 吃到飽）
- 其他地區（歐洲、紐西蘭、加拿大、中東等）→ 引導至 LINE @waysim 客服

## 檔案結構

| 檔案 | 說明 |
| --- | --- |
| `bot.py` | Telegram 主程式（含選單 + 推薦邏輯，獨立運作） |
| `line_bot.py` | LINE Bot 主程式（Flask webhook + Quick Reply） |
| `core.py` | LINE 端使用的共用業務邏輯模組 |
| `scraper.py` | 從 WaySim 官網抓產品資料 |
| `products_data.json` | 產品資料快照（兩個 bot 共用） |
| `Procfile` | Zeabur / Heroku 啟動指令（web + worker） |
| `requirements.txt` | Python 相依套件 |

## 本機執行

### Telegram

```powershell
$env:BOT_TOKEN = "<your_telegram_bot_token>"
pip install -r requirements.txt
python bot.py
```

### LINE（需 ngrok 暴露 HTTPS）

```powershell
$env:LINE_CHANNEL_ACCESS_TOKEN = "<your_token>"
$env:LINE_CHANNEL_SECRET       = "<your_secret>"
python line_bot.py            # 監聽 0.0.0.0:8080

# 另一個 terminal
ngrok http 8080
# 將 https://xxxx.ngrok-free.app/callback 設為 LINE Developers 的 Webhook URL
```

## 部署到 Zeabur

Zeabur 偵測到 `Procfile` 後會列出 `web` 與 `worker` 兩種 process。同一個 repo 可以建立兩個服務分別跑兩個 bot。

### 方案 A：只跑 LINE（推薦先這樣）

1. 在 [Zeabur](https://zeabur.com) 建立新專案 → **Deploy New Service → Git** → 選 `Adaimade/wbot`
2. 部署完成後預設使用 `web` process（即 `gunicorn line_bot:app`）
3. **Networking → Add Public Domain**，取得 `https://<name>.zeabur.app`
4. 進入 **Variables**，加入：
   | 變數 | 值 |
   | --- | --- |
   | `LINE_CHANNEL_ACCESS_TOKEN` | LINE Developers Console → Messaging API 取得 |
   | `LINE_CHANNEL_SECRET` | 同上頁面取得 |
5. 重啟服務
6. 把 `https://<name>.zeabur.app/callback` 填到 LINE Developers Console 的 **Webhook URL**，按 **Verify** 看到 Success 即完成

### 方案 B：同時跑 Telegram + LINE（兩個服務）

1. 先跑完方案 A
2. 在同一個 Zeabur 專案 → **Add Service** → 再選一次同個 GitHub repo
3. 新服務在 **Settings → Start Command** 改成 `python bot.py`
4. **Variables** 設定 `BOT_TOKEN`
5. 兩個服務並存：LINE 用 web、Telegram 用 worker

## 重新爬取產品資料

```powershell
python scraper.py
```

會覆寫 `products_data.json`，重啟 bot 即可看到新資料。

## 注意事項

- LINE 與 Telegram 兩端**狀態各自獨立**儲存於記憶體中，重啟即清空（使用者重新傳 `/start` 即可）。若需持久化可日後接 Redis。
- `bot.py` 與 `core.py` 為**獨立副本**，業務邏輯有調整時需手動同步兩邊。
- LINE Quick Reply 上限 13 個按鈕，目前選國家頁剛好用滿（12 國家 + 客服）。
