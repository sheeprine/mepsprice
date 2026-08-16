from datetime import datetime, timezone


def _utcnow():
    return datetime.now(timezone.utc)
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
)
from sqlalchemy.orm import DeclarativeBase, relationship, Session

import os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./mepsprice.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    handle = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=False)
    image_url = Column(String)
    product_url = Column(String, nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    last_checked_at = Column(DateTime)

    variants = relationship("Variant", back_populates="product", cascade="all, delete-orphan")


class Variant(Base):
    __tablename__ = "variants"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    external_variant_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    sku = Column(String)
    tracked = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)

    product = relationship("Product", back_populates="variants")
    price_checks = relationship("PriceCheck", back_populates="variant", cascade="all, delete-orphan")


class PriceCheck(Base):
    __tablename__ = "price_checks"

    id = Column(Integer, primary_key=True)
    variant_id = Column(Integer, ForeignKey("variants.id"), nullable=False)
    price = Column(Float, nullable=False)
    compare_at_price = Column(Float)
    checked_at = Column(DateTime, default=_utcnow)

    variant = relationship("Variant", back_populates="price_checks")


def get_db():
    with Session(engine) as session:
        yield session


def init_db():
    Base.metadata.create_all(bind=engine)
