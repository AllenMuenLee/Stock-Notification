"""
Email 通知模組

使用 smtplib 透過 Gmail SMTP 發送 HTML 格式的篩選報告。
"""

from __future__ import annotations

import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING

from logger_setup import setup_logger

if TYPE_CHECKING:
    from screener import ScreenedStock

logger = setup_logger("notifier")


def _build_html(stocks: list["ScreenedStock"], run_time: str) -> str:
    if not stocks:
        body = "<p>今日無符合篩選條件的股票。</p>"
    else:
        rows = ""
        for s in stocks:
            rows += f"""
            <tr>
                <td>{s.symbol}</td>
                <td>{s.name}</td>
                <td style="color:{'#cc0000' if s.price_change_pct > 0 else '#006600'}">
                    {s.price:.2f} ({s.price_change_pct:+.2f}%)
                </td>
                <td>{s.volume_ratio:.2f}x</td>
                <td>{s.turnover_rate_pct:.2f}%</td>
                <td>{s.market_cap_100m:.0f}億</td>
                <td>{'✅' if s.had_limit_up else '❌'}</td>
                <td>{s.vwap_above_ratio:.0%}</td>
                <td>{'✅' if s.vwap_dip_ok else '❌'}</td>
            </tr>"""

        body = f"""
        <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse; font-family:monospace;">
            <thead style="background:#1a4a8a; color:white;">
                <tr>
                    <th>代號</th><th>名稱</th><th>股價 / 漲幅</th>
                    <th>量比</th><th>換手率</th><th>市值</th>
                    <th>近期漲停</th><th>VWAP上方%</th><th>回踩有撐</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>"""

    return f"""
    <html><body style="font-family:Arial,sans-serif; color:#333;">
        <h2 style="color:#1a4a8a;">📈 每日股票篩選報告</h2>
        <p>篩選時間：<strong>{run_time}</strong>　符合條件：<strong>{len(stocks)} 檔</strong></p>
        {body}
        <hr/>
        <p style="font-size:12px;color:#999;">本報告由自動篩選系統產生，不構成投資建議。</p>
    </body></html>"""


class EmailNotifier:
    def __init__(self, config: dict):
        cfg = config.get("notification", {})
        self.subject: str = cfg.get("subject", "【每日股票篩選報告】")
        self.to_emails: list[str] = [
            e.strip()
            for e in cfg.get("to_email", os.getenv("EMAIL_RECIPIENT", "")).split(",")
            if e.strip()
        ]
        self.send_if_empty: bool = cfg.get("send_if_empty", True)

        self.sender: str = os.environ["EMAIL_SENDER"]
        self.password: str = os.environ["EMAIL_APP_PASSWORD"]
        self.smtp_host: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port: int = int(os.getenv("SMTP_PORT", "587"))

    def send(self, stocks: list["ScreenedStock"]) -> bool:
        if not stocks and not self.send_if_empty:
            logger.info("無符合條件股票且 send_if_empty=false，略過發信")
            return True
        if not self.to_emails:
            logger.error("未設定收件人 Email，請確認 config.yaml 或 .env")
            return False

        run_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        subject = f"{self.subject} {run_time[:10]}　共 {len(stocks)} 檔"
        html_body = _build_html(stocks, run_time)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.sender
        msg["To"] = ", ".join(self.to_emails)
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.login(self.sender, self.password)
                smtp.sendmail(self.sender, self.to_emails, msg.as_string())
            logger.info("Email 發送成功 → %s", self.to_emails)
            return True
        except smtplib.SMTPAuthenticationError:
            logger.error("Gmail 驗證失敗，請確認 EMAIL_APP_PASSWORD 是否為應用程式密碼")
            return False
        except Exception as exc:
            logger.error("Email 發送失敗: %s", exc)
            return False
