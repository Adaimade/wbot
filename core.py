"""WaySim 共用業務邏輯（產品載入、推薦演算法、文案常數）。

本模組僅供 line_bot.py 使用。Telegram 版（bot.py）為了避免變動風險，
維持獨立副本不引用此檔。若一邊有邏輯調整，請手動同步另一邊。

兩邊共用同一個 products_data.json，所以資料來源永遠一致。
"""

import os
import re
import json

# ── 基本常數 ──────────────────────────────────────────────────────────────────
LINE_CS = "https://line.me/R/ti/p/@waysim"

POPULAR_COUNTRIES = ["jp", "kr", "th", "vn", "sg", "id", "my", "ph", "cn", "hkmo", "us", "au"]

COUNTRY_DISPLAY = {
    "jp":   "🇯🇵 日本",   "kr":   "🇰🇷 韓國",
    "th":   "🇹🇭 泰國",   "vn":   "🇻🇳 越南",
    "sg":   "🇸🇬 新加坡", "id":   "🇮🇩 印尼",
    "my":   "🇲🇾 馬來西亞", "ph":  "🇵🇭 菲律賓",
    "cn":   "🇨🇳 中國",   "hkmo": "🇭🇰 港澳",
    "us":   "🇺🇸 美國",   "au":   "🇦🇺 澳洲",
}

TITLE_COUNTRY_MAP = [
    ("中港澳",   ["cn", "hkmo"]),
    ("中國",     ["cn"]),
    ("香港澳門", ["hkmo"]),
    ("日本",     ["jp"]),   ("韓國",     ["kr"]),
    ("泰國",     ["th"]),   ("越南",     ["vn"]),
    ("新加坡",   ["sg"]),   ("印尼",     ["id"]),
    ("馬來西亞", ["my"]),   ("菲律賓",   ["ph"]),
    ("美國",     ["us"]),   ("澳洲",     ["au"]),
]

USAGE_LABEL = {
    "heavy":  "📸 重度（影片 / 社群 / 大量上傳）",
    "medium": "📱 中度（地圖 / 查資料 / 偶爾社群）",
    "light":  "📷 輕度（地圖 / 確認行程 / 一般搜尋）",
}

DAYS_LABEL  = {"d1": "1–3 天",  "d2": "4–7 天",  "d3": "8–15 天",  "d4": "16–30 天"}
DAYS_MEDIAN = {"d1": 2,         "d2": 5,          "d3": 10,          "d4": 20}
DAILY_GB    = {"heavy": 5.0, "medium": 2.0, "light": 0.5}
FIXED_TIERS = [5, 10, 20, 30, 50]

SKIP_KEYWORDS = ["行李袋", "卡套", "WaySim Card", "充值", "儲值", "客制", "延期"]

PLAN_FILTER = {
    "fixed":     lambda t: "固定流量" in t,
    "unlimited": lambda t: "吃到飽" in t,
}

CARD_FILTER = {
    "esim":     lambda t: "eSIM" in t or "esim" in t.lower(),
    "physical": lambda t: "上網卡" in t,
}

CARD_LABEL = {"esim": "eSIM", "physical": "實體卡"}

# ── 純文字訊息（無 HTML，給 LINE 用）──────────────────────────────────────────
WARN_PLAIN = {
    "fixed": (
        "⚠️ 固定流量注意：流量用完即完全無網路，"
        "需先找到 WiFi 才能重新購買新方案。"
    ),
    "unlimited": (
        "⚠️ 吃到飽注意：超過每日限額後可能降速，"
        "降速後僅適合 LINE 傳送文字訊息，"
        f"其他服務可能造成不順暢。詳細規格請洽 WaySim 客服 {LINE_CS}"
    ),
}

PRICEDIFF_TEXT_PLAIN = (
    "❓ 為什麼有些方案比較貴？\n\n"
    "• 固定流量：依總容量計費，容量越大越貴，但整體較划算\n"
    "• 吃到飽每天高額度：每日可用量越高，成本也越高\n"
    "• 吃到飽高速原生線路：最高規格電信資源，價格也最高\n\n"
    "建議依實際使用習慣選擇。\n"
    f"不確定可詢問 WaySim 客服：{LINE_CS}"
)

CS_TEXT_PLAIN = (
    "📞 聯繫 WaySim 客服\n\n"
    "LINE 官方帳號：@waysim\n"
    f"{LINE_CS}\n\n"
    "客服可協助：\n"
    "• 歐洲多國方案（含 Orange Holiday 原生卡 + 通話）\n"
    "• 紐西蘭、加拿大、關島塞班、以色列、土耳其、巴基斯坦、斯里蘭卡、杜拜\n"
    "• 多國旅行方案建議\n"
    "• 速度與規格詳細說明\n"
    "• 方案延長與特殊需求"
)

MAIN_MENU_TEXT_PLAIN = (
    "👋 歡迎使用 WaySim 旅遊網卡推薦機器人\n\n"
    "請選擇你的旅遊使用習慣："
)

PHYSICAL_INTRO_TEXT_PLAIN = (
    "📦 選擇實體卡（不用 eSIM）\n\n"
    "我們需要你的使用習慣，協助挑選合適流量：\n"
    "請選擇你的旅遊使用習慣："
)

# ── 全域產品索引 ──────────────────────────────────────────────────────────────
PRODUCTS: list[dict] = []
COUNTRY_INDEX: dict[str, list[dict]] = {}


def _country_codes(title: str) -> list[str]:
    for kw, codes in TITLE_COUNTRY_MAP:
        if kw in title:
            return codes
    return []


def load_products() -> None:
    global PRODUCTS, COUNTRY_INDEX
    path = os.path.join(os.path.dirname(__file__), "products_data.json")
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    PRODUCTS = [p for p in raw if not any(k in p["title"] for k in SKIP_KEYWORDS)]
    COUNTRY_INDEX = {c: [] for c in COUNTRY_DISPLAY}
    for p in PRODUCTS:
        for code in _country_codes(p["title"]):
            if code in COUNTRY_INDEX:
                COUNTRY_INDEX[code].append(p)


def products_for(plan: str, country: str, card_type: str = "esim") -> list[dict]:
    pf = PLAN_FILTER.get(plan)
    cf = CARD_FILTER.get(card_type)
    if not pf or not cf:
        return []
    return [p for p in COUNTRY_INDEX.get(country, []) if pf(p["title"]) and cf(p["title"])]


def short_title(title: str) -> str:
    parts = title.split("│")
    return parts[0].strip() if parts else title


def option1_vals(product: dict) -> list[str]:
    seen, vals = set(), []
    for v in product["variants"]:
        val = v.get("option1")
        if val and val not in seen:
            seen.add(val); vals.append(val)
    return vals


# ── 推薦邏輯 ──────────────────────────────────────────────────────────────────
def rec_fixed_gb(est: float) -> int:
    for t in FIXED_TIERS:
        if t >= est:
            return t
    return FIXED_TIERS[-1]


def compute(usage: str, days_key: str) -> dict:
    daily   = DAILY_GB[usage]
    median  = DAYS_MEDIAN[days_key]
    est_gb  = daily * median
    return {
        "est_gb":       est_gb,
        "rec_fixed_gb": rec_fixed_gb(est_gb),
        "rec_daily_gb": daily,
        "exceeds_max":  est_gb > FIXED_TIERS[-1],
    }


def total_gb(opt: str) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)\s*GB", opt, re.IGNORECASE)
    return float(m.group(1)) if m else 0.0


def daily_gb_opt(opt: str) -> float:
    m = re.search(r"每天\s*(\d+(?:\.\d+)?)\s*GB", opt, re.IGNORECASE)
    if m: return float(m.group(1))
    m = re.search(r"每天\s*(\d+)\s*M", opt, re.IGNORECASE)
    if m: return float(m.group(1)) / 1024
    if "吃到飽" in opt: return 999.0
    return 0.0


def rec_idx_by_gb(options: list[str], plan: str, target_gb: float) -> int:
    if not options:
        return 0
    if plan == "fixed":
        gbs = [(total_gb(o), i) for i, o in enumerate(options)]
        valid = [(g, i) for g, i in gbs if g > 0]
        if not valid: return 0
        above = [(g, i) for g, i in valid if g >= target_gb]
        if above: return min(above)[1]
        return max(valid, key=lambda x: x[0])[1]
    else:
        dgs = [daily_gb_opt(o) for o in options]
        tiered  = [(abs(dg - target_gb), i) for i, dg in enumerate(dgs) if dg < 900]
        unlim   = [i for i, dg in enumerate(dgs) if dg >= 900]
        if not tiered: return unlim[0] if unlim else 0
        max_tier = max(dg for dg in dgs if dg < 900)
        if target_gb > max_tier and unlim:
            return unlim[0]
        return min(tiered)[1]


# ── 解析 user state ──────────────────────────────────────────────────────────
def resolve_product(state: dict) -> dict | None:
    handles = state.get("product_handles", [])
    idx = state.get("product_idx", 0)
    if not handles or idx >= len(handles): return None
    return next((p for p in PRODUCTS if p["handle"] == handles[idx]), None)


def resolve_sec(state: dict) -> dict | None:
    handle = state.get("sec_handle")
    if not handle: return None
    return next((p for p in PRODUCTS if p["handle"] == handle), None)


# ── 價格表 ────────────────────────────────────────────────────────────────────
def price_table(product: dict, opt1: str) -> str:
    variants = [v for v in product["variants"] if v.get("option1") == opt1]
    if not variants:
        return "（目前無法查詢價格，請洽客服）"

    def day_num(v):
        d = "".join(c for c in (v.get("option2") or "") if c.isdigit())
        return int(d) if d else 0

    variants.sort(key=day_num)
    if not variants[0].get("option2"):
        return f"NT${int(float(variants[0]['price']))}"
    return "\n".join(
        f"• {v.get('option2', '')}：NT${int(float(v['price']))}"
        for v in variants
    )


def prepare_sec(state: dict):
    """跨類型推薦：準備第二推薦的 product + option1（同卡別，另一種計費方式）。"""
    plan      = state.get("plan", "unlimited")
    country   = state.get("country", "")
    card_type = state.get("card_type", "esim")
    sec_plan  = "unlimited" if plan == "fixed" else "fixed"

    sec_products = products_for(sec_plan, country, card_type)
    if not sec_products:
        state["sec_handle"] = None; return

    sec_product = sec_products[0]
    sec_opts    = option1_vals(sec_product)
    target_gb   = state.get("rec_daily_gb", 2) if sec_plan == "unlimited" else state.get("rec_fixed_gb", 10)
    sec_rec     = rec_idx_by_gb(sec_opts, sec_plan, target_gb)

    state["sec_handle"]  = sec_product["handle"]
    state["sec_opts"]    = sec_opts
    state["sec_rec_idx"] = sec_rec
    state["sec_plan"]    = sec_plan


def build_result_text_plain(product: dict, opt1: str, plan: str, card_type: str = "esim") -> str:
    table = price_table(product, opt1)
    warn  = WARN_PLAIN.get(plan, "")
    card  = CARD_LABEL.get(card_type, "")
    return (
        f"✅ {product['title']}\n"
        f"卡別：{card}　方案：{opt1}\n\n"
        f"💰 天數 & 價格\n{table}\n\n"
        f"{warn}\n\n"
        f"👉 前往購買：{product['url']}"
    )
