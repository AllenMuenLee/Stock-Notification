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

    def close(self):
        """關閉連線並釋放資源，避免 memory / connection leak"""
        if self._sdk is not None:
            try:
                self._sdk.logout()
                logger.info("富邦 SDK 登出成功")
            except Exception as exc:
                logger.error("富邦 SDK 登出失敗: %s", exc)
            self._sdk = None



# ────────────────────────────────────────────
# yfinance 歷史資料
# ────────────────────────────────────────────

def _yf_symbol(symbol: str, exchange: str = "TWSE") -> str:
    return symbol + (".TW" if exchange == "TWSE" else ".TWO")


import pickle
import os

CACHE_FILE = "historical_cache.pkl"

class HistoricalDataClient:
    """透過 yfinance 取得台股歷史資料。"""

    def __init__(self):
        self._history_cache: dict[str, pd.DataFrame | None] = {}
        self._shares_cache: dict[str, float] = {}
        self._rate_limited = False
        self.load_cache()

    def load_cache(self):
        today_str = date.today().isoformat()
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "rb") as f:
                    data = pickle.load(f)
                if data.get("date") == today_str:
                    self._history_cache = data.get("history", {})
                    self._shares_cache = data.get("shares", {})
                    logger.info("成功載入本日歷史資料快取 (共 %d 筆)", len(self._history_cache))
                else:
                    logger.info("快取已過期 (非今日)，建立新快取")
            except Exception as exc:
                logger.error("讀取快取失敗: %s", exc)

    def save_cache(self):
        today_str = date.today().isoformat()
        try:
            with open(CACHE_FILE, "wb") as f:
                pickle.dump({
                    "date": today_str,
                    # 只儲存成功的歷史資料，失敗的 (None 或 empty) 不儲存，留待下次執行重試
                    "history": {k: v for k, v in self._history_cache.items() if v is not None and not v.empty},
                    "shares": self._shares_cache
                }, f)
            logger.info("歷史資料快取已儲存 (共 %d 筆)", len(self._history_cache))
        except Exception as exc:
            logger.error("寫入快取失敗: %s", exc)

    def _get_history(self, symbol: str, exchange: str, period: str = "3mo") -> pd.DataFrame:
        # 排除大盤指數與類股指數 (通常以 IX 開頭)，避免浪費 API 請求
        if symbol.startswith("IX") or symbol.startswith("IR"):
            return pd.DataFrame()
            
        key = f"{symbol}:{exchange}:{period}"
        if key in self._history_cache:
            val = self._history_cache[key]
            return val if val is not None else pd.DataFrame()
            
        if self._rate_limited:
            # 如果已經觸發 Rate Limit 熔斷機制，本次執行不再發送獨立請求
            self._history_cache[key] = None
            return pd.DataFrame()

        yf_sym = _yf_symbol(symbol, exchange)
        try:
            df = yf.Ticker(yf_sym).history(period=period, auto_adjust=True)
            if df is not None and not df.empty:
                self._history_cache[key] = df
            else:
                self._history_cache[key] = None
                return pd.DataFrame()
        except Exception as exc:
            err_msg = str(exc)
            logger.error("yfinance %s 獨立抓取失敗: %s", yf_sym, err_msg)
            if "Rate limited" in err_msg or "429" in err_msg or "Too Many Requests" in err_msg:
                logger.warning("檢測到 yfinance Rate Limit，啟動熔斷機制，本次執行後續將不再發送獨立請求！")
                self._rate_limited = True
            
            self._history_cache[key] = None
            return pd.DataFrame()
            
        return self._history_cache.get(key, pd.DataFrame())

    def prefetch_all_history(self, symbol_exchanges: list[tuple[str, str]], period: str = "3mo"):
        """使用 yfinance 的 bulk download 一次性批次下載歷史資料，並具備 Rate Limit 重試機制"""
        import time
        logger.info(f"準備批次預載 {len(symbol_exchanges)} 檔歷史資料...")
        
        yf_sym_to_key = {}
        for sym, exch in symbol_exchanges:
            # 排除大盤指數與類股指數 (通常以 IX 或 IR 開頭)
            if sym.startswith("IX") or sym.startswith("IR"):
                continue
                
            key = f"{sym}:{exch}:{period}"
            if key not in self._history_cache:
                yf_sym_to_key[_yf_symbol(sym, exch)] = key
                
        yf_syms = list(yf_sym_to_key.keys())
        
        max_retries = 3
        retry_delay = 60  # Rate limit 恢復等待時間 (秒)
        chunk_size = 50
        
        for attempt in range(max_retries):
            if not yf_syms:
                logger.info("所有歷史資料皆已成功快取！")
                break
                
            logger.info(f"--- 第 {attempt + 1} 次嘗試下載 (共 {len(yf_syms)} 檔) ---")
            missing_syms = []
            
            for i in range(0, len(yf_syms), chunk_size):
                chunk = yf_syms[i:i+chunk_size]
                logger.info(f"下載歷史資料進度: {i}/{len(yf_syms)}...")
                
                import sys, io
                f_err = io.StringIO()
                old_stderr = sys.stderr
                sys.stderr = f_err
                
                df = None
                try:
                    df = yf.download(chunk, period=period, progress=False, threads=True)
                except Exception as e:
                    logger.error(f"批次下載歷史資料發生錯誤: {e}")
                finally:
                    sys.stderr = old_stderr
                    
                stderr_output = f_err.getvalue()
                permanently_failed = set()
                for line in stderr_output.splitlines():
                    if "delisted" in line.lower() or "no data found" in line.lower() or "not found" in line.lower():
                        for yf_sym in chunk:
                            if yf_sym in line:
                                permanently_failed.add(yf_sym)

                if df is not None and not df.empty:
                    if df.columns.nlevels == 2:
                        for yf_sym in chunk:
                            key = yf_sym_to_key[yf_sym]
                            try:
                                sub_df = df.xs(yf_sym, level=1, axis=1).dropna(how='all')
                                if not sub_df.empty:
                                    self._history_cache[key] = sub_df
                            except KeyError:
                                pass
                    elif len(chunk) == 1:
                        key = yf_sym_to_key[chunk[0]]
                        sub_df = df.dropna(how='all')
                        if not sub_df.empty:
                            self._history_cache[key] = sub_df
                
                # 檢查這批有哪些還沒抓到
                for yf_sym in chunk:
                    key = yf_sym_to_key[yf_sym]
                    if key not in self._history_cache or self._history_cache[key] is None or self._history_cache[key].empty:
                        if yf_sym in permanently_failed:
                            # 標記為空 DataFrame，避免進入 missing_syms 觸發 Rate Limit 的 60 秒重試
                            logger.debug(f"{yf_sym} 已下市或無資料，跳過重試")
                            self._history_cache[key] = pd.DataFrame()
                        else:
                            missing_syms.append(yf_sym)
                
                # 每批次結束休息 1.5 秒，避免觸發 API 連續請求限制
                time.sleep(1.5)
                
            if not missing_syms:
                logger.info("本輪下載所有排定的資料皆已完成！")
                break
                
            yf_syms = missing_syms
            if attempt < max_retries - 1:
                logger.warning(f"仍有 {len(missing_syms)} 檔資料遺漏或遇 Rate Limit 被擋。休息 {retry_delay} 秒等待限制解除後重試...")
                time.sleep(retry_delay)
            else:
                logger.error(f"達到最大重試次數 ({max_retries}次)，最終仍有 {len(missing_syms)} 檔資料無法取得 (可能已下市或無資料)。")

    def prefetch_all_shares(self):
        """一次性透過政府 OpenAPI 取得所有上市櫃公司的發行股數，避免 yfinance rate limit。"""
        import requests
        import urllib3
        urllib3.disable_warnings()
        
        twse_url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
        tpex_url = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
        
        try:
            logger.info("從 TWSE 獲取上市股本...")
            res = requests.get(twse_url, timeout=10)
            if res.status_code == 200:
                for item in res.json():
                    symbol = item.get("公司代號", "")
                    shares_str = item.get("已發行普通股數或TDR原股發行股數", "0")
                    if symbol and shares_str.isdigit():
                        self._shares_cache[f"{symbol}:TWSE"] = float(shares_str)
        except Exception as e:
            logger.error(f"TWSE 股本獲取失敗: {e}")

        try:
            logger.info("從 TPEx 獲取上櫃股本...")
            res = requests.get(tpex_url, verify=False, timeout=10)
            if res.status_code == 200:
                for item in res.json():
                    symbol = item.get("公司代號", "")
                    shares_str = item.get("已發行普通股數或TDR原股發行股數", "0")
                    if symbol and shares_str.isdigit():
                        self._shares_cache[f"{symbol}:TPEx"] = float(shares_str)
        except Exception as e:
            logger.error(f"TPEx 股本獲取失敗: {e}")
        
        logger.info(f"股本預載完成，共 {len(self._shares_cache)} 筆")

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

        if shares > 0:
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
        不含今日的近 5 個完整交易日平均成交量（單位：張/lot）。
        yfinance Volume 為「股」，除以 1000 換算為「張」。
        """
        df = self._get_history(symbol, exchange, period="3mo")
        if df.empty or "Volume" not in df.columns:
            return 0.0
        try:
            historical_df = df[pd.to_datetime(df.index).date < date.today()]
        except Exception:
            historical_df = df
        if historical_df.empty:
            historical_df = df
        return float(historical_df["Volume"].tail(5).mean() / _SHARES_PER_LOT)

    def clear_cache(self):
        """清除快取，幫助釋放記憶體"""
        self._history_cache.clear()
        self._shares_cache.clear()
