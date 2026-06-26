# Google Cloud (GCP) 永久免費主機部署指南

本指南將教您如何將這個專案部署到 Google Cloud Platform (GCP) 的 **e2-micro 永久免費機器** 上，並透過 Streamlit 啟動網頁版的參數設定 UI。

---

## 步驟一：申請 GCP 免費主機 (VM)

1. 前往 [Google Cloud Console](https://console.cloud.google.com/) 並註冊/登入您的 Google 帳號。如果您是新用戶，還會有 300 美金的試用額度。
2. 進入「**Compute Engine**」 > 「**VM 執行個體**」，點擊「**建立執行個體**」。
3. **重要：請務必選擇以下免費方案的規格**：
   * **區域 (Region)**：只能選 `us-west1` (奧勒岡)、`us-central1` (愛荷華) 或 `us-east1` (南卡羅來納) 其中之一。
   * **機器設定**：選擇 `e2-micro`。
   * **開機磁碟**：請選擇 Debian (例如 Debian 12 Bookworm)，磁碟大小可設為標準永久磁碟 (Standard Persistent Disk) 30 GB 以下 (都在免費額度內)。
4. **防火牆**：勾選「允許 HTTP 流量」與「允許 HTTPS 流量」。
5. 點擊「**建立**」。

---

## 步驟二：開啟防火牆 Port (用於 Streamlit Web UI)

Streamlit 預設使用 `8501` Port，我們需要將這個 Port 打開。
1. 在 GCP 後台左側選單進入「**VPC 網路**」 > 「**防火牆**」。
2. 點擊「**建立防火牆規則**」。
3. 名稱填寫 `allow-streamlit`。
4. 目標填寫 `網路中的所有執行個體`。
5. 來源 IPv4 範圍填寫 `0.0.0.0/0`。
6. 通訊協定和通訊埠：勾選「指定的通訊協定和通訊埠」，選 `TCP`，並填入 `8501`。
7. 點擊「**建立**」。

---

## 步驟三：連線到主機並設定環境

回到「**VM 執行個體**」頁面，點擊您剛建好的機器右側的「**SSH**」按鈕，會彈出一個終端機視窗。

依序在終端機輸入以下指令：

```bash
# 1. 更新系統包並安裝 Python 及 pip
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv git tmux -y

# 2. 將專案程式碼上傳到主機
# 您可以透過 Git clone 您的程式碼，或是使用 SSH 視窗右上角的「上傳檔案」功能將整個資料夾傳上去。
# 假設您的程式碼放在 ~/stock_notification 資料夾內：
cd ~/stock_notification

# 3. 建立虛擬環境並啟動
python3 -m venv venv
source venv/bin/activate

# 4. 安裝套件
pip install -r requirements.txt

# 5. 放好您的憑證檔案
# 記得把富邦的 .pfx 憑證檔案上傳到專案目錄中。
```

---

## 步驟四：啟動 Web UI 參數設定頁面

為了讓 Web UI 能夠持續在背景執行，我們可以使用 `tmux` 工具。

```bash
# 1. 建立一個名為 ui 的 tmux session
tmux new -s ui

# 2. 啟動 Streamlit 網頁伺服器
streamlit run ui.py

# 3. 離開 tmux 視窗但讓它繼續在背景跑
# 在鍵盤上按下: Ctrl+B 然後放開，接著按 D
```

這時候您打開瀏覽器，輸入 `http://<您的主機外部IP>:8501` 就能看到剛剛改寫好的網頁版參數設定 UI 了！您可以在這個網頁上填寫 API 帳號密碼與憑證路徑等設定，並點擊儲存。

> **提示**：如果需要回到那個畫面，可以輸入 `tmux attach -t ui`。

---

## 步驟五：設定排程自動篩選 (二擇一)

### 方法 A：使用網頁 UI 中的排程 (較不推薦於正式環境)
您可以在網頁版的「執行 / 狀態」頁籤點擊「啟動排程」，它會在伺服器背景自動掛載 `main.py --schedule`。

### 方法 B：使用 Linux 內建的 crontab 排程 (推薦 👍)
如果您希望主機重開機也能自動執行，最好的方式是使用 `crontab`。

1. 在終端機輸入：
```bash
crontab -e
```
*(第一次執行可能會問你要用哪個編輯器，選 `nano` 即可)*

2. 在文件最下方加入這行（假設每天下午 13:00 執行，主機時區如果為 UTC，請自行換算時區，例如台灣時間 13:00 = UTC 05:00）：

```bash
0 5 * * * cd /home/使用者名稱/stock_notification && /home/使用者名稱/stock_notification/venv/bin/python main.py --run-now >> /home/使用者名稱/stock_notification/logs/cron.log 2>&1
```

> ⚠️ 注意：這行代表每天伺服器時間 05:00 (台灣下午 13:00) 會強制執行一次 `main.py --run-now`。
> 這樣一來您就不需要在 Web UI 點擊啟動排程了，伺服器時間到了就會自動跑！

---
🎉 **大功告成！您現在已經擁有一個 24 小時運作且免費的雲端股票通知機器人了！**
