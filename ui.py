"""
網頁版參數設定 UI (Streamlit)

使用 Streamlit 提供視覺化介面讓使用者調整篩選參數與通知設定。
執行方式：streamlit run ui.py
"""

import os
import subprocess
import sys
import threading
import yaml
import streamlit as st

CONFIG_FILE = "config.yaml"
ENV_FILE = ".env"

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

st.set_page_config(page_title="股票自動篩選系統 — 參數設定", layout="centered", page_icon="📈")
st.title("📈 股票自動篩選系統 — 參數設定")

config_data = load_config()
env_data = load_env()

sc = config_data.get("screening", {})
nt = config_data.get("notification", {})
sh = config_data.get("schedule", {})

tab1, tab2, tab3, tab4 = st.tabs(["📊 篩選條件", "✉️ 通知設定", "🔑 API 設定", "▶️ 執行 / 狀態"])

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
    fubon_cert = st.text_input("憑證路徑 (.pfx)", value=env_data.get("FUBON_CERT_PATH", ""))

    st.subheader("Gmail 發信設定")
    email_sender = st.text_input("寄件人 Gmail", value=env_data.get("EMAIL_SENDER", ""))
    email_pw = st.text_input("應用程式密碼", value=env_data.get("EMAIL_APP_PASSWORD", ""), type="password")

with tab4:
    st.subheader("執行控制")
    col1, col2 = st.columns(2)
    run_btn = col1.button("▶ 立即執行篩選", use_container_width=True)
    sched_btn = col2.button("⏰ 啟動排程 (背景執行)", use_container_width=True)

    st.markdown("---")
    st.write("執行記錄：")
    log_area = st.empty()

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

    env = {
        "EMAIL_SENDER": email_sender,
        "EMAIL_APP_PASSWORD": email_pw,
        "EMAIL_RECIPIENT": to_email,
        "SMTP_HOST": "smtp.gmail.com",
        "SMTP_PORT": "587",
        "FUBON_ACCOUNT": fubon_acc,
        "FUBON_PASSWORD": fubon_pw,
        "FUBON_CERT_PATH": fubon_cert,
    }
    save_env(env)

st.markdown("---")
if st.button("💾 儲存所有設定", type="primary", use_container_width=True):
    save_all()
    st.success("設定已儲存！")

if run_btn:
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
        env=env
    )
    logs = ["▶ 啟動立即篩選..."]
    log_area.text_area("Logs", "\n".join(logs), height=300, label_visibility="collapsed")
    
    for line in process.stdout:
        logs.append(line.rstrip())
        log_area.text_area("Logs", "\n".join(logs), height=300, label_visibility="collapsed")
        
    process.wait()
    logs.append("✅ 篩選完成")
    log_area.text_area("Logs", "\n".join(logs), height=300, label_visibility="collapsed")

if sched_btn:
    save_all()
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    
    def run_scheduler():
        subprocess.Popen(
            [sys.executable, "-u", "main.py", "--schedule"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env
        )
    threading.Thread(target=run_scheduler, daemon=True).start()
    st.success(f"⏰ 已在背景啟動排程 — 每日 {run_time} 自動執行。")
    st.info("💡 提示：在 Linux 主機上，更推薦使用 `tmux` 或 `systemd` 讓程式常駐於背景，可避免 Web UI 關閉時排程中斷。")
