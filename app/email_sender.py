from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import SMTP_PASS, SMTP_USER, TO_EMAIL
from logging_utils import setup_logger

logger = setup_logger()


def send_html_email(subject: str, html_body: str, text_body: str | None = None) -> None:
    if not SMTP_USER:
        raise RuntimeError("SMTP_USER가 설정되지 않았습니다")
    if not SMTP_PASS:
        raise RuntimeError("SMTP_PASS가 설정되지 않았습니다")
    if not TO_EMAIL:
        raise RuntimeError("TO_EMAIL이 설정되지 않았습니다")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = TO_EMAIL

    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))

    msg.attach(MIMEText(html_body, "html", "utf-8"))

    logger.info(f"[EMAIL] sending email to {TO_EMAIL}")

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, [TO_EMAIL], msg.as_string())

    logger.info("[EMAIL] email sent successfully")