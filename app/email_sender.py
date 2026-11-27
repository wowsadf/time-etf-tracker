from __future__ import annotations

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, formataddr, make_msgid

from config import SMTP_PASS, SMTP_USER, TO_EMAIL
from logging_utils import setup_logger

logger = setup_logger()


def send_html_email(subject: str, html_body: str, text_body: str | None = None) -> str:
    if not SMTP_USER:
        raise RuntimeError("SMTP_USER가 설정되지 않았습니다")
    if not SMTP_PASS:
        raise RuntimeError("SMTP_PASS가 설정되지 않았습니다")
    if not TO_EMAIL:
        raise RuntimeError("TO_EMAIL이 설정되지 않았습니다")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr(("TIME ETF", SMTP_USER))
    msg["To"] = TO_EMAIL
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=SMTP_USER.split("@")[-1])

    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))

    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if len(html_body.encode("utf-8")) > 90_000:
        logger.warning("[EMAIL] large HTML: 메일 앱에서 본문이 잘릴 수 있습니다")
    logger.info("[EMAIL] sending report to configured recipient")

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, [TO_EMAIL], msg.as_string())

    logger.info("[EMAIL] SMTP accepted message id=%s", msg["Message-ID"])
    return msg["Message-ID"]
