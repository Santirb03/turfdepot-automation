import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from io import BytesIO

import httpx
import pytest
from pydantic import SecretStr, ValidationError
from pypdf import PdfReader
from sqlalchemy import func, select, text

from turfdepot.core.config import Settings
from turfdepot.db.models import Conversation, Quote, WhatsAppJob
from turfdepot.services.catalog import approved_prices
from turfdepot.services.whatsapp_client import MetaError, WhatsAppClient
from turfdepot.whatsapp_worker import run_once, update_job

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def configure(app):
    settings = app.state.settings
    settings.whatsapp_enabled = True
    settings.whatsapp_phone_number_id = "12345"
    settings.whatsapp_api_version = "v24.0"
    settings.whatsapp_access_token = SecretStr("fake-access-token")
    settings.whatsapp_app_secret = SecretStr("fake-app-secret")
    settings.whatsapp_verify_token = SecretStr("fake-verify-token")
    settings.internal_api_key = SecretStr("fake-internal-key")
    settings.garden_prices = approved_prices()
    return settings


def payload(message_id="wamid.1", body="hola", kind="text", phone_id="12345", timestamp=NOW):
    message = {"from": "524421234567", "id": message_id, "timestamp": str(int(timestamp.timestamp())), "type": kind}
    if kind == "text":
        message["text"] = {"body": body}
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
        "metadata": {"phone_number_id": phone_id}, "messages": [message]}}]}]}


def post(client, body):
    content = json.dumps(body, ensure_ascii=False).encode()
    signature = "sha256=" + hmac.new(b"fake-app-secret", content, hashlib.sha256).hexdigest()
    return client.post("/webhooks/whatsapp", content=content,
                       headers={"content-type": "application/json", "x-hub-signature-256": signature})


class FakeMeta:
    def __init__(self):
        self.sent = []
        self.uploaded = []
        self.error = None

    def upload_pdf(self, content, filename):
        self.uploaded.append((content, filename))
        return "media.1"

    def send(self, phone, reply, media_id=None, filename=None):
        if self.error:
            raise self.error
        self.sent.append((phone, reply, media_id, filename))
        return f"outbound.{len(self.sent)}"


def work(app, meta):
    return run_once(app.state.engine, app.state.session_factory, app.state.settings, meta, NOW)


def test_disabled_and_verification(client, app):
    assert client.get("/webhooks/whatsapp").status_code == 503
    assert post(client, payload()).status_code == 503
    configure(app)
    query = {"hub.mode": "subscribe", "hub.verify_token": "fake-verify-token", "hub.challenge": "123"}
    response = client.get("/webhooks/whatsapp", params=query)
    assert response.status_code == 200 and response.text == "123"
    query["hub.verify_token"] = "wrong"
    assert client.get("/webhooks/whatsapp", params=query).status_code == 403


def test_protect_internal_routes(client, app):
    configure(app)
    for path in ("/quotes/1", "/quotes/1/pdf", "/docs", "/openapi.json"):
        assert client.get(path).status_code == 401
    assert client.post("/conversations/messages", json={}).status_code == 401
    assert client.get("/health").status_code == 200
    assert client.get("/quotes/1", headers={"authorization": "Bearer fake-internal-key"}).status_code == 404


def test_signature_and_json_validation(client, app):
    configure(app)
    assert client.post("/webhooks/whatsapp", json=payload()).status_code == 403
    assert post(client, []).status_code == 400
    assert post(client, {"object": "whatsapp_business_account", "entry": [None]}).status_code == 400
    invalid = payload()
    invalid["entry"][0]["changes"][0]["value"]["messages"][0]["from"] = "abc"
    assert post(client, invalid).status_code == 400
    assert client.post("/webhooks/whatsapp", content=b"a" * (1024 * 1024 + 1)).status_code == 413


def test_durable_inbox_duplicate_statuses_and_wrong_number(client, app):
    configure(app)
    assert post(client, payload()).status_code == 200
    assert post(client, payload()).status_code == 200
    assert post(client, payload("wamid.other", phone_id="999")).status_code == 200
    statuses = payload()
    value = statuses["entry"][0]["changes"][0]["value"]
    value.pop("messages")
    value["statuses"] = [{"id": "outbound.1", "status": "delivered"}]
    assert post(client, statuses).status_code == 200
    with app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(WhatsAppJob)) == 1
        assert session.scalar(select(func.count()).select_from(Conversation)) == 0
    # HTTP acknowledgment precedes processing/sending, allowing worker restarts.
    app.state.engine.dispose()
    meta = FakeMeta()
    assert work(app, meta)
    assert "nombre" in meta.sent[0][1]
    assert not work(app, meta)


def test_santiago_receives_document_and_retries_do_not_resend(client, app):
    configure(app)
    meta = FakeMeta()
    for index, body in enumerate(("hola", "Santiago Rodriguez", "30 x 22", "sí", "Corregidora")):
        assert post(client, payload(f"wamid.{index}", body)).status_code == 200
        assert work(app, meta)
    assert len(meta.sent) == 5 and len(meta.uploaded) == 1
    phone, reply, media_id, filename = meta.sent[-1]
    assert phone == "524421234567" and media_id == "media.1"
    assert reply.startswith("¡Listo, Santiago! 🌱👷‍♂️")
    assert "Corregidora" not in reply and "Rodriguez" not in reply
    assert filename == "Cotizacion-11001.pdf"
    pdf = PdfReader(BytesIO(meta.uploaded[0][0]))
    contents = "\n".join(page.extract_text() for page in pdf.pages)
    assert "Santiago Rodriguez" in contents and "Queretaro" in contents
    assert "Corregidora" not in contents
    assert "229.680,00" in contents and "99.000,00" in contents
    assert post(client, payload("wamid.4", "Corregidora")).status_code == 200
    assert not work(app, meta)
    assert len(meta.sent) == 5
    with app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Quote)) == 1
        assert all(job.status == "done" for job in session.scalars(select(WhatsAppJob)))


def test_unsupported_and_expired_messages_do_not_advance(client, app):
    configure(app)
    meta = FakeMeta()
    post(client, payload(kind="audio"))
    assert work(app, meta)
    assert "texto" in meta.sent[-1][1]
    post(client, payload("wamid.old", "hola", timestamp=NOW - timedelta(days=2)))
    assert work(app, meta)
    with app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Conversation)) == 0
        assert session.scalar(select(WhatsAppJob).where(WhatsAppJob.message_id == "wamid.old")).status == "expired"


def test_failed_send_retry_keeps_response_and_conversation(client, app):
    configure(app)
    meta = FakeMeta()
    meta.error = MetaError("meta_http_429")
    post(client, payload())
    assert work(app, meta)
    post(client, payload("wamid.2", "Ana"))
    assert not work(app, meta)  # Later messages for the contact wait.
    with app.state.session_factory() as session:
        job = session.scalar(select(WhatsAppJob).where(WhatsAppJob.message_id == "wamid.1"))
        assert job.status == "failed" and job.response["state"] == "name"
        job_id = job.id
    update_job(app.state.session_factory, job_id, status="pending")
    meta.error = None
    assert work(app, meta)
    assert "nombre" in meta.sent[-1][1]
    assert work(app, meta)
    with app.state.session_factory() as session:
        assert session.get(Conversation, "524421234567").customer_name == "Ana"


def test_ambiguous_send_is_not_retried(client, app):
    configure(app)
    meta = FakeMeta()
    meta.error = MetaError("meta_transport_error", uncertain=True)
    post(client, payload())
    assert work(app, meta)
    assert not work(app, meta)
    with app.state.session_factory() as session:
        assert session.scalar(select(WhatsAppJob)).status == "uncertain"


def test_interrupted_send_and_single_worker_lock(client, app):
    configure(app)
    post(client, payload())
    with app.state.engine.connect() as lock:
        lock.execute(text("SELECT pg_advisory_lock(hashtext(current_schema() || '_whatsapp_worker'))"))
        lock.commit()
        try:
            assert not work(app, FakeMeta())
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(hashtext(current_schema() || '_whatsapp_worker'))"))
            lock.commit()
    with app.state.session_factory.begin() as session:
        session.scalar(select(WhatsAppJob)).status = "sending"
    assert not work(app, FakeMeta())
    with app.state.session_factory() as session:
        assert session.scalar(select(WhatsAppJob)).status == "uncertain"


def test_meta_client_contract_and_no_sensitive_errors(app):
    settings = configure(app)
    calls = []
    def handler(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer fake-access-token"
        if request.url.path.endswith("/media"):
            assert b'application/pdf' in request.content and b'file' in request.content
            return httpx.Response(200, json={"id": "media.id"})
        return httpx.Response(200, json={"messages": [{"id": "outbound.id"}]})
    meta = WhatsAppClient(settings, transport=httpx.MockTransport(handler))
    try:
        assert meta.upload_pdf(b"fake-pdf", "quote.pdf") == "media.id"
        assert meta.send("524421234567", "hola") == "outbound.id"
        assert meta.send("524421234567", "listo", "media.id", "quote.pdf") == "outbound.id"
        sent = json.loads(calls[-1].content)
        assert sent["type"] == "document" and sent["document"]["id"] == "media.id"
        assert all(call.url.host == "graph.facebook.com" for call in calls)
    finally:
        meta.close()


@pytest.mark.parametrize("status,uncertain", [(401, False), (429, False), (500, True)])
def test_meta_errors_are_sanitized(app, status, uncertain):
    meta = WhatsAppClient(configure(app), transport=httpx.MockTransport(
        lambda _: httpx.Response(status, json={"error": "fake-access-token customer details"})))
    try:
        with pytest.raises(MetaError) as error:
            meta.send("524421234567", "hola")
        assert str(error.value) == f"meta_http_{status}" and error.value.uncertain == uncertain
    finally:
        meta.close()


def test_network_timeout_is_ambiguous(app):
    def timeout(request):
        raise httpx.ReadTimeout("private details", request=request)
    meta = WhatsAppClient(configure(app), transport=httpx.MockTransport(timeout))
    try:
        with pytest.raises(MetaError) as error:
            meta.send("524421234567", "hola")
        assert error.value.uncertain and str(error.value) == "meta_transport_error"
    finally:
        meta.close()


def test_meta_numeric_error_code_without_customer_details(app):
    meta = WhatsAppClient(configure(app), transport=httpx.MockTransport(lambda _: httpx.Response(
        400, json={"error": {"code": 131030, "error_subcode": 7,
                            "message": "fake-access-token private customer details"}})))
    try:
        with pytest.raises(MetaError) as error:
            meta.send("524421234567", "hola")
        assert str(error.value) == "meta_http_400_code_131030_error_subcode_7"
        assert not error.value.uncertain
    finally:
        meta.close()


def test_mexican_test_recipient_fallback_only_after_explicit_rejection(app):
    recipients = []
    def handler(request):
        body = json.loads(request.content)
        recipients.append(body["to"])
        if body["to"] == "5214421234567":
            return httpx.Response(400, json={"error": {"code": 131030}})
        return httpx.Response(200, json={"messages": [{"id": "accepted"}]})
    meta = WhatsAppClient(configure(app), transport=httpx.MockTransport(handler))
    try:
        assert meta.send("5214421234567", "hola") == "accepted"
        assert recipients == ["5214421234567", "524421234567"]
    finally:
        meta.close()


@pytest.mark.parametrize("status,code", [(500, 131030), (400, 131047), (401, 190)])
def test_no_format_retry_for_other_rejections(app, status, code):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={"error": {"code": code}})
    meta = WhatsAppClient(configure(app), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(MetaError):
            meta.send("5214421234567", "hola")
        assert len(requests) == 1
    finally:
        meta.close()


def test_enabled_requires_credentials_and_hides_secrets():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, whatsapp_enabled=True)
    settings = Settings(_env_file=None, whatsapp_enabled=True,
        whatsapp_phone_number_id="12345", whatsapp_api_version="v24.0",
        whatsapp_access_token="secret-test", whatsapp_app_secret="app-secret",
        whatsapp_verify_token="verify-token", internal_api_key="internal-key")
    assert "secret-test" not in repr(settings)
