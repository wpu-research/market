#!/usr/bin/env python3
"""
@vipvenommarket — Telegram Market/Satis Botu
---------------------------------------------
Ozellikler:
  • /start ile karsilama + ana menu (inline butonlar)
  • Urun listesi (products.json'dan okunur, kod degismeden guncellenir)
  • Urun detayi + adet secimi + sepet
  • Siparis onayi -> SQLite'a kaydedilir, admin'e bildirim gider
  • /siparislerim ile kullanici gecmis siparislerini gorur
  • /admin (sadece admin) bekleyen siparisleri listeler

Sifir bagimlilik: sadece Python 3 standart kutuphanesi.

Kullanim:
  export TELEGRAM_BOT_TOKEN="123456:ABC..."   # @BotFather'dan
  export ADMIN_CHAT_ID="11111111"             # siparis bildirimi gidecek kisi (opsiyonel ama onerilir)
  python3 venom_market_bot.py
"""

import json
import os
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "").strip()

if not BOT_TOKEN:
    sys.exit("HATA: TELEGRAM_BOT_TOKEN ortam degiskenini ayarla.")

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_FILE = os.environ.get("PRODUCTS_FILE", os.path.join(BASE_DIR, "products.json"))
DB_FILE = os.environ.get("ORDERS_DB", os.path.join(BASE_DIR, "orders.db"))

# ------------------------------------------------------------------ altyapi

def tg(method: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(
        f"{TG_API}/{method}", data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=70) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print(f"[TG] {method} hatasi: {e.read().decode()[:200]}", flush=True)
        return {"ok": False}


def load_products() -> list[dict]:
    try:
        with open(PRODUCTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def db() -> sqlite3.Connection:
    db_dir = os.path.dirname(DB_FILE)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            username TEXT,
            product_id TEXT NOT NULL,
            product_name TEXT NOT NULL,
            qty INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            total REAL NOT NULL,
            note TEXT DEFAULT '',
            status TEXT DEFAULT 'bekliyor',
            created_at TEXT NOT NULL
        )
    """)
    return conn


# Kullanici basina gecici durum (adet secimi / not bekleme)
STATE: dict[int, dict] = {}

# ------------------------------------------------------------------ menuler

def main_menu_kb() -> dict:
    return {"inline_keyboard": [
        [{"text": "🛒 Ürünler", "callback_data": "list"}],
        [{"text": "📦 Siparişlerim", "callback_data": "myorders"}],
    ]}


def products_kb() -> dict:
    rows = []
    for p in load_products():
        stok = "" if p.get("stock", 1) else " (stokta yok)"
        fiyat = f"{p['price']:g} {p.get('currency','TL')}" if p.get("price") else "fiyat sor"
        rows.append([{
            "text": f"{p['name']} — {fiyat}{stok}",
            "callback_data": f"p:{p['id']}",
        }])
    rows.append([{"text": "⬅️ Menü", "callback_data": "menu"}])
    return {"inline_keyboard": rows}


def product_detail_kb(pid: str) -> dict:
    qty_row = [{"text": str(n), "callback_data": f"q:{pid}:{n}"} for n in (1, 2, 3, 5, 10)]
    return {"inline_keyboard": [
        qty_row,
        [{"text": "⬅️ Ürünler", "callback_data": "list"}],
    ]}


def confirm_kb(pid: str, qty: int) -> dict:
    return {"inline_keyboard": [
        [{"text": "✅ Siparişi Onayla", "callback_data": f"ok:{pid}:{qty}"}],
        [{"text": "📝 Not ekle", "callback_data": f"note:{pid}:{qty}"},
         {"text": "❌ Vazgeç", "callback_data": "list"}],
    ]}


def get_product(pid: str) -> dict | None:
    return next((p for p in load_products() if str(p["id"]) == str(pid)), None)


# ------------------------------------------------------------------ akislar

def send(chat_id: int, text: str, kb: dict | None = None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if kb:
        payload["reply_markup"] = kb
    tg("sendMessage", payload)


def show_product(chat_id: int, pid: str):
    p = get_product(pid)
    if not p:
        send(chat_id, "Ürün bulunamadı.", products_kb())
        return
    fiyat = f"{p['price']:g} {p.get('currency','TL')}" if p.get("price") else "Fiyat için iletişime geç"
    text = (f"<b>{p['name']}</b>\n"
            f"{p.get('desc','')}\n\n"
            f"Fiyat: <b>{fiyat}</b>\n\n"
            f"Kaç adet istiyorsun?")
    if p.get("photo"):
        tg("sendPhoto", {"chat_id": chat_id, "photo": p["photo"],
                         "caption": text, "parse_mode": "HTML",
                         "reply_markup": product_detail_kb(pid)})
    else:
        send(chat_id, text, product_detail_kb(pid))


def show_confirm(chat_id: int, pid: str, qty: int):
    p = get_product(pid)
    if not p:
        return
    total = p["price"] * qty
    note = STATE.get(chat_id, {}).get("note", "")
    note_line = f"\nNot: {note}" if note else ""
    send(chat_id,
         f"Sipariş özeti:\n\n<b>{p['name']}</b> × {qty}\n"
         f"Toplam: <b>{total:g} {p.get('currency','TL')}</b>{note_line}",
         confirm_kb(pid, qty))


def place_order(chat_id: int, username: str, pid: str, qty: int):
    p = get_product(pid)
    if not p:
        return
    total = p["price"] * qty
    note = STATE.pop(chat_id, {}).get("note", "")
    conn = db()
    cur = conn.execute(
        "INSERT INTO orders (chat_id, username, product_id, product_name, qty, unit_price, total, note, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (chat_id, username, str(pid), p["name"], qty, p["price"], total, note,
         datetime.now().strftime("%Y-%m-%d %H:%M")),
    )
    conn.commit()
    order_id = cur.lastrowid
    conn.close()

    send(chat_id,
         f"✅ Siparişin alındı!\n\nSipariş No: <b>#{order_id}</b>\n"
         f"{p['name']} × {qty} = {total:g} {p.get('currency','TL')}\n\n"
         f"En kısa sürede seninle iletişime geçilecek.",
         main_menu_kb())

    if ADMIN_CHAT_ID:
        send(int(ADMIN_CHAT_ID),
             f"🔔 <b>Yeni sipariş #{order_id}</b>\n"
             f"Müşteri: @{username} (id {chat_id})\n"
             f"{p['name']} × {qty} = {total:g} {p.get('currency','TL')}\n"
             f"Not: {note or '-'}")


def show_my_orders(chat_id: int):
    conn = db()
    rows = conn.execute(
        "SELECT id, product_name, qty, total, status, created_at FROM orders "
        "WHERE chat_id=? ORDER BY id DESC LIMIT 10", (chat_id,)).fetchall()
    conn.close()
    if not rows:
        send(chat_id, "Henüz siparişin yok.", main_menu_kb())
        return
    lines = [f"#{r[0]} · {r[1]} × {r[2]} = {r[3]:g} TL · <i>{r[4]}</i> · {r[5]}" for r in rows]
    send(chat_id, "📦 Son siparişlerin:\n\n" + "\n".join(lines), main_menu_kb())


def show_admin(chat_id: int):
    conn = db()
    rows = conn.execute(
        "SELECT id, username, product_name, qty, total, created_at FROM orders "
        "WHERE status='bekliyor' ORDER BY id DESC LIMIT 20").fetchall()
    conn.close()
    if not rows:
        send(chat_id, "Bekleyen sipariş yok.")
        return
    lines = [f"#{r[0]} · @{r[1]} · {r[2]} × {r[3]} = {r[4]:g} TL · {r[5]}" for r in rows]
    send(chat_id, "⏳ Bekleyen siparişler:\n\n" + "\n".join(lines))


# ------------------------------------------------------------------ ana dongu

def handle_message(msg: dict):
    chat_id = msg["chat"]["id"]
    username = msg["from"].get("username") or msg["from"].get("first_name", "?")
    text = msg.get("text", "")

    # Not bekleme modunda serbest metin
    st = STATE.get(chat_id)
    if st and st.get("await") == "note":
        st["note"] = text[:200]
        st["await"] = None
        show_confirm(chat_id, st["pid"], st["qty"])
        return

    if text.startswith("/start"):
        send(chat_id,
             "🐍 <b>VIP Venom Market</b>'e hoş geldin!\n\n"
             "📍 Teslimat: KKTC Girne · Lefkoşa · Mağusa (toplu alımlarda)\n\n"
             "Aşağıdan ürünlere göz atabilirsin.",
             main_menu_kb())
    elif text.startswith("/siparislerim"):
        show_my_orders(chat_id)
    elif text.startswith("/admin") and str(chat_id) == ADMIN_CHAT_ID:
        show_admin(chat_id)
    else:
        send(chat_id, "Menüden seçim yapabilirsin 👇", main_menu_kb())


def handle_callback(cb: dict):
    chat_id = cb["message"]["chat"]["id"]
    username = cb["from"].get("username") or cb["from"].get("first_name", "?")
    data = cb["data"]
    tg("answerCallbackQuery", {"callback_query_id": cb["id"]})

    if data == "menu":
        send(chat_id, "Ana menü:", main_menu_kb())
    elif data == "list":
        STATE.pop(chat_id, None)
        send(chat_id, "🛒 Ürünlerimiz:", products_kb())
    elif data == "myorders":
        show_my_orders(chat_id)
    elif data.startswith("p:"):
        show_product(chat_id, data[2:])
    elif data.startswith("q:"):
        _, pid, qty = data.split(":")
        STATE[chat_id] = {"pid": pid, "qty": int(qty), "note": ""}
        show_confirm(chat_id, pid, int(qty))
    elif data.startswith("note:"):
        _, pid, qty = data.split(":")
        STATE[chat_id] = {"pid": pid, "qty": int(qty),
                          "note": STATE.get(chat_id, {}).get("note", ""), "await": "note"}
        send(chat_id, "📝 Notunu yaz (adres, renk, iletişim vs.):")
    elif data.startswith("ok:"):
        _, pid, qty = data.split(":")
        place_order(chat_id, username, pid, int(qty))


def main():
    me = tg("getMe").get("result", {})
    print(f"Bot aktif: @{me.get('username')} — ürün sayısı: {len(load_products())}", flush=True)
    db().close()  # tabloyu olustur

    offset = 0
    while True:
        resp = tg("getUpdates", {"offset": offset, "timeout": 60,
                                 "allowed_updates": ["message", "callback_query"]})
        if not resp.get("ok"):
            time.sleep(5)
            continue
        for upd in resp.get("result", []):
            offset = upd["update_id"] + 1
            try:
                if "message" in upd:
                    handle_message(upd["message"])
                elif "callback_query" in upd:
                    handle_callback(upd["callback_query"])
            except Exception as e:
                print(f"[HATA] {e}", flush=True)


if __name__ == "__main__":
    main()
