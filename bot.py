import os
import re
import sys
import json
import logging
import traceback
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
LINE_CS = "https://line.me/R/ti/p/@waysim"

# ── 常數 ──────────────────────────────────────────────────────────────────────
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

# d1~d4 = 旅行天數區間，median 用於估算
DAYS_LABEL  = {"d1": "1–3 天",  "d2": "4–7 天",  "d3": "8–15 天",  "d4": "16–30 天"}
DAYS_MEDIAN = {"d1": 2,         "d2": 5,          "d3": 10,          "d4": 20}

# 每日用量估算（GB）
DAILY_GB = {"heavy": 5.0, "medium": 2.0, "light": 0.5}

# WaySim 固定流量可選容量
FIXED_TIERS = [5, 10, 20, 30, 50]

# ── 估算邏輯 ──────────────────────────────────────────────────────────────────
def _rec_fixed_gb(est: float) -> int:
    for t in FIXED_TIERS:
        if t >= est:
            return t
    return FIXED_TIERS[-1]


def _compute(usage: str, days_key: str) -> dict:
    daily   = DAILY_GB[usage]
    median  = DAYS_MEDIAN[days_key]
    est_gb  = daily * median
    return {
        "est_gb":          est_gb,
        "rec_fixed_gb":    _rec_fixed_gb(est_gb),
        "rec_daily_gb":    daily,
        "exceeds_max":     est_gb > FIXED_TIERS[-1],
    }


# ── 產品資料 ──────────────────────────────────────────────────────────────────
PRODUCTS: list[dict] = []
COUNTRY_INDEX: dict[str, list[dict]] = {}
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


def _products_for(plan: str, country: str, card_type: str = "esim") -> list[dict]:
    pf = PLAN_FILTER.get(plan)
    cf = CARD_FILTER.get(card_type)
    if not pf or not cf:
        return []
    return [p for p in COUNTRY_INDEX.get(country, []) if pf(p["title"]) and cf(p["title"])]


def _short_title(title: str) -> str:
    """產品按鈕簡短顯示：只取第一段「國家+卡別」。"""
    parts = title.split("│")
    return parts[0].strip() if parts else title


def _option1_vals(product: dict) -> list[str]:
    seen, vals = set(), []
    for v in product["variants"]:
        val = v.get("option1")
        if val and val not in seen:
            seen.add(val); vals.append(val)
    return vals


# ── 推薦 option1 ──────────────────────────────────────────────────────────────
def _total_gb(opt: str) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)\s*GB", opt, re.IGNORECASE)
    return float(m.group(1)) if m else 0.0


def _daily_gb_opt(opt: str) -> float:
    m = re.search(r"每天\s*(\d+(?:\.\d+)?)\s*GB", opt, re.IGNORECASE)
    if m: return float(m.group(1))
    m = re.search(r"每天\s*(\d+)\s*M", opt, re.IGNORECASE)
    if m: return float(m.group(1)) / 1024
    if "吃到飽" in opt: return 999.0
    return 0.0


def _rec_idx_by_gb(options: list[str], plan: str, target_gb: float) -> int:
    """根據具體 GB 目標挑選最合適的 option1 index。
    fixed：選最小且 >= target 的容量（確保夠用）；unlimited：超過最高限速方案就選吃到飽。
    """
    if not options:
        return 0
    if plan == "fixed":
        gbs = [(_total_gb(o), i) for i, o in enumerate(options)]
        valid = [(g, i) for g, i in gbs if g > 0]
        if not valid: return 0
        above = [(g, i) for g, i in valid if g >= target_gb]
        if above: return min(above)[1]          # 最小且夠用的
        return max(valid, key=lambda x: x[0])[1]  # 全部不夠則選最大
    else:
        dgs = [_daily_gb_opt(o) for o in options]
        tiered  = [(abs(dg - target_gb), i) for i, dg in enumerate(dgs) if dg < 900]
        unlim   = [i for i, dg in enumerate(dgs) if dg >= 900]
        if not tiered: return unlim[0] if unlim else 0
        max_tier = max(dg for dg in dgs if dg < 900)
        # 需求超過最高限速方案 → 推薦吃到飽
        if target_gb > max_tier and unlim:
            return unlim[0]
        return min(tiered)[1]


# ── 解析 user_data ─────────────────────────────────────────────────────────────
def _resolve(ud: dict) -> dict | None:
    handles = ud.get("product_handles", [])
    idx = ud.get("product_idx", 0)
    if not handles or idx >= len(handles): return None
    return next((p for p in PRODUCTS if p["handle"] == handles[idx]), None)


def _resolve_sec(ud: dict) -> dict | None:
    handle = ud.get("sec_handle")
    if not handle: return None
    return next((p for p in PRODUCTS if p["handle"] == handle), None)


# ── 價格表 ────────────────────────────────────────────────────────────────────
def _price_table(product: dict, opt1: str) -> str:
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


# ── 訊息文字 ──────────────────────────────────────────────────────────────────
WARN = {
    "fixed": (
        "⚠️ <b>固定流量注意：</b>流量用完即完全無網路，"
        "需先找到 WiFi 才能重新購買新方案。"
    ),
    "unlimited": (
        "⚠️ <b>吃到飽注意：</b>超過每日限額後可能降速，"
        "降速後僅適合 LINE 傳送文字訊息，"
        f"其他服務可能造成不順暢。詳細規格請洽 <a href='{LINE_CS}'>WaySim 客服</a>。"
    ),
    "physical": (
        "⚠️ 超過流量限額後可能降速，"
        f"詳細規格請洽 <a href='{LINE_CS}'>WaySim 客服</a>。"
    ),
}

PRICEDIFF_TEXT = (
    "❓ <b>為什麼有些方案比較貴？</b>\n\n"
    "• <b>固定流量</b>：依總容量計費，容量越大越貴，但整體較划算\n"
    "• <b>吃到飽每天高額度</b>：每日可用量越高，成本也越高\n"
    "• <b>吃到飽高速原生線路</b>：最高規格電信資源，價格也最高\n\n"
    "建議依實際使用習慣選擇。\n"
    f"不確定可以 <a href='{LINE_CS}'>詢問 WaySim 客服</a>。"
)

CS_TEXT = (
    f"📞 <b>聯繫 WaySim 客服</b>\n\n"
    f"LINE 官方帳號：<b>@waysim</b>\n"
    f"<a href='{LINE_CS}'>點此開啟 LINE 對話</a>\n\n"
    "客服可協助：\n"
    "• 歐洲多國方案（含 Orange Holiday 原生卡 + 通話）\n"
    "• 紐西蘭、加拿大、關島塞班、以色列、土耳其、巴基斯坦、斯里蘭卡、杜拜\n"
    "• 多國旅行方案建議\n"
    "• 速度與規格詳細說明\n"
    "• 方案延長與特殊需求"
)

MAIN_MENU_TEXT = (
    "👋 歡迎使用 <b>WaySim 旅遊網卡推薦機器人</b>\n\n"
    "請選擇你的旅遊使用習慣："
)

PHYSICAL_INTRO_TEXT = (
    "📦 <b>選擇實體卡（不用 eSIM）</b>\n\n"
    "我們需要你的使用習慣，協助挑選合適流量：\n"
    "請選擇你的旅遊使用習慣："
)


# ── 鍵盤 ──────────────────────────────────────────────────────────────────────
BACK_TO_MAIN = InlineKeyboardMarkup([[
    InlineKeyboardButton("🔙 返回主選單", callback_data="main")
]])


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 重度｜影片 / 社群 / 大量上傳",   callback_data="usage_heavy")],
        [InlineKeyboardButton("📱 中度｜地圖 / 查資料 / 偶爾社群", callback_data="usage_medium")],
        [InlineKeyboardButton("📷 輕度｜地圖 / 確認行程 / 一般搜尋", callback_data="usage_light")],
        [InlineKeyboardButton("👴 不會安裝 eSIM（要實體卡）",      callback_data="t_physical")],
        [InlineKeyboardButton("📞 聯繫客服（其他地區 / 多國旅行）",  callback_data="cs")],
        [InlineKeyboardButton("❓ 為什麼有些方案比較貴？",           callback_data="pricediff")],
    ])


def usage_only_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 重度｜影片 / 社群 / 大量上傳",   callback_data="usage_heavy")],
        [InlineKeyboardButton("📱 中度｜地圖 / 查資料 / 偶爾社群", callback_data="usage_medium")],
        [InlineKeyboardButton("📷 輕度｜地圖 / 確認行程 / 一般搜尋", callback_data="usage_light")],
        [InlineKeyboardButton("🔙 返回主選單",                       callback_data="main")],
    ])


def days_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗓 1–3 天",   callback_data="d1"),
         InlineKeyboardButton("🗓 4–7 天",   callback_data="d2")],
        [InlineKeyboardButton("🗓 8–15 天",  callback_data="d3"),
         InlineKeyboardButton("🗓 16–30 天", callback_data="d4")],
        [InlineKeyboardButton("🔙 返回",     callback_data="back_usage")],
    ])


def plan_choice_keyboard(rec_fixed: int, rec_daily: float, exceeds: bool) -> InlineKeyboardMarkup:
    daily_str = (
        "最高額度方案" if rec_daily >= 5
        else f"每天 {int(rec_daily)}GB"
    )
    fixed_label = (
        f"💰 固定流量（推薦 {rec_fixed}GB，預估可能不夠用）" if exceeds
        else f"💰 固定流量（推薦 {rec_fixed}GB）"
    )
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(fixed_label,                            callback_data="plan_fixed")],
        [InlineKeyboardButton(f"😌 吃到飽（推薦 {daily_str}）",       callback_data="plan_unlimited")],
        [InlineKeyboardButton("🔙 返回",                              callback_data="back_days")],
    ])


def country_keyboard() -> InlineKeyboardMarkup:
    rows, row = [], []
    for code in POPULAR_COUNTRIES:
        row.append(InlineKeyboardButton(COUNTRY_DISPLAY[code], callback_data=f"c_{code}"))
        if len(row) == 3:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("🌏 更多地區 → 聯繫客服", callback_data="cs")])
    rows.append([InlineKeyboardButton("🔙 返回",               callback_data="back_plan")])
    return InlineKeyboardMarkup(rows)


def product_keyboard(products: list[dict]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(_short_title(p["title"]), callback_data=f"p_{i}")] for i, p in enumerate(products)]
    rows.append([InlineKeyboardButton("🔙 返回", callback_data="back_c")])
    return InlineKeyboardMarkup(rows)


def option_keyboard(options: list[str], rec_idx: int) -> InlineKeyboardMarkup:
    rows = []
    for i, opt in enumerate(options):
        label = f"⭐ {opt}（推薦）" if i == rec_idx else opt
        rows.append([InlineKeyboardButton(label, callback_data=f"o_{i}")])
    rows.append([InlineKeyboardButton("🔙 返回", callback_data="back_p")])
    return InlineKeyboardMarkup(rows)


def result_keyboard(sec_label: str | None) -> InlineKeyboardMarkup:
    rows = []
    if sec_label:
        rows.append([InlineKeyboardButton(f"🔹 第二推薦：{sec_label}", callback_data="sec_rec")])
    rows.append([InlineKeyboardButton("🔙 選其他子方案", callback_data="back_o")])
    rows.append([InlineKeyboardButton("🏠 返回主選單",   callback_data="main")])
    return InlineKeyboardMarkup(rows)


def sec_result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 返回主推薦", callback_data="back_sec")],
        [InlineKeyboardButton("🏠 返回主選單", callback_data="main")],
    ])


# ── 顯示輔助 ──────────────────────────────────────────────────────────────────
async def _show_main(target, is_query=False):
    kw = dict(text=MAIN_MENU_TEXT, reply_markup=main_keyboard(), parse_mode="HTML")
    await (target.edit_message_text(**kw) if is_query else target.reply_text(**kw))


async def _show_days(query, usage: str):
    label = USAGE_LABEL.get(usage, "")
    prefix = f"選擇了 <b>{label}</b>\n\n" if label else ""
    await query.edit_message_text(
        f"{prefix}這次出遊大約幾天？",
        reply_markup=days_keyboard(),
        parse_mode="HTML",
    )


async def _show_plan_choice(query, ud: dict):
    usage    = ud["usage"]
    days_key = ud["days_key"]
    est      = _compute(usage, days_key)
    ud.update(est)

    est_gb    = est["est_gb"]
    rec_fixed = est["rec_fixed_gb"]
    rec_daily = est["rec_daily_gb"]
    exceeds   = est["exceeds_max"]

    daily_str = (
        "最高額度方案" if rec_daily >= 5
        else f"每天 {int(rec_daily)}GB"
    )
    exceed_note = (
        f"\n⚠️ 預估用量 {int(est_gb)}GB 超過目前最大固定方案（50GB），固定流量可能不夠用"
        if exceeds else ""
    )

    text = (
        f"📊 <b>依你的使用習慣估算：</b>\n"
        f"• 使用習慣：{USAGE_LABEL[usage]}\n"
        f"• 旅行天數：{DAYS_LABEL[days_key]}\n"
        f"• 預估需要：約 {int(est_gb)} GB{exceed_note}\n\n"
        f"請選擇方案類型：\n\n"
        f"💰 <b>固定流量（推薦容量：{rec_fixed}GB）</b>\n"
        f"流量彈性使用，整體較划算\n"
        f"⚠️ 用完即無網路，需重新購買方案\n\n"
        f"😌 <b>吃到飽（推薦：{daily_str}）</b>\n"
        f"不需計算流量，較為安心\n"
        f"⚠️ 超量後可能降速，僅適合 LINE 傳文字"
    )
    await query.edit_message_text(
        text,
        reply_markup=plan_choice_keyboard(rec_fixed, rec_daily, exceeds),
        parse_mode="HTML",
    )


async def _show_option_selection(query, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    product = _resolve(ud)
    if not product:
        await _show_main(query, is_query=True); return

    options  = _option1_vals(product)
    plan     = ud.get("plan", "unlimited")
    usage    = ud.get("usage", "")
    target   = ud.get("rec_fixed_gb", ud.get("est_gb", 10)) if plan == "fixed" else ud.get("rec_daily_gb", 2)
    rec      = _rec_idx_by_gb(options, plan, target)
    ud["options"] = options
    ud["rec_idx"] = rec

    usage_label = USAGE_LABEL.get(usage, "")
    days_label  = DAYS_LABEL.get(ud.get("days_key", ""), "")
    header = (
        f"<b>{product['title']}</b>\n"
        f"{usage_label}　{days_label}\n\n"
        "請選擇方案種類（⭐ 為推薦）："
    ) if usage_label else f"<b>{product['title']}</b>\n\n請選擇方案種類："

    await query.edit_message_text(header, reply_markup=option_keyboard(options, rec), parse_mode="HTML")


def _build_result_text(product: dict, opt1: str, plan: str, card_type: str = "esim") -> str:
    table = _price_table(product, opt1)
    warn  = WARN.get(plan, "")
    card  = CARD_LABEL.get(card_type, "")
    return (
        f"✅ <b>{product['title']}</b>\n"
        f"卡別：{card}　方案：{opt1}\n\n"
        f"💰 <b>天數 &amp; 價格</b>\n{table}\n\n"
        f"{warn}\n\n"
        f"<a href='{product['url']}'>👉 前往 WaySim 購買</a>"
    )


def _prepare_sec(ud: dict):
    """跨類型推薦：準備第二推薦的 product + option1（同卡別，另一種計費方式）。"""
    plan      = ud.get("plan", "unlimited")
    country   = ud.get("country", "")
    card_type = ud.get("card_type", "esim")
    sec_plan  = "unlimited" if plan == "fixed" else "fixed"

    sec_products = _products_for(sec_plan, country, card_type)
    if not sec_products:
        ud["sec_handle"] = None; return

    sec_product = sec_products[0]
    sec_opts    = _option1_vals(sec_product)
    target_gb   = ud.get("rec_daily_gb", 2) if sec_plan == "unlimited" else ud.get("rec_fixed_gb", 10)
    sec_rec     = _rec_idx_by_gb(sec_opts, sec_plan, target_gb)

    ud["sec_handle"]  = sec_product["handle"]
    ud["sec_opts"]    = sec_opts
    ud["sec_rec_idx"] = sec_rec
    ud["sec_plan"]    = sec_plan


# ── 處理器 ────────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await _show_main(update.message)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    ud   = context.user_data

    # ── 靜態 ─────────────────────────────────────────────────────────────────
    if data == "main":
        ud.clear()
        await _show_main(query, is_query=True); return

    if data == "cs":
        await query.edit_message_text(CS_TEXT, reply_markup=BACK_TO_MAIN, parse_mode="HTML"); return

    if data == "pricediff":
        await query.edit_message_text(PRICEDIFF_TEXT, reply_markup=BACK_TO_MAIN, parse_mode="HTML"); return

    # ── 實體卡入口：仍需詢問使用習慣以推薦合適流量 ──────────────────────────
    if data == "t_physical":
        ud["card_type"] = "physical"
        await query.edit_message_text(
            PHYSICAL_INTRO_TEXT,
            reply_markup=usage_only_keyboard(),
            parse_mode="HTML",
        ); return

    # ── L1 使用習慣 ───────────────────────────────────────────────────────────
    if data.startswith("usage_"):
        ud["usage"] = data[6:]
        ud.setdefault("card_type", "esim")
        await _show_days(query, ud["usage"]); return

    # ── L2 旅行天數 ───────────────────────────────────────────────────────────
    if data in ("d1", "d2", "d3", "d4"):
        ud["days_key"] = data
        await _show_plan_choice(query, ud); return

    # ── L3 方案類型 ───────────────────────────────────────────────────────────
    if data in ("plan_fixed", "plan_unlimited"):
        ud["plan"] = data[5:]
        await query.edit_message_text("請選擇目的地：", reply_markup=country_keyboard(), parse_mode="HTML"); return

    # ── L4 選國家 ─────────────────────────────────────────────────────────────
    if data.startswith("c_"):
        country = data[2:]
        plan    = ud.get("plan", "unlimited")
        card_type = ud.get("card_type", "esim")
        ud["country"] = country
        products = _products_for(plan, country, card_type)

        if not products:
            card_label = CARD_LABEL.get(card_type, "")
            await query.edit_message_text(
                f"<b>{COUNTRY_DISPLAY.get(country, country)}</b> 目前無「{card_label}」此類型方案，\n"
                f"請 <a href='{LINE_CS}'>聯繫 WaySim 客服</a> 詢問。",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 重新選擇", callback_data="back_plan"),
                    InlineKeyboardButton("📞 聯繫客服", callback_data="cs"),
                ]]),
                parse_mode="HTML",
            ); return

        ud["product_handles"] = [p["handle"] for p in products]
        if len(products) == 1:
            ud["product_idx"] = 0
            await _show_option_selection(query, context)
        else:
            await query.edit_message_text(
                f"<b>{COUNTRY_DISPLAY.get(country, country)}</b> 有以下方案，請選擇：",
                reply_markup=product_keyboard(products),
                parse_mode="HTML",
            )
        return

    # ── L5 選產品 ─────────────────────────────────────────────────────────────
    if data.startswith("p_"):
        ud["product_idx"] = int(data[2:])
        await _show_option_selection(query, context); return

    # ── L6 選方案種類 → 顯示結果 ─────────────────────────────────────────────
    if data.startswith("o_"):
        idx     = int(data[2:])
        options = ud.get("options", [])
        product = _resolve(ud)
        if not product or idx >= len(options):
            await _show_main(query, is_query=True); return

        opt1      = options[idx]
        plan      = ud.get("plan", "unlimited")
        card_type = ud.get("card_type", "esim")
        ud["selected_opt1"] = opt1

        # 準備第二推薦
        _prepare_sec(ud)
        sec_handle = ud.get("sec_handle")
        sec_opts   = ud.get("sec_opts", [])
        sec_rec    = ud.get("sec_rec_idx", 0)

        sec_label = None
        if sec_handle and sec_opts:
            sec_product = _resolve_sec(ud)
            if sec_product:
                sec_label = sec_opts[sec_rec] if sec_rec < len(sec_opts) else sec_opts[0]

        text = _build_result_text(product, opt1, plan, card_type)
        await query.edit_message_text(text, reply_markup=result_keyboard(sec_label), parse_mode="HTML")
        return

    # ── 第二推薦 ──────────────────────────────────────────────────────────────
    if data == "sec_rec":
        sec_product = _resolve_sec(ud)
        sec_opts    = ud.get("sec_opts", [])
        sec_rec     = ud.get("sec_rec_idx", 0)
        sec_plan    = ud.get("sec_plan", "unlimited")
        card_type   = ud.get("card_type", "esim")
        if not sec_product or not sec_opts:
            await _show_main(query, is_query=True); return

        opt1 = sec_opts[sec_rec] if sec_rec < len(sec_opts) else sec_opts[0]
        text = (
            "🔹 <b>第二推薦方案</b>\n\n"
            + _build_result_text(sec_product, opt1, sec_plan, card_type)
        )
        await query.edit_message_text(text, reply_markup=sec_result_keyboard(), parse_mode="HTML")
        return

    # ── 返回主推薦 ────────────────────────────────────────────────────────────
    if data == "back_sec":
        product   = _resolve(ud)
        opt1      = ud.get("selected_opt1")
        plan      = ud.get("plan", "unlimited")
        card_type = ud.get("card_type", "esim")
        if not product or not opt1:
            await _show_main(query, is_query=True); return
        sec_opts  = ud.get("sec_opts", [])
        sec_label = sec_opts[ud.get("sec_rec_idx", 0)] if sec_opts else None
        text = _build_result_text(product, opt1, plan, card_type)
        await query.edit_message_text(text, reply_markup=result_keyboard(sec_label), parse_mode="HTML")
        return

    # ── 返回導航 ──────────────────────────────────────────────────────────────
    if data == "back_usage":
        # 若為實體卡入口，回到 usage_only 子選單；否則回主選單
        if ud.get("card_type") == "physical":
            await query.edit_message_text(
                PHYSICAL_INTRO_TEXT,
                reply_markup=usage_only_keyboard(),
                parse_mode="HTML",
            )
        else:
            await _show_main(query, is_query=True)
        return

    if data == "back_days":
        await _show_days(query, ud.get("usage", "")); return

    if data == "back_plan":
        if ud.get("days_key"):
            await _show_plan_choice(query, ud)
        else:
            await _show_main(query, is_query=True)
        return

    if data == "back_c":
        await query.edit_message_text("請選擇目的地：", reply_markup=country_keyboard(), parse_mode="HTML")
        return

    if data == "back_p":
        plan      = ud.get("plan", "")
        country   = ud.get("country", "")
        card_type = ud.get("card_type", "esim")
        products  = _products_for(plan, country, card_type) if plan and country else []
        if len(products) <= 1:
            await query.edit_message_text("請選擇目的地：", reply_markup=country_keyboard(), parse_mode="HTML")
        else:
            await query.edit_message_text(
                f"<b>{COUNTRY_DISPLAY.get(country, country)}</b> 有以下方案，請選擇：",
                reply_markup=product_keyboard(products),
                parse_mode="HTML",
            )
        return

    if data == "back_o":
        await _show_option_selection(query, context); return


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """記錄錯誤；若是使用者操作引發，嘗試友善提示。"""
    err = context.error
    logger.error("處理更新時發生例外: %s", err)
    logger.error("Traceback:\n%s", "".join(traceback.format_exception(type(err), err, err.__traceback__)))
    try:
        if isinstance(update, Update) and update.callback_query:
            await update.callback_query.answer("發生暫時性錯誤，請再試一次或輸入 /start 重新開始。", show_alert=False)
    except Exception:
        pass


# ── 主程式 ────────────────────────────────────────────────────────────────────
def main() -> None:
    if not TOKEN:
        raise ValueError("請先設定 BOT_TOKEN 環境變數")
    load_products()
    logger.info("已載入 %d 個產品", len(PRODUCTS))
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_error_handler(error_handler)
    logger.info("Bot 已啟動...")
    app.run_polling()


if __name__ == "__main__":
    main()
