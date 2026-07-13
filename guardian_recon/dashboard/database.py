"""
GuardianRecon — Database Layer
===================================
طبقة تخزين دائمة بـ SQLAlchemy. تبدأ بـ SQLite (بدون إعداد سيرفر)
وقابلة للترقية لـ PostgreSQL بمجرد تغيير DATABASE_URL — الكود
نفسه ما يتغير لأنه معتمد على SQLAlchemy ORM بالكامل.

مرحلة 1.1 من خارطة الطريق — لا يوجد فقدان بيانات بعد إعادة تشغيل السيرفر.
"""

from __future__ import annotations
from datetime import datetime, date
import os

from sqlalchemy import (
    create_engine, Column, String, Float, Integer, Boolean, DateTime, Date, Text
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from guardian_recon.config import get_database_url

DATABASE_URL = get_database_url()

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


# ============================================================
# الجداول
# ============================================================
class ReconciliationRunORM(Base):
    __tablename__ = "reconciliation_runs"

    id = Column(String, primary_key=True)
    as_of = Column(Date, nullable=False)
    bank_balance = Column(Float, default=0.0)
    gl_balance = Column(Float, default=0.0)
    raw_difference = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    source = Column(String, default="demo")  # demo / odoo_live


class ReconciliationItemORM(Base):
    __tablename__ = "reconciliation_items"

    id = Column(String, primary_key=True)
    run_id = Column(String, nullable=False)
    category = Column(String, nullable=False)
    txn_date = Column(Date)
    description = Column(Text)
    party_type = Column(String, nullable=True)
    amount = Column(Float, default=0.0)
    difference = Column(Float, default=0.0)
    status = Column(String, default="Current")
    age_days = Column(Integer, default=0)
    match_confidence = Column(Float, default=0.0)
    note = Column(Text)

    # الموافقة
    approval_status = Column(String, default="pending")  # pending/approved/rejected/auto_cleared
    decided_by = Column(String, nullable=True)
    decided_at = Column(DateTime, nullable=True)
    comment = Column(Text, default="")
    posted_to_odoo = Column(Boolean, default=False)


class ActivityLogORM(Base):
    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    actor = Column(String)
    action = Column(String)
    detail = Column(Text)


def init_db():
    """ينشئ كل الجداول إذا ما كانت موجودة — آمن يتنادى أكثر من مرة."""
    Base.metadata.create_all(bind=engine)


def get_session() -> Session:
    return SessionLocal()
