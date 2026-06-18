from sqlalchemy import Column, BigInteger, String, Date, DateTime, Integer, Text, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase
from pgvector.sqlalchemy import Vector


class Base(DeclarativeBase):
    pass


class FinancialData(Base):
    __tablename__ = "financial_data"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_code = Column(String(10), nullable=False, index=True)
    report_date = Column(Date, nullable=False)
    metric_name = Column(String(64), nullable=False)
    metric_value = Column(Numeric(20, 4))
    source = Column(String(32), default="akshare")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Document(Base):
    __tablename__ = "documents"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_code = Column(String(10), nullable=False, index=True)
    doc_type = Column(String(32), nullable=False)
    doc_title = Column(String(256))
    chunk_index = Column(Integer, default=0)
    content = Column(Text, nullable=False)
    content_zh = Column(Text)
    embedding = Column(Vector(1024))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True)
    company_code = Column(String(10), nullable=False)
    company_name = Column(String(64))
    report_date = Column(Date)
    status = Column(String(16), default="pending")
    progress = Column(Integer, default=0)
    result = Column(JSONB)
    error_log = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
