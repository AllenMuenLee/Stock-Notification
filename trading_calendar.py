"""
判斷台股交易日。

優先使用 TWSE 公開的休市日曆 API（不需登入）。
若 API 不可用，退回以「非週末且非固定假日」的近似判斷。
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import requests

from logger_setup import setup_logger

logger = setup_logger("trading_calendar")

# TWSE 公開的休市日程 (無需 Token)
_TWSE_HOLIDAY_URL = (
    "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule"
    "?response=json"
)


@lru_cache(maxsize=2)
def _fetch_holiday_dates(year: int) -> set[date]:
    """從 TWSE 取得指定年度的所有休市日期。"""
    try:
        resp = requests.get(_TWSE_HOLIDAY_URL, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        holidays: set[date] = set()
        for row in payload.get("data", []):
            # row[0] 為日期字串，格式可能是 "113/01/01"(民國) 或 "20240101"
            raw = str(row[0]).strip()
            if "/" in raw:
                # 民國年 → 西元年
                parts = raw.split("/")
                ad_year = int(parts[0]) + 1911
                d = date(ad_year, int(parts[1]), int(parts[2]))
            elif len(raw) == 8:
                d = date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
            else:
                continue
            if d.year == year:
                holidays.add(d)
        logger.info("已載入 %d 年休市日期 %d 筆", year, len(holidays))
        return holidays
    except Exception as exc:
        logger.warning("無法取得 TWSE 休市日曆: %s，改用近似法判斷", exc)
        return set()


def is_trading_day(target: date | None = None) -> bool:
    """回傳 target（預設今日）是否為台股交易日。"""
    if target is None:
        target = date.today()

    if target.weekday() >= 5:   # 週六、週日
        return False

    holidays = _fetch_holiday_dates(target.year)
    if holidays:
        return target not in holidays

    # 退回近似法：僅排除元旦與國慶日等固定假日
    fixed = {(1, 1), (2, 28), (4, 4), (4, 5), (5, 1), (10, 10)}
    return (target.month, target.day) not in fixed


def next_trading_day(from_date: date | None = None) -> date:
    d = (from_date or date.today()) + timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d
