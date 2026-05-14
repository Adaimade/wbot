"""
WaySim 產品資料爬蟲
執行：python scraper.py
輸出：products_data.json
"""

import json
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

# 強制 stdout 使用 UTF-8（避免 Windows cp950 報錯）
sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://waysim.net"

# WaySim 所有已知的 collection handles（URL-decoded）
COLLECTIONS = [
    "日本網卡專區",
    "日韓專區",
    "中國網卡專區",
    "港澳上網卡專區",
    "泰國網卡專區",
    "越南",
    "esim專區-1",
    "亞洲esim",
    "歐洲esim",
    "亞洲地區",
    "歐洲地區",
]


def fetch_json(url: str) -> dict | None:
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
                )
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  ⚠️  fetch 失敗 {url}: {e}")
        return None


def collect_all_handles() -> dict[str, str]:
    """從 /products.json 分頁取得所有產品 handle → title 對應。"""
    handles: dict[str, str] = {}
    page = 1
    while True:
        url = f"{BASE}/products.json?limit=250&page={page}"
        print(f"  取得產品清單第 {page} 頁…")
        data = fetch_json(url)
        if not data or not data.get("products"):
            break
        products = data["products"]
        if not products:
            break
        for p in products:
            handles[p["handle"]] = p["title"]
        if len(products) < 250:
            break
        page += 1
        time.sleep(0.5)
    return handles


def fetch_product_detail(handle: str) -> dict | None:
    encoded = urllib.parse.quote(handle, safe="-")
    url = f"{BASE}/products/{encoded}.json"
    data = fetch_json(url)
    if not data or "product" not in data:
        return None
    p = data["product"]

    # 取得方案選項名稱（option1 = 方案類型, option2 = 天數/流量）
    options = {o["position"]: o["name"] for o in p.get("options", [])}

    variants = []
    for v in p.get("variants", []):
        variants.append({
            "id":      v["id"],
            "title":   v["title"],
            "price":   v["price"],
            "option1": v.get("option1"),
            "option2": v.get("option2"),
            "option3": v.get("option3"),
            "sku":     v.get("sku", ""),
        })

    return {
        "id":           p["id"],
        "handle":       handle,
        "title":        p["title"],
        "url":          f"{BASE}/products/{urllib.parse.quote(handle, safe='-')}",
        "option_names": options,
        "variants":     variants,
    }


def main():
    print("=== WaySim 產品資料爬蟲 ===\n")

    print("① 取得所有產品清單…")
    handles = collect_all_handles()
    print(f"   共找到 {len(handles)} 個產品\n")

    print("② 逐一抓取產品詳細資料（含所有方案與價格）…")
    products = []
    for i, (handle, title) in enumerate(handles.items(), 1):
        print(f"   [{i}/{len(handles)}] {title}")
        detail = fetch_product_detail(handle)
        if detail:
            products.append(detail)
        time.sleep(0.4)  # 避免對伺服器造成過大壓力

    print(f"\n③ 儲存資料…")
    with open("products_data.json", "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 完成！共儲存 {len(products)} 個產品至 products_data.json")

    # 簡易摘要
    print("\n── 產品清單摘要 ──")
    for p in products:
        print(f"  {p['title']}")
        print(f"    {len(p['variants'])} 個方案組合，網址：{p['url']}")


if __name__ == "__main__":
    main()
