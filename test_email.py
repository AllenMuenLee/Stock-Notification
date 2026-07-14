import os
import yaml
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up some dummy data for the test
class DummyStock:
    def __init__(self):
        self.symbol = "2330"
        self.name = "台積電"
        self.price = 600.0
        self.price_change_pct = 1.5
        self.volume_ratio = 1.2
        self.turnover_rate_pct = 0.5
        self.market_cap_100m = 150000
        self.had_limit_up = False
        self.vwap_above_ratio = 0.8
        self.vwap_dip_ok = True

from notifier import EmailNotifier

def test_email():
    print("Loading config...")
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        print("config.yaml not found, using empty config.")
        config = {}

    print(f"EMAIL_SENDER in env: {os.environ.get('EMAIL_SENDER')}")
    print(f"EMAIL_RECIPIENT in env: {os.environ.get('EMAIL_RECIPIENT')}")
    
    try:
        notifier = EmailNotifier(config)
        print("Sending test email...")
        stocks = [DummyStock()]
        success = notifier.send(stocks)
        if success:
            print("Email sent successfully!")
        else:
            print("Failed to send email.")
    except Exception as e:
        print(f"Error during email initialization or sending: {e}")

if __name__ == "__main__":
    test_email()
