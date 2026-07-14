"""
主程式 — 排程執行入口

用法:
  python main.py              → 啟動排程（每日 13:00 執行）
  python main.py --run-now   → 忽略排程，立即執行一次篩選
  python main.py --schedule  → 同無參數（顯式排程模式）
  streamlit run ui.py        → 開啟網頁設定介面
"""

from __future__ import annotations

import argparse
import dataclasses
import json
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

RESULTS_DIR = "results"
RESULTS_FILE = os.path.join(RESULTS_DIR, "latest_run.json")


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
# 結果儲存
# ────────────────────────────────────────────

def save_results(all_stocks: list[ScreenedStock], run_time: str) -> None:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    payload = {
        "run_time": run_time,
        "total_evaluated": len(all_stocks),
        "passed": sum(1 for s in all_stocks if s.pass_all),
        "stocks": [dataclasses.asdict(s) for s in all_stocks],
    }
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info("篩選明細已儲存至 %s", RESULTS_FILE)


# ────────────────────────────────────────────
# 核心篩選流程
# ────────────────────────────────────────────

def run_screening(config: dict) -> list[ScreenedStock]:
    logger.info("═" * 50)
    run_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info("開始執行股票篩選 (%s)", run_time)

    if not is_trading_day():
        logger.info("今日非台股交易日，略過篩選")
        return []

    screening_cfg = ScreeningConfig.from_dict(config)
    screener = StockScreener(screening_cfg)

    passed_stocks = []
    try:
        # 確保在執行篩選前，歷史資料皆已透過批次機制 (具備重試與略過保護) 載入
        screener.prefetch()
        
        all_stocks = screener.run()
        passed_stocks = [s for s in all_stocks if s.pass_all]
        save_results(all_stocks, run_time)

        try:
            notifier = EmailNotifier(config)
            notifier.send(passed_stocks)
        except Exception as exc:
            logger.error("通知發送失敗: %s", exc)

        logger.info("本次篩選結束，共 %d 檔符合條件", len(passed_stocks))
    except Exception as exc:
        logger.exception("篩選過程發生未預期錯誤: %s", exc)
    finally:
        screener.close()
        import gc
        gc.collect()

    logger.info("═" * 50)
    return passed_stocks


def run_prefetch(config: dict) -> None:
    logger.info("═" * 50)
    logger.info("開始執行背景預先載入歷史資料 (Prefetch)")
    if not is_trading_day():
        logger.info("今日非台股交易日，略過預先載入")
        return

    screening_cfg = ScreeningConfig.from_dict(config)
    screener = StockScreener(screening_cfg)
    try:
        screener.prefetch()
    except Exception as exc:
        logger.exception("預先載入發生錯誤: %s", exc)
    finally:
        screener.close()
        import gc
        gc.collect()
    logger.info("═" * 50)


# ────────────────────────────────────────────
# 排程
# ────────────────────────────────────────────

def start_scheduler(config_path: str):
    import schedule
    from datetime import datetime, timedelta
    import socket
    import sys

    # 確保只有一個排程實例在執行 (使用 Socket Bind 機制)
    lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock_socket.bind(("127.0.0.1", 65432))
    except socket.error:
        logger.warning("排程已經在執行中，忽略本次啟動。")
        sys.exit(0)

    last_run_time = None

    def scheduled_prefetch():
        load_dotenv(override=True)
        run_prefetch(load_config(config_path))
        
    def scheduled_screening():
        load_dotenv(override=True)
        run_screening(load_config(config_path))

    while True:
        # 動態重新載入設定以取得最新排程時間
        current_config = load_config(config_path)
        current_run_time = current_config.get("schedule", {}).get("run_time", "13:00")
        
        if current_run_time != last_run_time:
            schedule.clear()
            
            # 計算 prefetch_time (提前 30 分鐘)
            try:
                rt = datetime.strptime(current_run_time, "%H:%M")
                pt = rt - timedelta(minutes=30)
                prefetch_time = pt.strftime("%H:%M")
            except ValueError:
                prefetch_time = "12:55"
                current_run_time = "13:00"

            logger.info("排程設定更新，每日 %s 預載資料，%s 執行篩選", prefetch_time, current_run_time)
            
            schedule.every().day.at(prefetch_time).do(scheduled_prefetch)
            schedule.every().day.at(current_run_time).do(scheduled_screening)
            
            last_run_time = current_run_time

        schedule.run_pending()
        time.sleep(30)


# ────────────────────────────────────────────
# CLI 入口
# ────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="股票自動篩選通知系統")
    parser.add_argument("--run-now", action="store_true", help="立即執行一次篩選")
    parser.add_argument("--prefetch", action="store_true", help="立即執行一次歷史資料預先載入")
    parser.add_argument("--schedule", action="store_true", help="啟動排程模式")
    parser.add_argument("--config", default="config.yaml", help="設定檔路徑")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.prefetch:
        run_prefetch(config)
    elif args.run_now:
        run_screening(config)
    else:
        start_scheduler(args.config)


if __name__ == "__main__":
    main()
