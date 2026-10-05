import pytest
from sqlalchemy import func, select

from turfdepot.db.models import Conversation, Quote, WhatsAppJob
from test_whatsapp import FakeMeta, configure, payload, post, work


@pytest.mark.parametrize("kind,body", [("text", "gracias"), ("text", "quiero contratar"),
                                      ("text", "hola"), ("audio", None), ("image", None)])
def test_silence_after_pdf_survives_restart(client, app, kind, body):
    configure(app)
    meta = FakeMeta()
    for index, message in enumerate(("hola", "Ana", "40 metros cuadrados", "Corregidora")):
        post(client, payload(f"handoff.{index}", message))
        assert work(app, meta)
    assert len(meta.sent) == 4 and len(meta.uploaded) == 1
    assert meta.sent[-1][2] == "media.1"  # Last automated message is the PDF.
    app.state.engine.dispose()
    post(client, payload("after.pdf", body, kind=kind))
    assert work(app, meta)
    assert len(meta.sent) == 4 and len(meta.uploaded) == 1
    post(client, payload("after.pdf", body, kind=kind))
    assert not work(app, meta)
    with app.state.session_factory() as session:
        job = session.scalar(select(WhatsAppJob).where(WhatsAppJob.message_id == "after.pdf"))
        assert job.status == "handed_off" and job.response["reply"] == ""
        assert session.scalar(select(func.count()).select_from(Quote)) == 1
        assert session.get(Conversation, "524421234567").state == "completed"


def test_handoff_does_not_silence_new_contacts(client, app):
    configure(app)
    meta = FakeMeta()
    for index, message in enumerate(("hola", "Ana", "40", "Corregidora")):
        post(client, payload(f"first.{index}", message))
        work(app, meta)
    incoming = payload("new.contact")
    incoming["entry"][0]["changes"][0]["value"]["messages"][0]["from"] = "524421234568"
    assert post(client, incoming).status_code == 200
    assert work(app, meta)
    assert len(meta.sent) == 5 and "nombre" in meta.sent[-1][1]
