# WaySim 旅遊網卡推薦機器人

依使用者旅遊使用習慣（重 / 中 / 輕度）× 旅行天數，估算需要的流量並推薦最合適的 WaySim 方案。
支援 eSIM 與實體上網卡兩種卡別、固定流量與吃到飽兩種計費方式，並提供跨類型第二推薦。

## 功能

- 主選單依使用習慣分流（重 / 中 / 輕度）
- 旅行天數 × 使用習慣自動估算每日 / 總流量
- 不會安裝 eSIM 入口 → 引導至實體卡推薦
- 依國家、卡別、計費方式過濾產品
- ⭐ 標示最適合的子方案
- 🔹 自動跨類型第二推薦（固定 ↔ 吃到飽）
- 其他地區（歐洲、紐西蘭、加拿大、中東等）→ 引導至 LINE @waysim 客服

## 資料來源

從 [waysim.net](https://waysim.net) 的 Shopify products.json 抓取。執行 `python scraper.py` 重新生成 `products_data.json`。

## 本機執行

```powershell
# Windows PowerShell
$env:BOT_TOKEN = "<your_telegram_bot_token>"
pip install -r requirements.txt
python bot.py
```

## 部署到 Zeabur

1. 在 [Zeabur](https://zeabur.com) 新增專案，從 GitHub 匯入此 repo。
2. 服務啟動後到「Variables」設定環境變數：

   | 變數 | 值 |
   | --- | --- |
   | `BOT_TOKEN` | 從 [@BotFather](https://t.me/BotFather) 取得 |

3. Zeabur 會偵測 `Procfile`，以 `worker: python bot.py` 啟動。Bot 採 Telegram 長輪詢（不需要對外 port）。

## 重新爬取產品資料

```powershell
python scraper.py
```

會覆寫 `products_data.json`。

## 檔案結構

- `bot.py` — Telegram bot 主程式（含選單流程、推薦邏輯）
- `scraper.py` — 從 WaySim 抓取產品資料
- `products_data.json` — 產品資料快照
- `requirements.txt` — Python 相依
- `Procfile` — Zeabur / Heroku 啟動指令
