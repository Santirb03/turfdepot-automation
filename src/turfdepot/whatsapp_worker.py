"""Durable small-volume worker. No external broker or scheduler required."""
import argparse
import logging
import signal
from datetime import datetime, timedelta, timezone
from threading import Event

from sqlalchemy import create_engine, exists, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import aliased, sessionmaker

from turfdepot.core.config import Settings
from turfdepot.db.models import Quote, WhatsAppJob
from turfdepot.db.schema import initialize_schema
from turfdepot.schemas.conversation import MessageCreate
from turfdepot.services.conversation_service import process_message
from turfdepot.services.pdf_service import quote_pdf
from turfdepot.services.whatsapp_client import MetaError, WhatsAppClient

LOG = logging.getLogger(__name__)


def update_job(factory, job_id, **values):
    with factory.begin() as session:
        job = session.get(WhatsAppJob, job_id)
        for name, value in values.items():
            setattr(job, name, value)


def run_once(engine, factory, settings, client, now=None) -> bool:
    now = now or datetime.now(timezone.utc)
    # A session-level lock keeps one worker active, even across its commits.
    with engine.connect() as lock:
        key = text("SELECT pg_try_advisory_lock(hashtext(current_schema() || '_whatsapp_worker'))")
        acquired = lock.scalar(key)
        lock.commit()
        if not acquired:
            return False
        try:
            return process_next(factory, settings, client, now)
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(hashtext(current_schema() || '_whatsapp_worker'))"))
            lock.commit()


def process_next(factory, settings, client, now):
    with factory.begin() as session:
        # A crash while sending cannot establish whether Meta accepted the send.
        for interrupted in session.scalars(select(WhatsAppJob).where(WhatsAppJob.status == "sending")):
            interrupted.status = "uncertain"
            interrupted.last_error = "interrupted_send"
        older = aliased(WhatsAppJob)
        blocked = exists(select(older.id).where(
            older.phone == WhatsAppJob.phone, older.id < WhatsAppJob.id,
            older.status.in_(["pending", "sending", "uncertain", "failed"])))
        job = session.scalar(select(WhatsAppJob).where(
            WhatsAppJob.status == "pending", ~blocked).order_by(WhatsAppJob.id).limit(1))
    if job is None:
        return False
    try:
        if now - job.inbound_at >= timedelta(hours=23, minutes=50):
            update_job(factory, job.id, status="expired", last_error="reply_window_expired")
            return True
        if job.inbound_at > now + timedelta(minutes=5):
            raise ValueError("Future timestamp")
        response = job.response
        if response is None:
            if job.message_text is None:
                response = {"reply": "Por ahora puedo leer mensajes de texto. Escribe tu respuesta para continuar.", "quote_id": None}
            else:
                with factory() as session:
                    response = process_message(session, MessageCreate(
                        contact_phone=job.phone, message_id=job.message_id, text=job.message_text), settings.garden_prices)
            update_job(factory, job.id, response=response)
        filename = None
        media_id = job.media_id
        if response.get("quote_id"):
            with factory() as session:
                quote = session.get(Quote, response["quote_id"])
                filename = f"Cotizacion-{quote.quote_number}.pdf"
                if not media_id:
                    content = quote_pdf(quote)
            if not media_id:
                media_id = client.upload_pdf(content, filename)
                update_job(factory, job.id, media_id=media_id)
        # Commit BEFORE the external send. Never automatically repeat an ambiguous send.
        update_job(factory, job.id, status="sending")
        outbound_id = client.send(job.phone, response["reply"], media_id, filename)
        update_job(factory, job.id, status="done", outbound_id=outbound_id, last_error=None)
        LOG.info("WhatsApp job %s accepted by Meta", job.id)
    except MetaError as exc:
        update_job(factory, job.id, status="uncertain" if exc.uncertain else "failed", last_error=str(exc))
        LOG.warning("WhatsApp job %s: %s", job.id, str(exc))
    except ValueError:
        update_job(factory, job.id, status="failed", last_error="processing_error")
        LOG.warning("WhatsApp job %s requires review", job.id)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--list", action="store_true", help="List recent job IDs and safe statuses")
    parser.add_argument("--retry", type=int, help="Retry a failed job after fixing its cause")
    parser.add_argument("--resolve", type=int, help="Mark an uncertain job resolved after checking delivery manually")
    args = parser.parse_args()
    settings = Settings()
    if not settings.whatsapp_enabled:
        parser.error("Configure y habilite WhatsApp primero.")
    logging.basicConfig(level=logging.INFO)
    engine = create_engine(settings.connection_url(), pool_pre_ping=True)
    factory = sessionmaker(engine, expire_on_commit=False)
    initialize_schema(engine)
    client = WhatsAppClient(settings)
    stop = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    try:
        if args.list:
            with factory() as session:
                for job in session.scalars(select(WhatsAppJob).order_by(WhatsAppJob.id.desc()).limit(20)):
                    print(job.id, job.status, job.last_error or "-")
            return
        if args.retry is not None or args.resolve is not None:
            with factory.begin() as session:
                job = session.get(WhatsAppJob, args.retry if args.retry is not None else args.resolve)
                required = "failed" if args.retry is not None else "uncertain"
                if job is None or job.status != required:
                    parser.error(f"El trabajo debe existir y estar en estado {required}.")
                job.status = "pending" if args.retry is not None else "done"
                job.last_error = None
            return
        while not stop.is_set():
            try:
                worked = run_once(engine, factory, settings, client)
            except SQLAlchemyError:
                LOG.error("WhatsApp database unavailable; will retry without exposing details")
                worked = False
            if args.once:
                break
            if not worked:
                stop.wait(2)
    finally:
        client.close()
        engine.dispose()


if __name__ == "__main__":
    main()
