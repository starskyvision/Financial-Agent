from sqlalchemy import Column, BigInteger, String, Date, DateTime, Integer, Text, JSON, func
from sqlalchemy.orm import DeclarativeBase
import enum


class Base(DeclarativeBase):
    pass


class TaskStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class FinancialData(Base):
    __tablename__ = "financial_data"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_code = Column(String(10), nullable=False, index=True)
    report_date = Column(Date, nullable=False)
    metric_name = Column(String(64), nullable=False)
    metric_value = Column(String(64), nullable=False)
    source = Column(String(32), default="akshare")
    created_at = Column(DateTime, server_default=func.now())


class Document(Base):
    __tablename__ = "documents"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_code = Column(String(10), nullable=False, index=True)
    doc_type = Column(String(32), nullable=False)
    chunk_index = Column(Integer, default=0)
    content = Column(Text)
    vector_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True)
    company_code = Column(String(10), nullable=False)
    status = Column(String(16), default="pending")
    result = Column(JSON, nullable=True)
    error_log = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
