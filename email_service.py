import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Dict, Any

REVIEWS_LOG_FILE = os.path.join(os.path.dirname(__file__), "data", "reviews_log.txt")


def get_owner_email() -> str:
    """Gets the owner/admin email specified in .env or default fallback."""
    return os.getenv("OWNER_EMAIL") or os.getenv("ADMIN_EMAIL") or "owner@example.com"


def log_review_to_file(user_email: str, rating: int, review_text: str, owner_email: str, clips_count: int, delivery_status: str):
    """Appends review details to a local text log for persistent auditing."""
    os.makedirs(os.path.dirname(REVIEWS_LOG_FILE), exist_ok=True)
    stars = "★" * rating + "☆" * (5 - rating)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    entry = (
        f"===================================================\n"
        f"Time: {timestamp}\n"
        f"From User: {user_email}\n"
        f"Clips Generated: {clips_count}\n"
        f"Rating: {rating}/5 ({stars})\n"
        f"Review:\n{review_text}\n"
        f"Forwarded To: {owner_email}\n"
        f"Email Delivery Status: {delivery_status}\n"
        f"===================================================\n\n"
    )
    with open(REVIEWS_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(entry)


def send_review_email_to_owner(
    user_email: str,
    rating: int,
    review_text: str,
    clips_count: int = 15
) -> Dict[str, Any]:
    """
    Sends the user review directly to the owner email configured in .env.
    If SMTP credentials are provided, delivers via SMTP.
    Always logs to data/reviews_log.txt and terminal.
    """
    owner_email = get_owner_email()
    stars = "★" * rating + "☆" * (5 - rating)
    subject = f"🌟 New AI Shorts Studio User Review ({rating}/5 Stars) from {user_email}"

    # Plain text and HTML formats
    text_content = (
        f"New User Review Received:\n\n"
        f"• User Email: {user_email}\n"
        f"• Rating: {rating}/5 Stars ({stars})\n"
        f"• Clips Generated: {clips_count}\n"
        f"• Review Feedback:\n"
        f"---------------------------------------------------\n"
        f"{review_text}\n"
        f"---------------------------------------------------\n"
        f"Sent automatically from AI Viral Shorts Studio."
    )

    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #f8fafc; padding: 24px; color: #0f172a;">
        <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; padding: 24px; box-shadow: 0 4px 6px rgba(0,0,0,0.05);">
          <div style="background: #2563eb; color: #ffffff; padding: 12px 18px; border-radius: 8px; font-size: 18px; font-weight: bold;">
            ⭐ New User Review Received
          </div>
          <div style="margin-top: 20px; font-size: 15px;">
            <p><strong>User:</strong> {user_email}</p>
            <p><strong>Clips Generated:</strong> {clips_count}</p>
            <p><strong>Rating:</strong> <span style="color: #f59e0b; font-size: 18px; font-weight: bold;">{stars}</span> ({rating}/5)</p>
            <div style="margin-top: 16px; padding: 16px; background: #f1f5f9; border-left: 4px solid #2563eb; border-radius: 6px;">
              <p style="margin: 0; font-weight: bold; color: #475569; font-size: 12px; text-transform: uppercase;">Feedback Message:</p>
              <p style="margin: 8px 0 0 0; white-space: pre-wrap; font-size: 14px; color: #0f172a;">{review_text}</p>
            </div>
          </div>
          <div style="margin-top: 24px; border-top: 1px solid #e2e8f0; padding-top: 12px; font-size: 12px; color: #64748b;">
            This review was automatically submitted on AI Viral Shorts Studio and forwarded to {owner_email}.
          </div>
        </div>
      </body>
    </html>
    """

    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT") or "587")
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in ["true", "1", "yes"]

    status = "saved_locally"
    delivery_note = ""

    if smtp_user and smtp_password and smtp_host:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = smtp_user
            msg["To"] = owner_email

            part1 = MIMEText(text_content, "plain", "utf-8")
            part2 = MIMEText(html_content, "html", "utf-8")
            msg.attach(part1)
            msg.attach(part2)

            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                if use_tls:
                    server.starttls()
                server.login(smtp_user, smtp_password)
                server.sendmail(smtp_user, [owner_email], msg.as_string())

            status = "sent_via_smtp"
            delivery_note = f"Email sent directly to {owner_email} via SMTP"
            print(f"[Email Service] Successfully delivered review email to {owner_email}!")
        except Exception as e:
            status = f"smtp_error: {str(e)}"
            delivery_note = f"SMTP error ({str(e)}), review saved to local audit file."
            print(f"[Email Service Warning] Failed to send email via SMTP: {e}")
    else:
        delivery_note = f"SMTP not configured in .env. Review saved locally and routed to {owner_email}."
        print(f"[Email Service] Review received for {owner_email}. (To receive inbox emails, configure SMTP_USER/PASSWORD in .env)")

    log_review_to_file(user_email, rating, review_text, owner_email, clips_count, delivery_note)

    return {
        "success": True,
        "status": status,
        "owner_email": owner_email,
        "delivery_note": delivery_note
    }
