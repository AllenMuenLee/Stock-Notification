"""
股票篩選邏輯

依據 config.yaml 中的參數，對即時快照與歷史資料進行多條件篩選。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from data_fetcher import FubonRealtimeClient, HistoricalDataClient
from logger_setup import setup_logger

logger = setup_logger("screener")

@dataclass
class ScreeningConfig:
    price_change_min: float = 3.0
    price_change_max: float = 5.0
    volume_ratio_min: float = 1.0
    turnover_rate_min: float = 5.0
    turnover_rate_max: float = 10.0
    market_cap_min_100m: float = 200.0
    market_cap_max_100m: float = 1000.0
    limit_up_lookback_days: int = 20
    vwap_above_ratio_min: float = 0.70
    vwap_dip_tolerance_pct: float = 0.5
    vwap_recovery_bars: int = 3

    @staticmethod
    def from_dict(d: dict) -> "ScreeningConfig":
        s = d.get("screening", {})
        fields = {k for k in ScreeningConfig.__dataclass_fields__}
        return ScreeningConfig(**{k: v for k, v in s.items() if k in fields})


@dataclass
class ScreenedStock:
    symbol: str
    name: str
    price: float
    price_change_pct: float
    volume_ratio: float
    turnover_rate_pct: float
    market_cap_100m: float
    had_limit_up: bool
    vwap_above_ratio: float
    vwap_dip_ok: bool
    pass_all: bool
    fail_reasons: list[str] = field(default_factory=list)


# ────────────────────────────────────────────
# VWAP 分析
# ────────────────────────────────────────────

def _calc_vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    cum_pv = (typical * df["volume"]).cumsum()
    cum_v = df["volume"].cumsum()
    return cum_pv / cum_v.replace(0, np.nan)


def _analyze_vwap(df: pd.DataFrame, cfg: ScreeningConfig) -> tuple[float, bool]:
    """
    回傳 (vwap_above_ratio, dip_recovery_ok)
    - vwap_above_ratio: 收盤在 VWAP 上方的 bar 比例
    - dip_recovery_ok: 是否符合「回踩有撐」特徵
    """
    if df.empty or len(df) < 5:
        return 0.0, False

    vwap = _calc_vwap(df)
    close = df["close"]
    above_ratio = float((close > vwap).sum() / len(df))

    tol = cfg.vwap_dip_tolerance_pct / 100
    dip_found = False
    recovery_ok = True

    for i in range(len(df)):
        v = vwap.iloc[i]
        c = close.iloc[i]
        if pd.isna(v) or pd.isna(c) or v == 0:
            continue
        dist = (c - v) / v
        if -tol <= dist <= tol:
            dip_found = True
            recovered = False
            end = min(i + 1 + cfg.vwap_recovery_bars, len(df))
            for j in range(i + 1, end):
                if close.iloc[j] > vwap.iloc[j]:
                    recovered = True
                    break
            if not recovered and end < len(df):
                recovery_ok = False
                break

    if not dip_found:
        recovery_ok = True

    return above_ratio, recovery_ok


def _to_float(value: object) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _snapshot_volume_lots(snap: dict) -> float:
    # totalVolume is cumulative traded volume; lastSize is only the latest fill.
    for key in ("totalVolume", "total_volume", "volume", "tradeVolume"):
        volume = _to_float(snap.get(key))
        if volume > 0:
            return volume
    return 0.0


# ────────────────────────────────────────────
# 主篩選器
# ────────────────────────────────────────────

class StockScreener:
    def __init__(self, config: ScreeningConfig):
        self.cfg = config
        self.realtime = FubonRealtimeClient()
        self.historical = HistoricalDataClient()

    def close(self):
        """釋放連線與記憶體資源"""
        self.realtime.close()
        self.historical.save_cache()
        self.historical.clear_cache()

    def prefetch(self):
        """預先抓取符合漲幅條件之股票的歷史靜態資料（如股本、5日均量、歷史K線）並寫入快取"""
        logger.info("開始執行歷史資料預先載入 (Prefetch)...")
        try:
            snapshots = self.realtime.get_all_snapshots()
        except RuntimeError as exc:
            logger.error("無法取得即時快照: %s", exc)
            return

        def _fetch_static_data(snap: dict):
            symbol = str(snap.get("symbol", snap.get("code", "")))
            if not symbol:
                return

            # --- 先用即時快照檢查漲幅，只有符合條件的才抓取歷史資料 ---
            close = _to_float(snap.get("closePrice") or snap.get("close") or snap.get("lastPrice"))
            prev_close = _to_float(snap.get("referencePrice") or snap.get("previousClose"))
            if prev_close and prev_close > 0:
                pct_change = (close - prev_close) / prev_close * 100
            else:
                pct_change = _to_float(snap.get("changePercent", snap.get("change_pct")))

            if not (self.cfg.price_change_min <= pct_change <= self.cfg.price_change_max):
                return
            # ---------------------------------------------------------

            raw_exchange = snap.get("_exchange", snap.get("exchange", "TWSE"))
            exchange = "TWSE" if ("TWSE" in raw_exchange or "TSE" in raw_exchange) else "TPEx"
            
            # 觸發快取
            self.historical.get_5day_avg_volume(symbol, exchange)
            self.historical.get_shares_outstanding(symbol, exchange)
            self.historical.had_limit_up_recently(symbol, exchange, self.cfg.limit_up_lookback_days)

        logger.info("準備過濾並為可能符合條件的股票預先抓取資料...")
        
        from concurrent.futures import ThreadPoolExecutor, as_completed
        # 預先抓取可以使用多一點執行緒，因為不包含複雜運算
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(_fetch_static_data, snap) for snap in snapshots]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    pass
        
        self.historical.save_cache()
        logger.info("預先載入完成！")

    def run(self) -> list[ScreenedStock]:
        logger.info("開始執行股票篩選...")

        logger.info("取得即時快照...")
        try:
            snapshots = self.realtime.get_all_snapshots()
        except RuntimeError as exc:
            logger.error("無法取得即時快照: %s", exc)
            return []
        logger.info("共取得 %d 檔股票快照", len(snapshots))

        all_stocks: list[ScreenedStock] = []
        
        # 使用 ThreadPoolExecutor 加速多檔股票的 yfinance 歷史資料請求
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_snap = {
                executor.submit(self._evaluate, snap): snap 
                for snap in snapshots
            }
            for future in as_completed(future_to_snap):
                try:
                    stock = future.result()
                    all_stocks.append(stock)
                except Exception as exc:
                    logger.error("評估股票時發生例外: %s", exc)
                    snap = future_to_snap[future]
                    all_stocks.append(self._failed_stock_from_snapshot(snap, f"評估失敗: {exc}"))

        passed_count = sum(1 for s in all_stocks if s.pass_all)
        logger.info("篩選完成，符合條件: %d / 評估: %d / 快照: %d",
                    passed_count, len(all_stocks), len(snapshots))
        return all_stocks

    def _evaluate(self, snap: dict) -> ScreenedStock:
        try:
            symbol = str(snap.get("symbol", snap.get("code", "")))
            if not symbol:
                return self._failed_stock_from_snapshot(snap, "缺少股票代號")
            return self._evaluate_inner(snap)
        except Exception as exc:
            symbol = snap.get("symbol", snap.get("code", "?"))
            logger.warning("評估 %s 發生例外: %s", symbol, exc)
            return self._failed_stock_from_snapshot(snap, f"評估失敗: {exc}")

    def _evaluate_inner(self, snap: dict) -> ScreenedStock:
        symbol: str = str(snap.get("symbol", snap.get("code", "")))
        name: str = snap.get("name", symbol)
        # 判斷交易所，供 yfinance 加後綴 (.TW / .TWO)
        raw_exchange: str = snap.get("_exchange", snap.get("exchange", "TWSE"))
        exchange = "TWSE" if ("TWSE" in raw_exchange or "TSE" in raw_exchange) else "TPEx"

        # Fugle snapshot 欄位名稱：closePrice, referencePrice, totalVolume
        close = _to_float(
            snap.get("closePrice") or snap.get("close") or snap.get("lastPrice")
        )
        prev_close = _to_float(
            snap.get("referencePrice") or snap.get("previousClose")
        )
        volume_lots = _snapshot_volume_lots(snap)

        fail_reasons: list[str] = []

        # ── 1. 漲幅 ──────────────────────────────────────
        if prev_close and prev_close > 0:
            pct_change = (close - prev_close) / prev_close * 100
        else:
            pct_change = _to_float(snap.get("changePercent", snap.get("change_pct")))

        if not (self.cfg.price_change_min <= pct_change <= self.cfg.price_change_max):
            fail_reasons.append(
                f"漲幅 {pct_change:.2f}% ∉ [{self.cfg.price_change_min}, {self.cfg.price_change_max}]%"
            )

        # ── 2. 量比 ──────────────────────────────────────
        volume_ratio = 0.0
        avg5_lots = self.historical.get_5day_avg_volume(symbol, exchange)
        if avg5_lots > 0:
            volume_ratio = volume_lots / avg5_lots
            
        if volume_ratio < self.cfg.volume_ratio_min:
            fail_reasons.append(f"量比 {volume_ratio:.2f} < {self.cfg.volume_ratio_min}")

        # ── 3. 換手率 ─────────────────────────────────────
        turnover_rate = 0.0
        shares = self.historical.get_shares_outstanding(symbol, exchange)
        # 發行股數 (股)；Fubon 累計成交量為張，需 × 1000 換算
        if shares > 0 and volume_lots > 0:
            volume_shares = volume_lots * 1000
            turnover_rate = volume_shares / shares * 100
            
        if not (self.cfg.turnover_rate_min <= turnover_rate <= self.cfg.turnover_rate_max):
            fail_reasons.append(
                f"換手率 {turnover_rate:.2f}% ∉ [{self.cfg.turnover_rate_min}, {self.cfg.turnover_rate_max}]%"
            )

        # ── 4. 市值 ───────────────────────────────────────
        market_cap_100m = 0.0
        if shares > 0 and close > 0:
            market_cap_100m = close * shares / 1e8
            
        if not (self.cfg.market_cap_min_100m <= market_cap_100m <= self.cfg.market_cap_max_100m):
            fail_reasons.append(
                f"市值 {market_cap_100m:.0f}億 ∉ [{self.cfg.market_cap_min_100m:.0f}, {self.cfg.market_cap_max_100m:.0f}]億"
            )

        # ── 5. 近期漲停（僅前四項都通過才查詢，節省 API）────
        had_limit_up = False
        if not fail_reasons:
            had_limit_up = self.historical.had_limit_up_recently(
                symbol, exchange, self.cfg.limit_up_lookback_days
            )
            if not had_limit_up:
                fail_reasons.append(f"近 {self.cfg.limit_up_lookback_days} 日無漲停紀錄")

        # ── 6. VWAP 分析（僅前五項都通過才查詢）────────────
        vwap_above_ratio = 0.0
        vwap_dip_ok = False
        if not fail_reasons:
            candles = self.realtime.get_minute_candles(symbol)
            if not candles.empty:
                vwap_above_ratio, vwap_dip_ok = _analyze_vwap(candles, self.cfg)

            if vwap_above_ratio < self.cfg.vwap_above_ratio_min:
                fail_reasons.append(
                    f"VWAP 上方比例 {vwap_above_ratio:.0%} < {self.cfg.vwap_above_ratio_min:.0%}"
                )
            if not vwap_dip_ok:
                fail_reasons.append("回踩均線後無有效承接")

        return ScreenedStock(
            symbol=symbol,
            name=name,
            price=close,
            price_change_pct=round(pct_change, 2),
            volume_ratio=round(volume_ratio, 2),
            turnover_rate_pct=round(turnover_rate, 2),
            market_cap_100m=round(market_cap_100m, 1),
            had_limit_up=had_limit_up,
            vwap_above_ratio=round(vwap_above_ratio, 3),
            vwap_dip_ok=vwap_dip_ok,
            pass_all=not fail_reasons,
            fail_reasons=fail_reasons,
        )

    def _failed_stock_from_snapshot(self, snap: dict, reason: str) -> ScreenedStock:
        symbol = str(snap.get("symbol", snap.get("code", "")) or "?")
        name = snap.get("name", symbol)
        close = _to_float(snap.get("closePrice") or snap.get("close") or snap.get("lastPrice"))
        prev_close = _to_float(snap.get("referencePrice") or snap.get("previousClose"))
        if prev_close > 0:
            pct_change = (close - prev_close) / prev_close * 100
        else:
            pct_change = _to_float(snap.get("changePercent", snap.get("change_pct")))

        return ScreenedStock(
            symbol=symbol,
            name=name,
            price=close,
            price_change_pct=round(pct_change, 2),
            volume_ratio=0.0,
            turnover_rate_pct=0.0,
            market_cap_100m=0.0,
            had_limit_up=False,
            vwap_above_ratio=0.0,
            vwap_dip_ok=False,
            pass_all=False,
            fail_reasons=[reason],
        )
