import os, email, imaplib, quopri, base64, re
from datetime import datetime, timezone
from django.core.management.base import BaseCommand
from django.utils.timezone import make_aware
from sales.models import InboundEmail, BookingSale

m = re.search(r'(BK-\d+)', subj or "")
if m:
    code = m.group(1)
    try:
        b = BookingSale.objects.get(booking_code=code)
        InboundEmail.objects.filter(uid=uid).update(booking=b)
    except BookingSale.DoesNotExist:
        pass

def _decode_header(value):
    from email.header import decode_header
    if not value: return ""
    parts = decode_header(value)
    decoded = ""
    for text, enc in parts:
        if isinstance(text, bytes):
            decoded += text.decode(enc or "utf-8", errors="replace")
        else:
            decoded += text
    return decoded

def _get_body(msg):
    text, html = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if ctype in ("text/plain","text/html") and "attachment" not in disp.lower():
                payload = part.get_payload(decode=True) or b""
                try:
                    decoded = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                except Exception:
                    decoded = payload.decode("utf-8", errors="replace")
                if ctype == "text/plain":
                    text += decoded
                else:
                    html += decoded
    else:
        payload = msg.get_payload(decode=True) or b""
        text = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    return text.strip(), html.strip()

class Command(BaseCommand):
    help = "Fetch unread emails from Gmail via IMAP and store them in DB"

    def handle(self, *args, **opts):
        host = os.environ.get("IMAP_HOST","imap.gmail.com")
        port = int(os.environ.get("IMAP_PORT","993"))
        user = os.environ.get("IMAP_USERNAME")
        pwd  = os.environ.get("IMAP_PASSWORD")
        use_ssl = os.environ.get("IMAP_USE_SSL","true").lower() == "true"

        if use_ssl:
            M = imaplib.IMAP4_SSL(host, port)
        else:
            M = imaplib.IMAP4(host, port)
        M.login(user, pwd)
        M.select("INBOX")

        # UNSEEN — только непрочитанные. Можно заменить на метки, если настроишь фильтры в Gmail.
        typ, data = M.search(None, "UNSEEN")
        if typ != "OK":
            self.stdout.write(self.style.ERROR("IMAP search failed"))
            return

        ids = data[0].split()
        self.stdout.write(f"Found {len(ids)} unseen emails")

        for i in ids:
            typ, msg_data = M.fetch(i, "(RFC822 UID)")
            if typ != "OK": 
                continue

            uid = None
            for resp in msg_data:
                if isinstance(resp, tuple):
                    # вытащим UID
                    m = re.search(rb'UID (\d+)', resp[0] or b"")
                    if m:
                        uid = m.group(1).decode()
                    raw = resp[1]
                    msg = email.message_from_bytes(raw)

                    mid = msg.get("Message-ID")
                    subj = _decode_header(msg.get("Subject"))
                    from_ = _decode_header(msg.get("From"))
                    to_   = _decode_header(msg.get("To"))
                    date_hdr = msg.get("Date")
                    try:
                        dt = email.utils.parsedate_to_datetime(date_hdr)
                        if dt and dt.tzinfo is None:
                            dt = make_aware(dt)
                    except Exception:
                        dt = datetime.now(timezone.utc)

                    text, html = _get_body(msg)
                    snippet = (text or html)
                    snippet = re.sub(r"\s+", " ", snippet).strip()[:400]

                    if uid and not InboundEmail.objects.filter(uid=uid).exists():
                        InboundEmail.objects.create(
                            uid=uid, message_id=mid, subject=subj, from_email=from_,
                            to_email=to_, date=dt, snippet=snippet, body_text=text,
                            body_html=html, raw_headers=str(msg.items()),
                        )

        # пометить прочитанными, чтобы не дублировать (опционально):
        if ids:
            M.store(b",".join(ids), "+FLAGS", "\\Seen")

        M.close()
        M.logout()
