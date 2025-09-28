from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
import imaplib, os

class Command(BaseCommand):
    help = "SMTP+IMAP diagnostics"

    def handle(self, *args, **opts):
        # SMTP
        self.stdout.write("== SMTP test ==")
        try:
            n = send_mail(
                subject="SalesPortal • SMTP DIAG",
                message="Диагностика SMTP прошла успешно.",
                from_email=None,
                recipient_list=[os.environ.get("EMAIL_HOST_USER")],
            )
            self.stdout.write(self.style.SUCCESS(f"SMTP OK, sent={n}, from={settings.DEFAULT_FROM_EMAIL}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"SMTP FAIL: {e}"))

        # IMAP
        self.stdout.write("\n== IMAP test ==")
        host = os.environ.get("IMAP_HOST","imap.gmail.com")
        port = int(os.environ.get("IMAP_PORT","993"))
        user = os.environ.get("IMAP_USERNAME")
        pwd  = os.environ.get("IMAP_PASSWORD")
        try:
            M = imaplib.IMAP4_SSL(host, port)
            M.login(user, pwd)
            M.select("INBOX")
            typ, data = M.search(None, "ALL")
            count = len((data[0] or b"").split())
            self.stdout.write(self.style.SUCCESS(f"IMAP OK, inbox messages: {count}"))
            M.close(); M.logout()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"IMAP FAIL: {e}"))
