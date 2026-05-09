# SME-Eye: Autonomous Secure Operations and Quality Agent

SME-Eye, KOBİ'ler için geliştirilmiş AI destekli güvenli operasyon, lojistik, kalite kontrol, teslimat doğrulama ve iade yönetimi uygulamasıdır.

Gemini karar destek ajanı olarak kullanılır; fakat kritik sipariş durum geçişleri backend tarafındaki güvenli state machine tarafından zorunlu olarak kontrol edilir.

## Türkçe

### Kurulum

Proje klasörüne gir:

```powershell
cd "C:\Users\bedir\OneDrive\Desktop\Hackathon\autonomous-sme-ops"
```

Sanal ortam oluştur:

```powershell
python -m venv .venv
```

Sanal ortamı aktif et:

```powershell
.\.venv\Scripts\activate
```

Bağımlılıkları kur:

```powershell
python -m pip install -r requirements.txt
```

Yerel `.env` dosyası oluştur:

```env
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
```

`.env` dosyasını GitHub'a yükleme. Güvenli örnek dosya olarak `.env.example` kullanılır.

Uygulamayı başlat:

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8010
```

Adresler:

```text
Admin Paneli:     http://127.0.0.1:8010/dashboard
Müşteri Portalı:  http://127.0.0.1:8010/tracking
API Dokümanı:     http://127.0.0.1:8010/docs
```

### Nasıl Kullanılır?

1. Admin panelini aç.
2. `Demo Verisini Yenile` butonuna bas.
3. `Bekliyor` durumundaki bir siparişi seç.
4. `Örnek Notu Doldur` butonuna bas.
5. `Kalite Kontrol` çalıştır.
6. Sipariş onaylanırsa `Kargoya Ver` butonuna bas.
7. `Portalı Aç` butonu ile müşteri portalına geç.
8. Müşteri portalında kargo puanı ve teslimat yorumu gönder.
9. İade gerekiyorsa ayrı `İade Paneli` üzerinden iade talebi oluştur.
10. `Mesaj Paneli` üzerinden AI destek ajanı ile mesajlaş.

### Özellikler

- FastAPI backend
- SQLite + SQLAlchemy ORM
- Pydantic doğrulama
- Gemini destekli kalite kontrol
- AI destekli gecikme mesajı üretimi
- Güvenli teslimat token doğrulaması
- Kargo puanı ve müşteri yorumu
- Ayrı iade paneli
- Müşteri mesaj paneli
- Son işlemler zaman çizelgesi
- El yapımı gıda ürünleriyle demo veri seti

### Güvenlik

- Teslimat ve iade işlemleri `order_id` + `crypto_token` doğrulaması gerektirir.
- Geçersiz token istekleri `403 Forbidden` ile engellenir.
- Hatalı sipariş durum geçişleri `409 Conflict` ile engellenir.
- Gemini JSON çıktısı üretir, fakat nihai güvenlik kontrolü backend state machine tarafından yapılır.
- Gerçek API key yalnızca `.env` içinden okunur.

### Ana Endpointler

```text
GET  /dashboard
GET  /tracking
GET  /api/dashboard
POST /api/demo/reset
POST /api/orders
POST /api/quality-check/{order_id}
POST /api/orders/{order_id}/ship
POST /api/cargo-webhook/simulate
POST /api/tracking/lookup
POST /api/delivery/confirm
POST /api/return/request
POST /api/customer/message
```

## English

### Setup

Open the project directory:

```powershell
cd "C:\Users\bedir\OneDrive\Desktop\Hackathon\autonomous-sme-ops"
```

Create a virtual environment:

```powershell
python -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\activate
```

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Create a local `.env` file:

```env
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
```

Do not commit `.env`. Use `.env.example` as the safe configuration template.

Run the app:

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8010
```

Open:

```text
Admin Dashboard:  http://127.0.0.1:8010/dashboard
Customer Portal:  http://127.0.0.1:8010/tracking
API Docs:         http://127.0.0.1:8010/docs
```

### How to Use

1. Open the admin dashboard.
2. Click `Demo Verisini Yenile`.
3. Select a `Bekliyor` order.
4. Click `Örnek Notu Doldur`.
5. Run `Kalite Kontrol`.
6. If approved, click `Kargoya Ver`.
7. Open the customer portal with `Portalı Aç`.
8. Submit delivery rating and customer feedback.
9. If a return is needed, use the separate return panel.
10. Use the message panel to chat with the AI support agent.

### Features

- FastAPI backend
- SQLite + SQLAlchemy ORM
- Pydantic validation
- Gemini-powered quality control
- AI-generated delay messages
- Secure delivery token verification
- Delivery rating and customer feedback
- Separate return request panel
- Customer support message panel
- Recent activity timeline
- Handmade-food SME demo dataset

### Security

- Delivery and return actions require `order_id` + `crypto_token`.
- Invalid tokens are blocked with `403 Forbidden`.
- Invalid state transitions are blocked with `409 Conflict`.
- Gemini returns structured JSON, but backend state guards remain authoritative.
- Real API keys are loaded only from `.env`.

### Main Endpoints

```text
GET  /dashboard
GET  /tracking
GET  /api/dashboard
POST /api/demo/reset
POST /api/orders
POST /api/quality-check/{order_id}
POST /api/orders/{order_id}/ship
POST /api/cargo-webhook/simulate
POST /api/tracking/lookup
POST /api/delivery/confirm
POST /api/return/request
POST /api/customer/message
```
