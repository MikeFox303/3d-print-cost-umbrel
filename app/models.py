from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Filament(Base):
    __tablename__ = "filaments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    brand: Mapped[str] = mapped_column(String(100), default="")
    material: Mapped[str] = mapped_column(String(60), default="PETG")
    color: Mapped[str] = mapped_column(String(80), default="")
    weight_g: Mapped[float] = mapped_column(Float, default=1000)
    purchase_price: Mapped[float] = mapped_column(Float, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    @property
    def price_per_g(self) -> float:
        return self.purchase_price / self.weight_g if self.weight_g else 0.0

class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    client: Mapped[str] = mapped_column(String(180), default="")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    print_minutes: Mapped[int] = mapped_column(Integer, default=0)
    manual_minutes: Mapped[int] = mapped_column(Integer, default=0)
    packaging_cost: Mapped[float] = mapped_column(Float, default=0)
    complexity: Mapped[str] = mapped_column(String(32), default="normal")
    platform: Mapped[str] = mapped_column(String(32), default="direct")
    electricity_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_margin: Mapped[float] = mapped_column(Float, default=0.35)
    final_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    production_cost: Mapped[float] = mapped_column(Float, default=0)
    minimum_price: Mapped[float] = mapped_column(Float, default=0)
    recommended_price: Mapped[float] = mapped_column(Float, default=0)
    planned_payback: Mapped[float] = mapped_column(Float, default=0)
    realized_payback: Mapped[float] = mapped_column(Float, default=0)
    expected_profit: Mapped[float] = mapped_column(Float, default=0)
    payback_rate_snapshot: Mapped[float] = mapped_column(Float, default=0)
    calc_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")

    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    materials: Mapped[list["OrderMaterial"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )

class OrderMaterial(Base):
    __tablename__ = "order_materials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    filament_id: Mapped[int | None] = mapped_column(ForeignKey("filaments.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="local")
    source_ref: Mapped[str] = mapped_column(String(120), default="")
    name_snapshot: Mapped[str] = mapped_column(String(180), nullable=False)
    material_snapshot: Mapped[str] = mapped_column(String(60), default="")
    grams: Mapped[float] = mapped_column(Float, default=0)
    price_per_g_snapshot: Mapped[float] = mapped_column(Float, default=0)
    remaining_g_snapshot: Mapped[float | None] = mapped_column(Float, nullable=True)

    order: Mapped[Order] = relationship(back_populates="materials")

class MonthlyPaybackRate(Base):
    __tablename__ = "monthly_payback_rates"
    __table_args__ = (UniqueConstraint("month", name="uq_payback_month"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    month: Mapped[str] = mapped_column(String(7), nullable=False)
    rate: Mapped[float] = mapped_column(Float, default=0)
    reference_hours: Mapped[float] = mapped_column(Float, default=0)
    remaining_equipment: Mapped[float] = mapped_column(Float, default=0)
    recovered_before: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
