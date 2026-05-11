from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, text
from sqlalchemy.orm import Session, joinedload

from ai_agent import AIConfigurationError, AIServiceError, GeminiAgent
from database import Base, SessionLocal, engine, get_db
from models import (
    CargoDelayRequest,
    AdminMessageApprovalRequest,
    AdminDirectMessageRequest,
    CustomerMessageRequest,
    DeliveryConfirmRequest,
    EventLog,
    Order,
    OrderCreate,
    OrderStatus,
    Product,
    QualityCheckRequest,
    ReturnRequest,
    TrackingLookupRequest,
    utc_now,
)


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
agent = GeminiAgent()

ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.QUALITY_CHECK, OrderStatus.APPROVED},
    OrderStatus.QUALITY_CHECK: {OrderStatus.APPROVED},
    OrderStatus.APPROVED: {OrderStatus.SHIPPED},
    OrderStatus.SHIPPED: {OrderStatus.DELAYED, OrderStatus.DELIVERED, OrderStatus.RETURN_INITIATED},
    OrderStatus.DELAYED: {OrderStatus.DELIVERED, OrderStatus.RETURN_INITIATED},
    OrderStatus.DELIVERED: {OrderStatus.RETURN_INITIATED},
    OrderStatus.RETURN_INITIATED: set(),
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_sqlite_schema()
    seed_database()
    yield


app = FastAPI(
    title="SME-Eye: Autonomous Secure Operations and Quality Agent",
    version="1.0.0",
    lifespan=lifespan,
)


def ensure_sqlite_schema() -> None:
    """Add lightweight demo columns for existing SQLite databases."""
    if not str(engine.url).startswith("sqlite"):
        return

    with engine.begin() as connection:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(orders)")).fetchall()}
        if "public_order_code" not in columns:
            connection.execute(text("ALTER TABLE orders ADD COLUMN public_order_code VARCHAR(80)"))
        if "origin_city" not in columns:
            connection.execute(text("ALTER TABLE orders ADD COLUMN origin_city VARCHAR(80) DEFAULT 'İstanbul'"))
        if "destination_city" not in columns:
            connection.execute(text("ALTER TABLE orders ADD COLUMN destination_city VARCHAR(80) DEFAULT 'İstanbul'"))


def make_public_order_code(order_id: int, customer_name: str = "") -> str:
    seed = f"{order_id}:{customer_name}:SME-EYE".encode("utf-8")
    fingerprint = hashlib.sha256(seed).hexdigest()[:10].upper()
    return f"SME-TR-2026-OPS-{order_id:06d}-{fingerprint}"


def seed_database() -> None:
    """Seed a small demo dataset only when the database is empty."""
    db = SessionLocal()
    try:
        if db.query(Product).count() > 0:
            return
        seed_demo_data(db)
        db.commit()
    finally:
        db.close()


def seed_demo_data(db: Session) -> None:
    """Create a Turkish handmade-food demo dataset with ready-to-test orders."""
    products = [
        Product(name="Ev Yapımı Çilek Reçeli", stock_quantity=42, critical_threshold=8, price=145.00),
        Product(name="Köy Peyniri", stock_quantity=18, critical_threshold=6, price=260.00),
        Product(name="Taş Değirmen Erişte", stock_quantity=31, critical_threshold=7, price=120.00),
        Product(name="Anne Usulü Tarhana", stock_quantity=9, critical_threshold=10, price=135.00),
        Product(name="Soğuk Sıkım Zeytinyağı", stock_quantity=22, critical_threshold=5, price=390.00),
        Product(name="El Açması Baklava", stock_quantity=14, critical_threshold=4, price=520.00),
        Product(name="Doğal Domates Salçası", stock_quantity=27, critical_threshold=6, price=180.00),
        Product(name="Kuru İncir Paketi", stock_quantity=36, critical_threshold=8, price=210.00),
        Product(name="Köy Yumurtası Kolisi", stock_quantity=7, critical_threshold=6, price=165.00),
        Product(name="El Yapımı Nar Ekşisi", stock_quantity=12, critical_threshold=5, price=155.00),
    ]
    db.add_all(products)
    db.flush()

    demo_orders = [
        ("Ayşe Yılmaz", "+90 555 100 1001", products[0], OrderStatus.PENDING, None, "Bursa", "Ankara"),
        ("Mehmet Kaya", "+90 555 100 1002", products[1], OrderStatus.PENDING, None, "Balıkesir", "İstanbul"),
        ("Zeynep Demir", "+90 555 100 1003", products[2], OrderStatus.APPROVED, "SME-EYE-DEMO-0003", "Konya", "İzmir"),
        ("Can Arslan", "+90 555 100 1004", products[3], OrderStatus.SHIPPED, "SME-EYE-DEMO-0004", "Kahramanmaraş", "Antalya"),
        ("Elif Şahin", "+90 555 100 1005", products[4], OrderStatus.DELAYED, "SME-EYE-DEMO-0005", "Aydın", "Trabzon"),
        ("Burak Çelik", "+90 555 100 1006", products[5], OrderStatus.SHIPPED, "SME-EYE-DEMO-0006", "Gaziantep", "Eskişehir"),
        ("Derya Koç", "+90 555 100 1007", products[6], OrderStatus.APPROVED, "SME-EYE-DEMO-0007", "İzmir", "Samsun"),
        ("Kerem Aydın", "+90 555 100 1008", products[7], OrderStatus.SHIPPED, "SME-EYE-DEMO-0008", "Aydın", "Kayseri"),
        ("Seda Öz", "+90 555 100 1009", products[8], OrderStatus.DELIVERED, "SME-EYE-DEMO-0009", "Bolu", "Ankara"),
        ("Emre Aksoy", "+90 555 100 1010", products[9], OrderStatus.RETURN_INITIATED, "SME-EYE-DEMO-0010", "Adana", "İstanbul"),
    ]

    for customer_name, customer_phone, product, status_value, demo_token, origin_city, destination_city in demo_orders:
        order = Order(
            customer_name=customer_name,
            customer_phone=customer_phone,
            product_id=product.id,
            status=status_value,
            crypto_token=demo_token,
            origin_city=origin_city,
            destination_city=destination_city,
        )
        db.add(order)
        db.flush()
        order.public_order_code = make_public_order_code(order.id, customer_name)
        log_event(
            db,
            order.id,
            f"Demo sipariş {status_value.value} durumunda oluşturuldu.",
            {
                "kaynak": "demo_seed",
                "durum": status_value.value,
                "teslimat_tokeni": demo_token,
                "gonderen_sehir": origin_city,
                "gidecegi_sehir": destination_city,
            },
        )
        if status_value == OrderStatus.DELAYED:
            log_event(
                db,
                order.id,
                "Acil işlem gerekiyor: gecikme tespit edildi.",
                {
                    "customer_message": "Gecikme için otomatik bilgilendirme hazırlandı. Operasyon ekibi teslimat sürecini düzeltecek.",
                    "severity": "high",
                },
            )
            log_event(
                db,
                order.id,
                "Destek yanıtı onaylandı ve müşteriye gönderildi.",
                {
                    "role": "agent",
                    "reply": "Kargonuzda gecikme tespit edildi. Operasyon ekibi teslimat sürecini düzeltmek için aksiyon aldı.",
                    "intent": "cargo_delay_auto_notice",
                },
            )


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_delivery_token(db: Session) -> tuple[str, str]:
    """Return a secure token and its fingerprint for audit display."""
    for _ in range(5):
        plaintext = secrets.token_urlsafe(32)
        exists = db.query(Order).filter(Order.crypto_token == plaintext).first()
        if not exists:
            return plaintext, token_digest(plaintext)
    raise HTTPException(status_code=500, detail="Benzersiz teslimat tokeni üretilemedi.")


def verify_delivery_token(order: Order, provided_token: str) -> bool:
    if not order.crypto_token:
        return False
    provided_token = provided_token.strip()
    return hmac.compare_digest(order.crypto_token, provided_token) or hmac.compare_digest(
        order.crypto_token,
        token_digest(provided_token),
    )


def is_sha256_hex(value: str | None) -> bool:
    if not value or len(value) != 64:
        return False
    return all(char in "0123456789abcdefABCDEF" for char in value)


def enforce_transition(order: Order, new_status: OrderStatus) -> None:
    if order.status == new_status:
        return

    allowed = ALLOWED_TRANSITIONS.get(order.status, set())
    if new_status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Geçersiz durum geçişi: {order.status.value} -> {new_status.value}",
        )

    order.status = new_status
    order.updated_at = utc_now()


def log_event(db: Session, order_id: int, description: str, ai_log: dict[str, Any] | None = None) -> EventLog:
    event = EventLog(
        order_id=order_id,
        event_description=description,
        ai_decision_log=json.dumps(ai_log or {}, ensure_ascii=False, default=str),
    )
    db.add(event)
    return event


def get_order_or_404(db: Session, order_id: int) -> Order:
    order = (
        db.query(Order)
        .options(joinedload(Order.product))
        .filter(Order.id == order_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sipariş bulunamadı.")
    return order


def serialize_product(product: Product) -> dict[str, Any]:
    return {
        "id": product.id,
        "name": product.name,
        "stock_quantity": product.stock_quantity,
        "critical_threshold": product.critical_threshold,
        "price": float(product.price),
        "is_critical": product.stock_quantity <= product.critical_threshold,
    }


def serialize_order(order: Order, *, include_phone: bool = True) -> dict[str, Any]:
    token_is_digest = is_sha256_hex(order.crypto_token)
    alert_level = "normal"
    alert_reason = ""
    if order.status in {OrderStatus.DELAYED, OrderStatus.RETURN_INITIATED}:
        alert_level = "high"
        alert_reason = "Acil işlem gerekiyor: gecikme veya iade riski var."
    elif order.product and order.product.stock_quantity <= order.product.critical_threshold:
        alert_level = "warning"
        alert_reason = "Kritik stok seviyesine yaklaşıldı."
    elif order.status == OrderStatus.QUALITY_CHECK:
        alert_level = "warning"
        alert_reason = "Kalite kontrol yeniden işlem bekliyor."

    data = {
        "id": order.id,
        "public_order_code": order.public_order_code or make_public_order_code(order.id, order.customer_name),
        "customer_name": order.customer_name,
        "product_id": order.product_id,
        "product": serialize_product(order.product) if order.product else None,
        "status": order.status.value,
        "origin_city": order.origin_city or "İstanbul",
        "destination_city": order.destination_city or "İstanbul",
        "alert_level": alert_level,
        "alert_reason": alert_reason,
        "crypto_token_issued": bool(order.crypto_token),
        "delivery_token": order.crypto_token if order.crypto_token and not token_is_digest else None,
        "token_fingerprint": (
            order.crypto_token[:12]
            if token_is_digest
            else token_digest(order.crypto_token)[:12]
            if order.crypto_token
            else None
        ),
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
    }
    if include_phone:
        data["customer_phone"] = order.customer_phone
    return data


def serialize_log(event: EventLog) -> dict[str, Any]:
    try:
        ai_log = json.loads(event.ai_decision_log)
    except json.JSONDecodeError:
        ai_log = {"raw": event.ai_decision_log}

    return {
        "id": event.id,
        "order_id": event.order_id,
        "event_description": event.event_description,
        "ai_decision_log": ai_log,
        "timestamp": event.timestamp.isoformat(),
    }


def serialize_activity(event: EventLog) -> dict[str, Any]:
    try:
        ai_log = json.loads(event.ai_decision_log)
    except json.JSONDecodeError:
        ai_log = {}

    detail = (
        ai_log.get("customer_message")
        or ai_log.get("reply")
        or ai_log.get("reason")
        or ai_log.get("message")
        or ""
    )
    description_lower = event.event_description.lower()
    severity = ai_log.get("severity") or "normal"
    if any(marker in description_lower for marker in ["gecik", "iade", "engellendi", "acil"]):
        severity = "high"
    elif any(marker in description_lower for marker in ["kalite", "stok", "uyarı"]):
        severity = "warning"
    order = event.order
    return {
        "id": event.id,
        "order_id": event.order_id,
        "public_order_code": order.public_order_code or make_public_order_code(order.id, order.customer_name) if order else f"SME-ORDER-{event.order_id}",
        "origin_city": order.origin_city or "İstanbul" if order else "-",
        "destination_city": order.destination_city or "İstanbul" if order else "-",
        "description": event.event_description,
        "detail": detail,
        "severity": severity,
        "timestamp": event.timestamp.isoformat(),
    }


def serialize_customer_messages(order_id: int, db: Session) -> list[dict[str, Any]]:
    events = (
        db.query(EventLog)
        .filter(EventLog.order_id == order_id)
        .filter(
            EventLog.event_description.in_(
                [
                    "Müşteri mesajı alındı.",
                    "Otomatik inceleme mesajı müşteriye gönderildi.",
                    "Destek yanıtı onaylandı ve müşteriye gönderildi.",
                    "Yetkili müşteriye doğrudan mesaj gönderdi.",
                ]
            )
        )
        .order_by(EventLog.timestamp.asc())
        .all()
    )
    messages: list[dict[str, Any]] = []
    for event in events:
        try:
            payload = json.loads(event.ai_decision_log)
        except json.JSONDecodeError:
            payload = {}
        messages.append(
            {
                "id": event.id,
                "role": payload.get("role", "system"),
                "message": payload.get("message") or payload.get("reply") or "",
                "timestamp": event.timestamp.isoformat(),
            }
        )
    return messages


def serialize_pending_message(event: EventLog) -> dict[str, Any]:
    try:
        payload = json.loads(event.ai_decision_log)
    except json.JSONDecodeError:
        payload = {}

    order = event.order
    return {
        "id": event.id,
        "order_id": event.order_id,
        "public_order_code": order.public_order_code or make_public_order_code(order.id, order.customer_name) if order else f"SME-ORDER-{event.order_id}",
        "customer_name": order.customer_name if order else "",
        "product_name": order.product.name if order and order.product else "",
        "message": payload.get("message", ""),
        "draft_reply": payload.get("draft_reply", ""),
        "intent": payload.get("intent", ""),
        "timestamp": event.timestamp.isoformat(),
    }


def dashboard_payload(db: Session) -> dict[str, Any]:
    orders = (
        db.query(Order)
        .options(joinedload(Order.product))
        .order_by(Order.updated_at.desc())
        .all()
    )
    products = db.query(Product).order_by(Product.name.asc()).all()
    logs = (
        db.query(EventLog)
        .options(joinedload(EventLog.order).joinedload(Order.product))
        .order_by(EventLog.timestamp.desc())
        .limit(30)
        .all()
    )
    delayed_orders = [order for order in orders if order.status == OrderStatus.DELAYED]
    critical_products = [product for product in products if product.stock_quantity <= product.critical_threshold]
    pending_message_events = (
        db.query(EventLog)
        .options(joinedload(EventLog.order).joinedload(Order.product))
        .filter(EventLog.event_description == "Yanıt onay bekliyor.")
        .order_by(EventLog.timestamp.desc())
        .all()
    )

    stats = {
        "total_orders": db.query(func.count(Order.id)).scalar() or 0,
        "critical_stock_alerts": (
            db.query(func.count(Product.id))
            .filter(Product.stock_quantity <= Product.critical_threshold)
            .scalar()
            or 0
        ),
        "delayed_shipments": (
            db.query(func.count(Order.id))
            .filter(Order.status == OrderStatus.DELAYED)
            .scalar()
            or 0
        ),
    }

    return {
        "stats": stats,
        "orders": [serialize_order(order) for order in orders],
        "active_orders": [
            serialize_order(order)
            for order in orders
            if order.status not in {OrderStatus.DELIVERED, OrderStatus.RETURN_INITIATED}
        ],
        "products": [serialize_product(product) for product in products],
        "critical_products": [serialize_product(product) for product in critical_products],
        "delayed_orders": [serialize_order(order) for order in delayed_orders],
        "pending_messages": [serialize_pending_message(event) for event in pending_message_events],
        "logs": [serialize_log(event) for event in logs],
        "activities": [serialize_activity(event) for event in logs],
    }


def order_ai_context(order: Order) -> dict[str, Any]:
    return {
        "id": order.id,
        "status": order.status.value,
        "customer_name": order.customer_name,
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
    }


def handle_ai_exception(exc: Exception) -> HTTPException:
    if isinstance(exc, AIConfigurationError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, AIServiceError):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unexpected AI failure.")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/dashboard")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        dashboard_payload(db),
    )


@app.get("/tracking", response_class=HTMLResponse)
def tracking(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "tracking.html")


@app.get("/api/dashboard")
def dashboard_api(db: Session = Depends(get_db)) -> dict[str, Any]:
    return dashboard_payload(db)


@app.post("/api/demo/reset")
def reset_demo(db: Session = Depends(get_db)) -> dict[str, Any]:
    db.query(EventLog).delete()
    db.query(Order).delete()
    db.query(Product).delete()
    seed_demo_data(db)
    db.commit()
    return dashboard_payload(db)


@app.post("/api/orders", status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    product = db.query(Product).filter(Product.id == payload.product_id).first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ürün bulunamadı.")
    if product.stock_quantity <= 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ürün stokta yok.")

    product.stock_quantity -= 1
    order = Order(
        customer_name=payload.customer_name,
        customer_phone=payload.customer_phone,
        product_id=product.id,
        origin_city=payload.origin_city,
        destination_city=payload.destination_city,
        status=OrderStatus.PENDING,
    )
    db.add(order)
    db.flush()
    order.public_order_code = make_public_order_code(order.id, payload.customer_name)
    log_event(
        db,
        order.id,
        "Sipariş oluşturuldu ve stoktan bir ürün rezerve edildi.",
        {"stock_quantity_after_reservation": product.stock_quantity},
    )
    db.commit()
    db.refresh(order)
    return {"order": serialize_order(get_order_or_404(db, order.id))}


@app.post("/api/quality-check/{order_id}")
def quality_check(order_id: int, payload: QualityCheckRequest, db: Session = Depends(get_db)) -> JSONResponse:
    order = get_order_or_404(db, order_id)
    if order.status not in {OrderStatus.PENDING, OrderStatus.QUALITY_CHECK}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Kalite kontrol yalnızca PENDING veya QUALITY_CHECK durumundaki siparişler için çalışır.",
        )

    try:
        decision = agent.analyze_quality(
            product=serialize_product(order.product),
            order=order_ai_context(order),
            worker_note=payload.worker_note,
            response_language=payload.language,
        )
    except Exception as exc:
        raise handle_ai_exception(exc) from exc

    decision_log = decision.model_dump()

    if decision.approved:
        plaintext_token, fingerprint = issue_delivery_token(db)
        order.crypto_token = plaintext_token
        enforce_transition(order, OrderStatus.APPROVED)
        log_event(
            db,
            order.id,
            "Gemini kalite kontrolü siparişi onayladı ve güvenli teslimat tokeni üretti.",
            {**decision_log, "token_fingerprint": fingerprint[:12]},
        )
        db.commit()
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "order": serialize_order(get_order_or_404(db, order.id)),
                "ai_decision": decision_log,
                "delivery_token": plaintext_token,
                "token_notice": "Bu tokeni müşteri portalında kullanabilirsiniz.",
            },
        )

    enforce_transition(order, OrderStatus.QUALITY_CHECK)
    log_event(
        db,
        order.id,
        "Gemini kalite kontrolü siparişi reddetti ve gönderimi durdurdu.",
        decision_log,
    )
    db.commit()
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "order": serialize_order(get_order_or_404(db, order.id)),
            "ai_decision": decision_log,
        },
    )


@app.post("/api/orders/{order_id}/ship")
def mark_shipped(order_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    order = get_order_or_404(db, order_id)
    if not order.crypto_token:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Güvenli teslimat tokeni üretilmeden sipariş kargoya verilemez.",
        )

    enforce_transition(order, OrderStatus.SHIPPED)
    log_event(
        db,
        order.id,
        "Sipariş kalite onayından sonra KARGODA durumuna alındı.",
        {"previous_state": "APPROVED", "next_state": "SHIPPED"},
    )
    db.commit()
    return {"order": serialize_order(get_order_or_404(db, order.id))}


@app.post("/api/cargo-webhook/simulate")
def simulate_cargo_delay(payload: CargoDelayRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    order = get_order_or_404(db, payload.order_id)
    if order.status != OrderStatus.SHIPPED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Kargo gecikmesi simülasyonu için sipariş SHIPPED durumunda olmalı.",
        )

    try:
        decision = agent.write_delay_message(
            customer={"name": order.customer_name, "phone": order.customer_phone},
            product=serialize_product(order.product),
            order=order_ai_context(order),
            delay_reason=payload.delay_reason,
            response_language=payload.language,
        )
    except Exception as exc:
        raise handle_ai_exception(exc) from exc

    decision_log = decision.model_dump()
    enforce_transition(order, OrderStatus.DELAYED)
    log_event(
        db,
        order.id,
        "Kargo gecikmesi simüle edildi; Gemini müşteriye özel bilgilendirme mesajı üretti.",
        {
            **decision_log,
            "delay_reason": payload.delay_reason,
            "severity": "high",
            "customer_message": f"{decision.customer_message} Operasyon ekibi gecikmeyi düzeltmek için aksiyon aldı.",
        },
    )
    log_event(
        db,
        order.id,
        "Destek yanıtı onaylandı ve müşteriye gönderildi.",
        {
            "role": "agent",
            "reply": f"{decision.customer_message} Operasyon ekibi gecikmeyi düzeltmek için aksiyon aldı.",
            "intent": "cargo_delay_auto_notice",
        },
    )
    db.commit()
    return {
        "order": serialize_order(get_order_or_404(db, order.id)),
        "ai_decision": decision_log,
        "customer_message": decision.customer_message,
    }


@app.post("/api/tracking/lookup")
def tracking_lookup(payload: TrackingLookupRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    order = get_order_or_404(db, payload.order_id)
    if not verify_delivery_token(order, payload.crypto_token):
        log_event(
            db,
            order.id,
            "Geçersiz teslimat tokeni ile takip sorgusu engellendi.",
            {"token_fingerprint": token_digest(payload.crypto_token)[:12]},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Geçersiz teslimat tokeni.")

    return {
        "order": serialize_order(order, include_phone=False),
        "messages": serialize_customer_messages(order.id, db),
    }


@app.post("/api/delivery/confirm")
def confirm_delivery(payload: DeliveryConfirmRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    order = get_order_or_404(db, payload.order_id)
    if not verify_delivery_token(order, payload.crypto_token):
        log_event(
            db,
            order.id,
            "Geçersiz teslimat tokeni ile teslimat onayı engellendi.",
            {"token_fingerprint": token_digest(payload.crypto_token)[:12]},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Geçersiz teslimat tokeni.")

    if order.status not in {OrderStatus.SHIPPED, OrderStatus.DELAYED, OrderStatus.DELIVERED}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Teslimat puanı ve yorumu için sipariş SHIPPED, DELAYED veya DELIVERED durumunda olmalı.",
        )

    try:
        decision = agent.analyze_delivery_feedback(
            customer_feedback=payload.customer_feedback,
            cargo_rating=payload.cargo_rating,
            delivery_confirmed=payload.delivery_confirmed,
            product=serialize_product(order.product),
            order=order_ai_context(order),
            response_language=payload.language,
        )
    except Exception as exc:
        raise handle_ai_exception(exc) from exc

    decision_log = decision.model_dump()
    decision_log["cargo_rating"] = payload.cargo_rating
    decision_log["customer_feedback"] = payload.customer_feedback
    if order.status != OrderStatus.DELIVERED:
        enforce_transition(order, OrderStatus.DELIVERED)
    log_event(
        db,
        order.id,
        "Teslimat puanı ve müşteri yorumu kaydedildi.",
        decision_log,
    )
    db.commit()

    return {
        "order": serialize_order(get_order_or_404(db, order.id)),
        "ai_decision": decision_log,
        "customer_message": decision.customer_message,
    }


@app.post("/api/return/request")
def request_return(payload: ReturnRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    order = get_order_or_404(db, payload.order_id)
    if not verify_delivery_token(order, payload.crypto_token):
        log_event(
            db,
            order.id,
            "Geçersiz teslimat tokeni ile iade talebi engellendi.",
            {"token_fingerprint": token_digest(payload.crypto_token)[:12]},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Geçersiz teslimat tokeni.")

    if order.status not in {OrderStatus.SHIPPED, OrderStatus.DELAYED, OrderStatus.DELIVERED}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="İade talebi için sipariş Kargoda, Gecikti veya Teslim Edildi durumunda olmalı.",
        )

    try:
        decision = agent.analyze_return_request(
            return_reason=payload.return_reason,
            product=serialize_product(order.product),
            order=order_ai_context(order),
            response_language=payload.language,
        )
    except Exception as exc:
        raise handle_ai_exception(exc) from exc

    decision_log = decision.model_dump()
    decision_log["return_reason"] = payload.return_reason

    if decision.return_approved:
        stock_reserved_for_replacement = False
        if decision.replacement_required and order.product.stock_quantity > 0:
            order.product.stock_quantity -= 1
            stock_reserved_for_replacement = True
        decision_log["replacement_stock_reserved"] = stock_reserved_for_replacement
        decision_log["stock_quantity_after_replacement_reservation"] = order.product.stock_quantity
        enforce_transition(order, OrderStatus.RETURN_INITIATED)
        description = (
            "İade talebi onaylandı ve değişim stoğu rezerve edildi."
            if stock_reserved_for_replacement
            else "İade talebi onaylandı."
        )
    else:
        description = "İade talebi incelendi fakat otomatik onaylanmadı."

    log_event(db, order.id, description, decision_log)
    db.commit()
    return {
        "order": serialize_order(get_order_or_404(db, order.id)),
        "ai_decision": decision_log,
        "customer_message": decision.customer_message,
    }


@app.post("/api/customer/messages")
def customer_messages(payload: TrackingLookupRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    order = get_order_or_404(db, payload.order_id)
    if not verify_delivery_token(order, payload.crypto_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Geçersiz teslimat tokeni.")
    return {"messages": serialize_customer_messages(order.id, db)}


@app.post("/api/customer/message")
def customer_message(payload: CustomerMessageRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    order = get_order_or_404(db, payload.order_id)
    if not verify_delivery_token(order, payload.crypto_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Geçersiz teslimat tokeni.")

    customer_event = log_event(
        db,
        order.id,
        "Müşteri mesajı alındı.",
        {"role": "customer", "message": payload.message},
    )
    acknowledgement = (
        "Mesajınız alındı. Operasyon ekibi yanıtı inceleyip onayladıktan sonra burada görebileceksiniz."
        if payload.language == "tr"
        else "Your message was received. The operations team will review and approve the reply before it appears here."
    )
    log_event(
        db,
        order.id,
        "Otomatik inceleme mesajı müşteriye gönderildi.",
        {"role": "agent", "reply": acknowledgement, "intent": "message_under_review"},
    )

    try:
        decision = agent.write_support_reply(
            message=payload.message,
            product=serialize_product(order.product),
            order=order_ai_context(order),
            response_language=payload.language,
        )
    except Exception as exc:
        raise handle_ai_exception(exc) from exc

    pending_event = log_event(
        db,
        order.id,
        "Yanıt onay bekliyor.",
        {
            "role": "agent",
            "message_event_id": customer_event.id,
            "message": payload.message,
            "draft_reply": decision.reply,
            "intent": decision.intent,
            "status": "pending_approval",
        },
    )
    db.commit()
    return {
        "draft_reply": decision.reply,
        "pending_approval": True,
        "pending_event_id": pending_event.id,
        "messages": serialize_customer_messages(order.id, db),
    }


@app.post("/api/admin/messages/{event_id}/approve")
def approve_customer_message(
    event_id: int,
    approval: AdminMessageApprovalRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    event = (
        db.query(EventLog)
        .options(joinedload(EventLog.order))
        .filter(EventLog.id == event_id)
        .first()
    )
    if not event or event.event_description != "Yanıt onay bekliyor.":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Onay bekleyen mesaj bulunamadı.")

    try:
        event_payload = json.loads(event.ai_decision_log)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Mesaj kaydı okunamadı.") from exc

    draft_reply = event_payload.get("draft_reply")
    final_reply = (approval.reply_text or "").strip() or draft_reply
    if not final_reply:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Onaylanacak taslak yanıt yok.")

    event_payload["status"] = "approved"
    event_payload["approved_reply"] = final_reply
    event.event_description = "Yanıt yetkili tarafından onaylandı."
    event.ai_decision_log = json.dumps(event_payload, ensure_ascii=False, default=str)
    log_event(
        db,
        event.order_id,
        "Destek yanıtı onaylandı ve müşteriye gönderildi.",
        {"role": "agent", "reply": final_reply, "intent": event_payload.get("intent", "")},
    )
    db.commit()
    return dashboard_payload(db)


@app.post("/api/admin/orders/message")
def admin_direct_message(payload: AdminDirectMessageRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    order = get_order_or_404(db, payload.order_id)
    log_event(
        db,
        order.id,
        "Yetkili müşteriye doğrudan mesaj gönderdi.",
        {"role": "agent", "reply": payload.message, "intent": "admin_direct_message"},
    )
    db.commit()
    return dashboard_payload(db)
