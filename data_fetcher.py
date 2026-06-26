"""
資料抓取模組

即時資料：富邦 Neo API → fugle_marketdata REST client
  - 快照：sdk.marketdata.rest_client.stock.snapshot.quotes(market='TSE'|'OTC')
  - 分鐘K棒：sdk.marketdata.rest_client.stock.intraday.candles(symbol=..., timeframe='1')

歷史資料：yfinance (台股代號格式：2330.TW / 3008.TWO)
"""

from __future__ import annotations

import os
from datetime import date

import pandas as pd
import yfinance as yf

from logger_setup import setup_logger

logger = setup_logger("data_fetcher")

# 台股 1 張 = 1000 股；yfinance Volume 單位為「股」
_SHARES_PER_LOT = 1000


# ────────────────────────────────────────────
# 富邦 Neo API 即時資料
# ────────────────────────────────────────────

class FubonRealtimeClient:
    """封裝富邦 Neo API，提供即時報價與分時資料。"""

    def __init__(self):
        self._sdk = None

    def _get_sdk(self):
        if self._sdk is not None:
            return self._sdk

        try:
            from fubon_neo.sdk import FubonSDK  # type: ignore
        except ImportError:
            raise RuntimeError("fubon_neo 套件未安裝，請執行: pip install fubon_neo")

        account  = os.environ.get("FUBON_ACCOUNT", "")
        password = os.environ.get("FUBON_PASSWORD", "")
        cert     = os.environ.get("FUBON_CERT_PATH", "")
        cert_pw  = os.environ.get("FUBON_CERT_PASSWORD", "")

        if not account or not password or not cert:
            raise RuntimeError(
                "富邦 API 帳號/密碼/憑證路徑未設定，"
                "請至 UI「API 設定」頁籤填寫後儲存"
            )
        if not os.path.exists(cert):
            raise RuntimeError(
                f"找不到憑證檔案：{cert}\n"
                "請確認 FUBON_CERT_PATH 路徑正確"
            )

        sdk = FubonSDK()
        try:
            accounts = sdk.login(account, password, cert, cert_pw)
            logger.info("富邦 SDK 登入成功")
            if not accounts.is_success:
                raise RuntimeError(f"登入失敗: {accounts.message}")
        except Exception as exc:
            raise RuntimeError(f"富邦 SDK 登入失敗: {exc}") from exc

        try:
            sdk.init_realtime()
            
        except Exception as exc:
            raise RuntimeError(
                f"富邦 SDK init_realtime 失敗: {exc}\n"
                "可能原因：帳號密碼錯誤、憑證過期、或網路無法連線"
            ) from exc

        self._sdk = sdk
        logger.info("富邦 Neo API 登入並初始化成功")
        return sdk

    @property
    def _rest(self):
        return self._get_sdk().marketdata.rest_client

    def get_all_snapshots(self) -> list[dict]:
        """
        取得台股全體即時快照。
        API: stock.snapshot.quotes(market='TSE') 與 market='OTC'
        回傳列表，每個元素為一檔股票的快照 dict，
        並附加 '_exchange' 欄位 ('TWSE' 或 'TPEx')。
        """
        results: list[dict] = []
        for market, exchange in (("TSE", "TWSE"), ("OTC", "TPEx")):
            try:
                resp = self._rest.stock.snapshot.quotes(market=market)
                # resp 為 dict，資料在 resp['data']
                data = resp.get("data", []) if isinstance(resp, dict) else []
                for item in data:
                    item["_exchange"] = exchange
                results.extend(data)
                logger.info("取得 %s 快照 %d 筆", exchange, len(data))
            except Exception as exc:
                logger.error("抓取 %s 快照失敗: %s", exchange, exc)
        return results

    def get_minute_candles(self, symbol: str) -> pd.DataFrame:
        """
        取得今日分鐘 K 棒。
        API: stock.intraday.candles(symbol=..., timeframe='1')
        回傳 DataFrame 欄位: time, open, high, low, close, volume
        """
        try:
            resp = self._rest.stock.intraday.candles(symbol=symbol, timeframe="1")
            data = resp.get("data", []) if isinstance(resp, dict) else []
            if not data:
                return pd.DataFrame()

            df = pd.DataFrame(data)
            df.columns = [c.lower() for c in df.columns]

            # time 欄位可能是 Unix ms 時間戳
            if "time" in df.columns:
                ts = pd.to_numeric(df["time"], errors="coerce")
                if ts.iloc[0] > 1e10:   # ms 時間戳
                    df["time"] = pd.to_datetime(ts, unit="ms", utc=True).dt.tz_convert("Asia/Taipei")
                else:
                    df["time"] = pd.to_datetime(df["time"])
                df = df.sort_values("time").reset_index(drop=True)

            for col in ("open", "high", "low", "close", "volume"):
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

            return df
        except Exception as exc:
            logger.error("取得 %s 分鐘 K 棒失敗: %s", symbol, exc)
            return pd.DataFrame()


# ────────────────────────────────────────────
# yfinance 歷史資料
# ────────────────────────────────────────────

def _yf_symbol(symbol: str, exchange: str = "TWSE") -> str:
    return symbol + (".TW" if exchange == "TWSE" else ".TWO")


class HistoricalDataClient:
    """透過 yfinance 取得台股歷史資料。"""

    def __init__(self):
        self._history_cache: dict[str, pd.DataFrame] = {}
        self._shares_cache: dict[str, float] = {}

    def _get_history(self, symbol: str, exchange: str, period: str = "2mo") -> pd.DataFrame:
        key = f"{symbol}:{exchange}:{period}"
        if key not in self._history_cache:
            yf_sym = _yf_symbol(symbol, exchange)
            try:
                df = yf.Ticker(yf_sym).history(period=period, auto_adjust=True)
                self._history_cache[key] = df
            except Exception as exc:
                logger.error("yfinance %s 失敗: %s", yf_sym, exc)
                self._history_cache[key] = pd.DataFrame()
        return self._history_cache[key]

    def get_shares_outstanding(self, symbol: str, exchange: str = "TWSE") -> float:
        """取得發行股數（單位：股）。結果快取於 session 中。"""
        key = f"{symbol}:{exchange}"
        if key in self._shares_cache:
            return self._shares_cache[key]

        yf_sym = _yf_symbol(symbol, exchange)
        shares = 0.0
        try:
            val = getattr(yf.Ticker(yf_sym).fast_info, "shares", None)
            if val and val > 0:
                shares = float(val)
        except Exception:
            pass

        if shares == 0:
            try:
                info = yf.Ticker(yf_sym).info
                val = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding") or 0
                shares = float(val)
            except Exception as exc:
                logger.debug("無法取得 %s 股本: %s", yf_sym, exc)

        self._shares_cache[key] = shares
        return shares

    def had_limit_up_recently(
        self, symbol: str, exchange: str = "TWSE", lookback_trading_days: int = 20
    ) -> bool:
        """近 lookback_trading_days 個交易日內是否有漲停（漲幅 >= 9.5%）。"""
        df = self._get_history(symbol, exchange, period="3mo")
        if df.empty or len(df) < 2:
            return False
        pct = df["Close"].tail(lookback_trading_days + 1).pct_change().dropna() * 100
        return bool((pct >= 9.5).any())

    def get_5day_avg_volume(self, symbol: str, exchange: str = "TWSE") -> float:
        """
        近 5 個交易日平均成交量（單位：張/lot）。
        yfinance Volume 為「股」，除以 1000 換算為「張」。
        """
        df = self._get_history(symbol, exchange, period="15d")
        if df.empty or "Volume" not in df.columns:
            return 0.0
        return float(df["Volume"].tail(5).mean() / _SHARES_PER_LOT)
