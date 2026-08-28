# VIP Venom Market Bot — Railway Kurulumu

## 1. Bu klasörü GitHub'a yükle
Yeni bir repo aç, bu 4 dosyayı (venom_market_bot.py, products.json, Procfile, runtime.txt) push et.

## 2. Railway'de servis oluştur
- railway.app → New Project → Deploy from GitHub repo → repoyu seç.
- Deploy tamamlanınca Settings → Start Command boşsa `python3 venom_market_bot.py` yaz
  (Procfile varsa otomatik algılar).

## 3. Ortam değişkenleri (Variables sekmesi)
- TELEGRAM_BOT_TOKEN = BotFather token'ı
- ADMIN_CHAT_ID      = arkadaşının chat id'si
- ORDERS_DB          = /data/orders.db

## 4. Volume ekle (siparişler silinmesin diye)
- Servis → Settings → Volumes → Add Volume → Mount path: /data
- Bu olmadan her deploy'da sipariş geçmişi sıfırlanır.

## 5. Test
Deploy loglarında "Bot aktif: @..." yazısını gör, Telegram'dan /start at.

## Ürün güncelleme
products.json'u repoda düzenleyip push et — Railway otomatik yeniden deploy eder.
