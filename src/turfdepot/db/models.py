from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, func, Sequence, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


quote_number_sequence = Sequence("quote_number_seq", start=11001, metadata=Base.metadata)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    phone: Mapped[str] = mapped_column(String(30))
    location: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    quotes: Mapped[list["Quote"]] = relationship(back_populates="customer")


class Quote(Base):
    __tablename__ = "quotes"
    __table_args__ = (
        CheckConstraint("square_meters > 0"),
        CheckConstraint("subtotal >= 0 AND extras_total >= 0"),
        CheckConstraint("total = subtotal + extras_total"),
        CheckConstraint("status = 'pending'"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    quote_number: Mapped[int] = mapped_column(
        quote_number_sequence, server_default=quote_number_sequence.next_value(), unique=True
    )
    pdf_prices: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    base_price_per_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    square_meters: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    garden_type: Mapped[str] = mapped_column(String(80))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    extras_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    customer: Mapped[Customer] = relationship(back_populates="quotes")
    extras: Mapped[list["QuoteExtra"]] = relationship(back_populates="quote", cascade="all, delete-orphan")


class QuoteExtra(Base):
    __tablename__ = "quote_extras"
    __table_args__ = (CheckConstraint("price >= 0"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("quotes.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    quote: Mapped[Quote] = relationship(back_populates="extras")


class Conversation(Base):
    __tablename__ = "conversations"

    phone: Mapped[str] = mapped_column(String(16), primary_key=True)
    state: Mapped[str] = mapped_column(String(30), default="name")
    customer_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    square_meters: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    quote_id: Mapped[int | None] = mapped_column(ForeignKey("quotes.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    phone: Mapped[str] = mapped_column(ForeignKey("conversations.phone"), primary_key=True)
    message_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    request_text: Mapped[str] = mapped_column(String(1000))
    response: Mapped[dict] = mapped_column(JSON)
