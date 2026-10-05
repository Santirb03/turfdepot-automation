"""Small Cloud API client. Never include tokens or raw responses in errors."""
import httpx

from turfdepot.core.config import Settings


class MetaError(ValueError):
    def __init__(self, code: str, uncertain: bool = False):
        super().__init__(code)
        self.uncertain = uncertain


class WhatsAppClient:
    def __init__(self, settings: Settings, transport=None):
        self.http = httpx.Client(
            base_url=f"https://graph.facebook.com/{settings.whatsapp_api_version}/{settings.whatsapp_phone_number_id}/",
            headers={"Authorization": "Bearer " + settings.whatsapp_access_token.get_secret_value()},
            timeout=15, transport=transport, follow_redirects=False,
        )

    def close(self):
        self.http.close()

    def _post(self, endpoint: str, *, sending=False, **kwargs) -> dict:
        try:
            result = self.http.post(endpoint, **kwargs)
        except httpx.HTTPError as exc:
            raise MetaError("meta_transport_error", uncertain=sending) from exc
        if not result.is_success:
            # A server failure may happen after accepting an outbound message.
            code = f"meta_http_{result.status_code}"
            try:
                error = result.json().get("error", {})
                if isinstance(error, dict):
                    for field in ("code", "error_subcode"):
                        if type(error.get(field)) is int:
                            code += f"_{field}_{error[field]}"
            except (ValueError, AttributeError):
                pass
            raise MetaError(code, uncertain=sending and result.status_code >= 500)
        try:
            payload = result.json()
            if not isinstance(payload, dict):
                raise ValueError()
            return payload
        except ValueError as exc:
            raise MetaError("meta_invalid_response", uncertain=sending) from exc

    def upload_pdf(self, content: bytes, filename: str) -> str:
        payload = self._post("media", data={"messaging_product": "whatsapp", "type": "application/pdf"},
                             files={"file": (filename, content, "application/pdf")})
        media_id = payload.get("id")
        if not isinstance(media_id, str) or not media_id or len(media_id) > 200:
            raise MetaError("meta_missing_media_id")
        return media_id

    def send(self, phone: str, reply: str, media_id=None, filename=None) -> str:
        body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": phone}
        if media_id:
            body.update(type="document", document={"id": media_id, "filename": filename, "caption": reply})
        else:
            body.update(type="text", text={"body": reply, "preview_url": False})
        try:
            payload = self._post("messages", sending=True, json=body)
        except MetaError as exc:
            # Test allow-lists can store +52 while webhooks use legacy +521.
            # Retry only an explicit recipient rejection, never an uncertain send.
            if (str(exc).startswith("meta_http_400_code_131030") and not exc.uncertain
                    and phone.startswith("521") and len(phone) == 13 and phone.isdigit()):
                body["to"] = "52" + phone[3:]
                payload = self._post("messages", sending=True, json=body)
            else:
                raise
        try:
            message_id = payload["messages"][0]["id"]
            if not isinstance(message_id, str) or not message_id or len(message_id) > 200:
                raise ValueError()
            return message_id
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise MetaError("meta_missing_message_id", uncertain=True) from exc
