"""
網頁版參數設定 UI (Streamlit)

使用 Streamlit 提供視覺化介面讓使用者調整篩選參數與通知設定。
執行方式：streamlit run ui.py
"""

import json
import os
import subprocess
import sys
import threading
import yaml
import hmac
import streamlit as st

CONFIG_FILE = "config.yaml"
ENV_FILE = ".env"
RESULTS_FILE = os.path.join("results", "latest_run.json")


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}

def save_config(data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

def load_env():
    env = {}
    path = ENV_FILE if os.path.exists(ENV_FILE) else ".env.example"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip()
    return env

def save_env(data):
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write("# 自動產生 — 請勿上傳此檔案到版本控制\n")
        for k, v in data.items():
            f.write(f"{k}={v}\n")


st.set_page_config(page_title="股票自動篩選系統 — 參數設定", layout="centered")
st.title("股票自動篩選系統 — 參數設定")

config_data = load_config()
env_data = load_env()

if "show_details" not in st.session_state:
    st.session_state.show_details = False
if "is_running" not in st.session_state:
    st.session_state.is_running = False
if "run_logs" not in st.session_state:
    st.session_state.run_logs = []
if "page" not in st.session_state:
    st.session_state.page = 0

sc = config_data.get("screening", {})
nt = config_data.get("notification", {})
sh = config_data.get("schedule", {})

def check_password():
    """驗證密碼"""
    expected_password = env_data.get("UI_PASSWORD")

    if not expected_password:
        st.warning("⚠️ 系統尚未設定管理介面密碼！為了您的安全，請直接修改伺服器上的 `.env` 檔案，新增 `UI_PASSWORD=您的密碼`，然後重新整理網頁。")
        return False

    def password_entered():
        if hmac.compare_digest(st.session_state["password"], expected_password):
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.text_input("🔒 請輸入系統密碼以解鎖管理介面", type="password", on_change=password_entered, key="password")
    if "password_correct" in st.session_state and not st.session_state["password_correct"]:
        st.error("😕 密碼錯誤，請重試。")
    return False

if not check_password():
    st.stop()

tab1, tab2, tab3, tab4 = st.tabs(["篩選條件", "通知設定", "API 設定", "執行 / 狀態"])

with tab1:
    st.info("調整後請點擊最下方的「儲存所有設定」即生效。所有數值在下次執行時套用。")
    st.subheader("漲幅 & 量能")
    col1, col2, col3 = st.columns(3)
    pct_min = col1.number_input("漲幅最小值 (%)", value=float(sc.get("price_change_min", 3.0)))
    pct_max = col2.number_input("漲幅最大值 (%)", value=float(sc.get("price_change_max", 5.0)))
    vol_ratio = col3.number_input("量比門檻 (>)", value=float(sc.get("volume_ratio_min", 1.0)))

    st.subheader("換手率 & 市值")
    col1, col2 = st.columns(2)
    to_min = col1.number_input("換手率最小值 (%)", value=float(sc.get("turnover_rate_min", 5.0)))
    to_max = col2.number_input("換手率最大值 (%)", value=float(sc.get("turnover_rate_max", 10.0)))
    col1, col2 = st.columns(2)
    cap_min = col1.number_input("市值最小值 (億)", value=float(sc.get("market_cap_min_100m", 200)))
    cap_max = col2.number_input("市值最大值 (億)", value=float(sc.get("market_cap_max_100m", 1000)))

    st.subheader("近期漲停 & VWAP 分析")
    col1, col2 = st.columns(2)
    lu_days = col1.number_input("回顧天數 (漲停)", value=int(sc.get("limit_up_lookback_days", 20)), step=1)
    vwap_ratio = col2.number_input("VWAP 上方比例 (>)", value=float(sc.get("vwap_above_ratio_min", 0.70)))
    col1, col2 = st.columns(2)
    vwap_tol = col1.number_input("回踩距離容差 (%)", value=float(sc.get("vwap_dip_tolerance_pct", 0.5)))
    vwap_rec = col2.number_input("回踩回升 bar 數", value=int(sc.get("vwap_recovery_bars", 3)), step=1)

with tab2:
    st.info("收件人可填多個，用半形逗號 , 分隔。")
    st.subheader("Email 通知")
    to_email = st.text_input("收件人 Email", value=nt.get("to_email", env_data.get("EMAIL_RECIPIENT", "")))
    subject = st.text_input("信件主旨", value=nt.get("subject", "【每日股票篩選報告】"))
    send_empty = st.checkbox("無符合股票時仍發送通知", value=nt.get("send_if_empty", True))

    st.subheader("排程設定")
    run_time = st.text_input("每日執行時間 (HH:MM)", value=sh.get("run_time", "13:00"))

with tab3:
    st.info("設定存於 .env 檔（不納入版本控制）。")
    st.subheader("富邦 Neo API")
    fubon_acc = st.text_input("帳號", value=env_data.get("FUBON_ACCOUNT", ""))
    fubon_pw = st.text_input("密碼", value=env_data.get("FUBON_PASSWORD", ""), type="password")
    
    uploaded_cert = st.file_uploader("上傳憑證 (.pfx) - 將自動儲存至 ~/CAFubon", type=["pfx"])
    if uploaded_cert is not None:
        cert_dir = os.path.expanduser("~/CAFubon")
        os.makedirs(cert_dir, exist_ok=True)
        cert_path = os.path.join(cert_dir, uploaded_cert.name)
        
        file_hash = hash(uploaded_cert.getvalue())
        if st.session_state.get("last_uploaded_cert_hash") != file_hash:
            st.session_state["last_uploaded_cert_hash"] = file_hash
            
            with open(cert_path, "wb") as f:
                f.write(uploaded_cert.getbuffer())
            
            # 立即將憑證路徑儲存至 .env，避免重新整理網頁後消失
            current_env = load_env()
            current_env["FUBON_CERT_PATH"] = cert_path
            save_env(current_env)
            
            st.rerun()
            
    fubon_cert = st.text_input("憑證路徑 (.pfx)", value=env_data.get("FUBON_CERT_PATH", ""), disabled=True)
    fubon_cert_pw = st.text_input("憑證密碼 (若與登入密碼不同則填寫)", value=env_data.get("FUBON_CERT_PASSWORD", ""), type="password")

with tab4:
    st.subheader("執行控制")
    col1, col2 = st.columns(2)
    run_btn = col1.button("▶ 立即執行篩選", use_container_width=True, disabled=st.session_state.is_running)
    sched_btn = col2.button("⏰ 啟動排程 (背景執行)", use_container_width=True, disabled=st.session_state.is_running)

    # 點擊執行時自動隱藏明細，避免卡頓
    if run_btn:
        st.session_state.show_details = False
        st.session_state.is_running = True
        st.rerun()

    st.markdown("---")
    st.write("執行記錄：")
    log_area = st.empty()
    if st.session_state.run_logs:
        log_area.text_area("Logs", "\n".join(st.session_state.run_logs[-30:]), height=300, label_visibility="collapsed")

    # ── 篩選明細檢視器 ──────────────────────────────────
    st.markdown("---")
    st.subheader("篩選明細")

    detail_col1, detail_col2, detail_col3 = st.columns([1, 1, 1])
    toggle_label = "隱藏篩選明細" if st.session_state.show_details else "查看上次篩選明細"
    if detail_col1.button(toggle_label, use_container_width=True, disabled=st.session_state.is_running):
        st.session_state.show_details = not st.session_state.show_details
        st.rerun()

    def reset_page():
        st.session_state.page = 0

    detail_filter = detail_col2.selectbox(
        "顯示範圍",
        ["全部", "通過", "未通過"],
        label_visibility="collapsed",
        on_change=reset_page,
    )

    if st.session_state.show_details:
        if not os.path.exists(RESULTS_FILE):
            st.warning("尚無篩選記錄，請先執行篩選")
        else:
            with open(RESULTS_FILE, encoding="utf-8") as f:
                results = json.load(f)

            stocks = results.get("stocks", [])
            run_ts = results.get("run_time", "")
            total = results.get("total_evaluated", 0)
            passed = results.get("passed", 0)

            st.info(
                f"篩選時間：{run_ts}　"
                f"評估：{total} 檔　"
                f"通過：{passed} 檔　"
                f"未通過：{total - passed} 檔"
            )

            if detail_filter == "通過":
                stocks = [s for s in stocks if s["pass_all"]]
            elif detail_filter == "未通過":
                stocks = [s for s in stocks if not s["pass_all"]]

            if not stocks:
                st.info("此條件下無資料")
            else:
                import math
                PAGE_SIZE = 50
                total_pages = max(1, math.ceil(len(stocks) / PAGE_SIZE))
                
                # 防呆：如果分頁超出範圍
                if st.session_state.page >= total_pages:
                    st.session_state.page = total_pages - 1
                if st.session_state.page < 0:
                    st.session_state.page = 0
                
                # 分頁控制 UI
                pg_col1, pg_col2, pg_col3 = st.columns([1, 2, 1])
                if pg_col1.button("◀ 上一頁", disabled=st.session_state.page == 0, use_container_width=True):
                    st.session_state.page -= 1
                    st.rerun()
                
                pg_col2.markdown(f"<div style='text-align: center; padding-top: 5px; color: #555;'>第 <b>{st.session_state.page + 1}</b> / {total_pages} 頁 (共 {len(stocks)} 筆)</div>", unsafe_allow_html=True)
                
                if pg_col3.button("下一頁 ▶", disabled=st.session_state.page >= total_pages - 1, use_container_width=True):
                    st.session_state.page += 1
                    st.rerun()
                
                start_idx = st.session_state.page * PAGE_SIZE
                end_idx = start_idx + PAGE_SIZE
                page_stocks = stocks[start_idx:end_idx]

                with st.container(height=500):
                    for s in page_stocks:
                        status = "✅ 通過" if s["pass_all"] else "❌ 未通過"
                        label = f"{s['symbol']} {s['name']}　{status}　{s['price_change_pct']:+.2f}%"
                        with st.expander(label, expanded=s["pass_all"]):
                            c1, c2, c3 = st.columns(3)
                            c1.metric("股價", f"{s['price']:.2f}")
                            c1.metric("漲幅", f"{s['price_change_pct']:+.2f}%")
                            c2.metric("量比", f"{s['volume_ratio']:.2f}x")
                            c2.metric("換手率", f"{s['turnover_rate_pct']:.2f}%")
                            c3.metric("市值", f"{s['market_cap_100m']:.0f}億")
                            c3.metric("VWAP上方", f"{s['vwap_above_ratio']:.0%}")

                            if s["pass_all"]:
                                st.success("所有條件均通過")
                            else:
                                st.error("未通過原因：")
                                for reason in s["fail_reasons"]:
                                    st.write(f"• {reason}")


def save_all():
    cfg = {
        "screening": {
            "price_change_min": pct_min,
            "price_change_max": pct_max,
            "volume_ratio_min": vol_ratio,
            "turnover_rate_min": to_min,
            "turnover_rate_max": to_max,
            "market_cap_min_100m": cap_min,
            "market_cap_max_100m": cap_max,
            "limit_up_lookback_days": lu_days,
            "vwap_above_ratio_min": vwap_ratio,
            "vwap_dip_tolerance_pct": vwap_tol,
            "vwap_recovery_bars": vwap_rec,
        },
        "notification": {
            "to_email": to_email,
            "subject": subject,
            "send_if_empty": send_empty,
        },
        "schedule": {
            "run_time": run_time,
            "timezone": "Asia/Taipei",
        },
    }
    save_config(cfg)

    env = env_data.copy()
    env.update({
        "EMAIL_RECIPIENT": to_email,
        "SMTP_HOST": "smtp.gmail.com",
        "SMTP_PORT": "587",
        "FUBON_ACCOUNT": fubon_acc,
        "FUBON_PASSWORD": fubon_pw,
        "FUBON_CERT_PATH": fubon_cert,
        "FUBON_CERT_PASSWORD": fubon_cert_pw,
    })
    save_env(env)


st.markdown("---")
if st.button("💾 儲存所有設定", type="primary", use_container_width=True):
    save_all()
    st.success("設定已儲存！")

if st.session_state.is_running:
    save_all()
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    process = subprocess.Popen(
        [sys.executable, "-u", "main.py", "--run-now"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    st.session_state.run_logs = ["啟動立即篩選..."]
    log_area.text_area("Logs", "\n".join(st.session_state.run_logs[-30:]), height=300, label_visibility="collapsed")

    for line in process.stdout:
        st.session_state.run_logs.append(line.rstrip())
        log_area.text_area("Logs", "\n".join(st.session_state.run_logs[-30:]), height=300, label_visibility="collapsed")

    process.wait()
    st.session_state.run_logs.append("篩選完成")
    st.session_state.is_running = False
    st.rerun()

if sched_btn:
    save_all()
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    def run_scheduler():
        subprocess.Popen(
            [sys.executable, "-u", "main.py", "--schedule"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
    threading.Thread(target=run_scheduler, daemon=True).start()
    st.success(f"⏰ 已在背景啟動排程 — 每日 {run_time} 自動執行。")
