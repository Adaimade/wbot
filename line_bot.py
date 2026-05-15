"""WaySim LINE Bot (Messaging API + Flask webhook)。

獨立於 Telegram 版（bot.py）：兩者可同時運行，共用 products_data.json。
推薦邏輯放在 core.py，本檔只負責 LINE UI 與狀態流。

部署：Zeabur 設定 web 服務，環境變數 LINE_CHANNEL_ACCESS_TOKEN + LINE_CHANNEL_SECRET
本機開發：搭配 ngrok 將 :8080 對外暴露 → 設為 LINE Developers Console 的 Webhook URL
"""

import os
import sys
import logging
from flask import Flask, request, abort

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage,
    QuickReply, QuickReplyItem, PostbackAction,
)
from linebot.v3.webhooks import (
    MessageEvent, TextMessageContent, PostbackEvent, FollowEvent,
)

import core

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
CHANNEL_SECRET       = os.getenv("LINE_CHANNEL_SECRET", "")

if not CHANNEL_ACCESS_TOKEN or not CHANNEL_SECRET:
    logger.warning("LINE_CHANNEL_ACCESS_TOKEN 或 LINE_CHANNEL_SECRET 尚未設定")

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler       = WebhookHandler(CHANNEL_SECRET or "placeholder")

core.load_products()
logger.info("已載入 %d 個產品", len(core.PRODUCTS))

app = Flask(__name__)

# ── 使用者狀態（記憶體；Zeabur 重啟即清空，用戶重新 /start 即可）─────────────
USER_STATE: dict[str, dict] = {}


def _state(user_id: str) -> dict:
    if user_id not in USER_STATE:
        USER_STATE[user_id] = {}
    return USER_STATE[user_id]


# ── Quick Reply 輔助 ─────────────────────────────────────────────────────────
def qr(items: list[tuple[str, str]]) -> QuickReply:
    """items: [(label, postback_data)]。LINE Quick Reply label 上限 20 字元。"""
    return QuickReply(items=[
        QuickReplyItem(action=PostbackAction(
            label=label[:20], data=data, display_text=label,
        ))
        for label, data in items[:13]  # LINE 上限 13 個
    ])


def reply(reply_token: str, text: str, quick: QuickReply | None = None):
    if not CHANNEL_ACCESS_TOKEN:
        logger.warning("缺少 access token，無法 reply")
        return
    msg = TextMessage(text=text[:4900], quick_reply=quick)
    with ApiClient(configuration) as api:
        MessagingApi(api).reply_message_with_http_info(
            ReplyMessageRequest(reply_token=reply_token, messages=[msg])
        )


# ── 頁面渲染 ─────────────────────────────────────────────────────────────────
def show_main(reply_token: str):
    items = [
        ("📸 重度｜影片社群",   "usage_heavy"),
        ("📱 中度｜地圖查詢",   "usage_medium"),
        ("📷 輕度｜地圖瀏覽",   "usage_light"),
        ("👴 不裝 eSIM 要實體", "t_physical"),
        ("📞 客服 / 其他地區",  "cs"),
        ("❓ 方案差異",         "pricediff"),
    ]
    reply(reply_token, core.MAIN_MENU_TEXT_PLAIN, qr(items))


def show_usage_for_physical(reply_token: str):
    items = [
        ("📸 重度｜影片社群", "usage_heavy"),
        ("📱 中度｜地圖查詢", "usage_medium"),
        ("📷 輕度｜地圖瀏覽", "usage_light"),
        ("🏠 主選單",         "main"),
    ]
    reply(reply_token, core.PHYSICAL_INTRO_TEXT_PLAIN, qr(items))


def show_days(reply_token: str, usage: str):
    label = core.USAGE_LABEL.get(usage, "")
    prefix = f"選擇了 {label}\n\n" if label else ""
    items = [
        ("🗓 1–3 天",   "d1"),
        ("🗓 4–7 天",   "d2"),
        ("🗓 8–15 天",  "d3"),
        ("🗓 16–30 天", "d4"),
        ("🔙 返回",      "back_usage"),
    ]
    reply(reply_token, f"{prefix}這次出遊大約幾天？", qr(items))


def show_plan_choice(reply_token: str, ud: dict):
    usage    = ud["usage"]
    days_key = ud["days_key"]
    est      = core.compute(usage, days_key)
    ud.update(est)

    est_gb    = est["est_gb"]
    rec_fixed = est["rec_fixed_gb"]
    rec_daily = est["rec_daily_gb"]
    exceeds   = est["exceeds_max"]

    daily_str = "最高額度方案" if rec_daily >= 5 else f"每天 {int(rec_daily)}GB"
    exceed_note = (
        f"\n⚠️ 預估用量 {int(est_gb)}GB 超過目前最大固定方案（50GB），固定流量可能不夠用"
        if exceeds else ""
    )

    text = (
        f"📊 依你的使用習慣估算：\n"
        f"• 使用習慣：{core.USAGE_LABEL[usage]}\n"
        f"• 旅行天數：{core.DAYS_LABEL[days_key]}\n"
        f"• 預估需要：約 {int(est_gb)} GB{exceed_note}\n\n"
        f"請選擇方案類型：\n\n"
        f"💰 固定流量（推薦容量：{rec_fixed}GB）\n"
        f"流量彈性使用，整體較划算\n"
        f"⚠️ 用完即無網路，需重新購買方案\n\n"
        f"😌 吃到飽（推薦：{daily_str}）\n"
        f"不需計算流量，較為安心\n"
        f"⚠️ 超量後可能降速，僅適合 LINE 傳文字"
    )
    fixed_label = (
        f"💰 固定 {rec_fixed}GB（不夠用）" if exceeds
        else f"💰 固定 {rec_fixed}GB"
    )
    items = [
        (fixed_label,                "plan_fixed"),
        (f"😌 吃到飽 {daily_str}",  "plan_unlimited"),
        ("🔙 返回",                  "back_days"),
    ]
    reply(reply_token, text, qr(items))


def show_country(reply_token: str):
    # 12 國家 + 更多地區 = 13（LINE Quick Reply 上限）
    items = [(core.COUNTRY_DISPLAY[c], f"c_{c}") for c in core.POPULAR_COUNTRIES]
    items.append(("🌏 更多地區→客服", "cs"))
    reply(
        reply_token,
        "請選擇目的地：\n（其他地區請點「更多地區→客服」；想重選請傳 /start）",
        qr(items),
    )


def show_product_select(reply_token: str, products: list[dict], country: str):
    text = f"{core.COUNTRY_DISPLAY.get(country, country)} 有以下方案，請選擇："
    items = [(core.short_title(p["title"]), f"p_{i}") for i, p in enumerate(products)]
    items.append(("🔙 返回國家", "back_c"))
    items.append(("🏠 主選單",   "main"))
    reply(reply_token, text, qr(items))


def show_options(reply_token: str, ud: dict):
    product = core.resolve_product(ud)
    if not product:
        return show_main(reply_token)

    options = core.option1_vals(product)
    plan    = ud.get("plan", "unlimited")
    target  = (
        ud.get("rec_fixed_gb", ud.get("est_gb", 10))
        if plan == "fixed"
        else ud.get("rec_daily_gb", 2)
    )
    rec = core.rec_idx_by_gb(options, plan, target)
    ud["options"] = options
    ud["rec_idx"] = rec

    usage_label = core.USAGE_LABEL.get(ud.get("usage", ""), "")
    days_label  = core.DAYS_LABEL.get(ud.get("days_key", ""), "")
    header = (
        f"{product['title']}\n{usage_label}　{days_label}\n\n請選擇方案種類（⭐ 為推薦）："
        if usage_label
        else f"{product['title']}\n\n請選擇方案種類："
    )

    items: list[tuple[str, str]] = []
    for i, opt in enumerate(options):
        label = f"⭐ {opt}" if i == rec else opt
        items.append((label, f"o_{i}"))
    items.append(("🔙 返回",   "back_p"))
    items.append(("🏠 主選單", "main"))
    reply(reply_token, header, qr(items))


def show_result(reply_token: str, ud: dict, opt_idx: int | None):
    options = ud.get("options", [])
    product = core.resolve_product(ud)
    if not product:
        return show_main(reply_token)

    if opt_idx is not None:
        if opt_idx >= len(options):
            return show_main(reply_token)
        opt1 = options[opt_idx]
        ud["selected_opt1"] = opt1
        core.prepare_sec(ud)
    else:
        opt1 = ud.get("selected_opt1")
        if not opt1:
            return show_main(reply_token)

    plan      = ud.get("plan", "unlimited")
    card_type = ud.get("card_type", "esim")
    text      = core.build_result_text_plain(product, opt1, plan, card_type)

    items: list[tuple[str, str]] = []
    sec_handle = ud.get("sec_handle")
    sec_opts   = ud.get("sec_opts", [])
    sec_rec    = ud.get("sec_rec_idx", 0)
    if sec_handle and sec_opts:
        sec_label = sec_opts[sec_rec] if sec_rec < len(sec_opts) else sec_opts[0]
        items.append((f"🔹 第二推薦：{sec_label}", "sec_rec"))
    items.append(("🔙 選其他子方案", "back_o"))
    items.append(("🏠 主選單",       "main"))
    reply(reply_token, text, qr(items))


def show_sec(reply_token: str, ud: dict):
    sec_product = core.resolve_sec(ud)
    sec_opts    = ud.get("sec_opts", [])
    sec_rec     = ud.get("sec_rec_idx", 0)
    sec_plan    = ud.get("sec_plan", "unlimited")
    card_type   = ud.get("card_type", "esim")
    if not sec_product or not sec_opts:
        return show_main(reply_token)

    opt1 = sec_opts[sec_rec] if sec_rec < len(sec_opts) else sec_opts[0]
    text = "🔹 第二推薦方案\n\n" + core.build_result_text_plain(
        sec_product, opt1, sec_plan, card_type
    )
    items = [
        ("🔙 返回主推薦", "back_sec"),
        ("🏠 主選單",     "main"),
    ]
    reply(reply_token, text, qr(items))


# ── Dispatch（postback handler）──────────────────────────────────────────────
def dispatch(reply_token: str, user_id: str, data: str):
    ud = _state(user_id)
    try:
        if data == "main":
            ud.clear()
            return show_main(reply_token)
        if data == "cs":
            return reply(reply_token, core.CS_TEXT_PLAIN,
                         qr([("🏠 主選單", "main")]))
        if data == "pricediff":
            return reply(reply_token, core.PRICEDIFF_TEXT_PLAIN,
                         qr([("🏠 主選單", "main")]))
        if data == "t_physical":
            ud["card_type"] = "physical"
            return show_usage_for_physical(reply_token)
        if data.startswith("usage_"):
            ud["usage"] = data[6:]
            ud.setdefault("card_type", "esim")
            return show_days(reply_token, ud["usage"])
        if data in ("d1", "d2", "d3", "d4"):
            ud["days_key"] = data
            return show_plan_choice(reply_token, ud)
        if data in ("plan_fixed", "plan_unlimited"):
            ud["plan"] = data[5:]
            return show_country(reply_token)
        if data.startswith("c_"):
            country   = data[2:]
            plan      = ud.get("plan", "unlimited")
            card_type = ud.get("card_type", "esim")
            ud["country"] = country
            products = core.products_for(plan, country, card_type)
            if not products:
                card = core.CARD_LABEL.get(card_type, "")
                return reply(
                    reply_token,
                    f"{core.COUNTRY_DISPLAY.get(country, country)} 目前無「{card}」此類型方案，"
                    f"請聯繫 WaySim 客服 @waysim",
                    qr([("📞 聯繫客服", "cs"), ("🏠 主選單", "main")]),
                )
            ud["product_handles"] = [p["handle"] for p in products]
            if len(products) == 1:
                ud["product_idx"] = 0
                return show_options(reply_token, ud)
            return show_product_select(reply_token, products, country)
        if data.startswith("p_"):
            ud["product_idx"] = int(data[2:])
            return show_options(reply_token, ud)
        if data.startswith("o_"):
            return show_result(reply_token, ud, int(data[2:]))
        if data == "sec_rec":
            return show_sec(reply_token, ud)
        if data == "back_sec":
            return show_result(reply_token, ud, None)
        if data == "back_usage":
            if ud.get("card_type") == "physical":
                return show_usage_for_physical(reply_token)
            return show_main(reply_token)
        if data == "back_days":
            return show_days(reply_token, ud.get("usage", ""))
        if data == "back_plan":
            if ud.get("days_key"):
                return show_plan_choice(reply_token, ud)
            return show_main(reply_token)
        if data == "back_c":
            return show_country(reply_token)
        if data == "back_p":
            plan      = ud.get("plan", "")
            country   = ud.get("country", "")
            card_type = ud.get("card_type", "esim")
            products  = core.products_for(plan, country, card_type) if plan and country else []
            if len(products) <= 1:
                return show_country(reply_token)
            return show_product_select(reply_token, products, country)
        if data == "back_o":
            return show_options(reply_token, ud)

        logger.warning("未知 postback data: %s", data)
        return show_main(reply_token)
    except Exception:
        logger.exception("dispatch 發生錯誤")
        try:
            reply(reply_token, "發生暫時性錯誤，請傳 /start 重新開始。",
                  qr([("🏠 主選單", "main")]))
        except Exception:
            pass


# ── Webhook 路由 ─────────────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def health():
    return "WaySim LINE Bot OK", 200


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body      = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logger.warning("Webhook 簽章不正確")
        abort(400)
    return "OK"


@handler.add(FollowEvent)
def on_follow(event):
    user_id = getattr(event.source, "user_id", None)
    if user_id:
        USER_STATE[user_id] = {}
    show_main(event.reply_token)


@handler.add(MessageEvent, message=TextMessageContent)
def on_text(event):
    user_id = getattr(event.source, "user_id", None) or "anon"
    text = (event.message.text or "").strip().lower()
    if text in ("/start", "start", "開始", "選單", "menu"):
        USER_STATE[user_id] = {}
    show_main(event.reply_token)


@handler.add(PostbackEvent)
def on_postback(event):
    user_id = getattr(event.source, "user_id", None) or "anon"
    dispatch(event.reply_token, user_id, event.postback.data)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
