"""
主程式 — 排程執行入口

用法:
  python main.py              → 啟動排程（每日 13:00 執行）
  python main.py --run-now   → 忽略排程，立即執行一次篩選
  python main.py --schedule  → 同無參數（顯式排程模式）
  python ui.py               → 開啟圖形設定介面
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

import yaml
from dotenv import load_dotenv

from logger_setup import setup_logger
from notifier import EmailNotifier
from screener import ScreenedStock, ScreeningConfig, StockScreener
from trading_calendar import is_trading_day

load_dotenv()
logger = setup_logger("main")


# ────────────────────────────────────────────
# 設定載入
# ────────────────────────────────────────────

def load_config(path: str = "config.yaml") -> dict:
    if not os.path.exists(path):
        logger.error("找不到設定檔 %s，請先執行 ui.py 完成設定", path)
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ────────────────────────────────────────────
# 核心篩選流程
# ────────────────────────────────────────────

def run_screening(config: dict) -> list[ScreenedStock]:
    logger.info("═" * 50)
    logger.info("開始執行股票篩選 (%s)", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    if not is_trading_day():
        logger.info("今日非台股交易日，略過篩選")
        return []

    screening_cfg = ScreeningConfig.from_dict(config)
    screener = StockScreener(screening_cfg)

    try:
        passed_stocks = screener.run()
    except Exception as exc:
        logger.exception("篩選過程發生未預期錯誤: %s", exc)
        return []

    try:
        notifier = EmailNotifier(config)
        notifier.send(passed_stocks)
    except Exception as exc:
        logger.error("通知發送失敗: %s", exc)

    logger.info("本次篩選結束，共 %d 檔符合條件", len(passed_stocks))
    logger.info("═" * 50)
    return passed_stocks


# ────────────────────────────────────────────
# 排程
# ────────────────────────────────────────────

def start_scheduler(config: dict):
    import schedule

    run_time = config.get("schedule", {}).get("run_time", "13:00")
    logger.info("排程啟動，將於每個交易日 %s 執行篩選", run_time)

    schedule.every().day.at(run_time).do(run_screening, config=config)

    while True:
        schedule.run_pending()
        time.sleep(30)


# ────────────────────────────────────────────
# CLI 入口
# ────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="股票自動篩選通知系統")
    parser.add_argument("--run-now", action="store_true", help="立即執行一次篩選")
    parser.add_argument("--schedule", action="store_true", help="啟動排程模式")
    parser.add_argument("--config", default="config.yaml", help="設定檔路徑")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.run_now:
        run_screening(config)
    else:
        start_scheduler(config)


if __name__ == "__main__":
    main()
