from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def utc_now() -> datetime:
    """Use UTC timestamps for deterministic audit trails."""
    return datetime.now(timezone.utc)


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    QUALITY_CHECK = "QUALITY_CHECK"
    APPROVED = "APPROVED"
    SHIPPED = "SHIPPED"
    DELAYED = "DELAYED"
    DELIVERED = "DELIVERED"
    RETURN_INITIATED = "RETURN_INITIATED"


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    stock_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    critical_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    orders: Mapped[list["Order"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(160), nullable=False)
    customer_phone: Mapped[str] = mapped_column(String(40), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus, name="order_status", native_enum=False, validate_strings=True),
        nullable=False,
        default=OrderStatus.PENDING,
        index=True,
    )
    # Stores a SHA-256 digest of the delivery token, never the plaintext token.
    crypto_token: Mapped[str | None] = mapped_column(
        String(128),
        unique=True,
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    product: Mapped[Product] = relationship(back_populates="orders")
    event_logs: Mapped[list["EventLog"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
    )


class EventLog(Base):
    __tablename__ = "event_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    event_description: Mapped[str] = mapped_column(Text, nullable=False)
    ai_decision_log: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        index=True,
    )

    order: Mapped[Order] = relationship(back_populates="event_logs")


class ProductCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=160)
    stock_quantity: int = Field(..., ge=0)
    critical_threshold: int = Field(..., ge=0)
    price: Decimal = Field(..., gt=0)


class ProductRead(ProductCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)


class OrderCreate(BaseModel):
    customer_name: str = Field(..., min_length=2, max_length=160)
    customer_phone: str = Field(..., min_length=6, max_length=40)
    product_id: int = Field(..., gt=0)


class QualityCheckRequest(BaseModel):
    worker_note: str = Field(..., min_length=5, max_length=2000)
    language: str = Field(default="en", pattern="^(en|tr)$")


class CargoDelayRequest(BaseModel):
    order_id: int = Field(..., gt=0)
    delay_reason: str = Field(
        default="Bölgesel kargo merkezinde beklenmeyen rota gecikmesi oluştu.",
        min_length=5,
        max_length=500,
    )
    language: str = Field(default="en", pattern="^(en|tr)$")


class DeliveryConfirmRequest(BaseModel):
    order_id: int = Field(..., gt=0)
    crypto_token: str = Field(..., min_length=16, max_length=256)
    customer_feedback: str = Field(..., min_length=3, max_length=2000)
    cargo_rating: int = Field(..., ge=1, le=5)
    delivery_confirmed: bool = True
    language: str = Field(default="en", pattern="^(en|tr)$")


class ReturnRequest(BaseModel):
    order_id: int = Field(..., gt=0)
    crypto_token: str = Field(..., min_length=16, max_length=256)
    return_reason: str = Field(..., min_length=5, max_length=2000)
    language: str = Field(default="en", pattern="^(en|tr)$")


class TrackingLookupRequest(BaseModel):
    order_id: int = Field(..., gt=0)
    crypto_token: str = Field(..., min_length=16, max_length=256)


class CustomerMessageRequest(BaseModel):
    order_id: int = Field(..., gt=0)
    crypto_token: str = Field(..., min_length=16, max_length=256)
    message: str = Field(..., min_length=2, max_length=2000)
    language: str = Field(default="en", pattern="^(en|tr)$")
