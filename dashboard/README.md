# DRFX Trading Dashboard v2.0

Multi-account MetaTrader 5 trading dashboard with real-time WebSocket updates,
equity curves, forex heatmap, economic calendar, and TradingView integration.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)
![MT5](https://img.shields.io/badge/MetaTrader5-API-orange)

---

## Features

| Feature                   | Description                                                  |
|---------------------------|--------------------------------------------------------------|
| Portfolio Overview Cards  | Total balance, equity, floating P/L, today/weekly/monthly    |
| Real-time Equity Curve    | Chart.js line chart with equity, balance, and floating lines |
| Accounts Table            | All MT5 accounts with sortable columns                       |
| TradingView Widget        | Live chart for XAUUSD, EURUSD, GBPUSD, BTCUSD               |
| Economic Calendar         | Upcoming high-impact news events with forecasts              |
| Market Overview           | Live prices for major instruments                            |
| Forex Heatmap             | 8×8 currency strength matrix + strength bars                 |
| WebSocket Updates         | Real-time data every 5 seconds                               |
| Demo Mode                 | Fully functional demo when MT5 terminal is unavailable       |

---

## Project Structure

```
trading-dashboard/
├── backend/
│   ├── main.py              # FastAPI server + WebSocket + REST
│   ├── mt5_service.py        # MT5 multi-account service layer
│   └── analytics.py          # Heatmap, news, portfolio stats
├── frontend/
│   ├── index.html            # Dashboard layout
│   ├── dashboard.js          # State management + WS controller
│   ├── charts.js             # Chart.js + heatmap + TV widget
│   └── styles.css            # Dark terminal theme
├── .env                      # Configuration (accounts, API keys)
├── requirements.txt          # Python dependencies
└── README.md                 # This file
```

---

## Installation Guide

### Step 1: Install Python (3.10 or newer)

**Windows:**
1. Download Python from https://www.python.org/downloads/
2. Run the installer. **Check "Add Python to PATH"** during installation.
3. Verify: open Command Prompt and type:
   ```
   python --version
   ```

**macOS:**
```bash
brew install python@3.12
```

**Linux:**
```bash
sudo apt update && sudo apt install python3.12 python3.12-venv python3-pip
```

---

### Step 2: Install MetaTrader 5 Terminal

> **Note:** MT5 is Windows-only. On Mac/Linux, the dashboard runs in Demo Mode
> with simulated data (fully functional UI).

1. Download MT5 from your broker or https://www.metatrader5.com/
2. Install and log in to at least one trading account.
3. Keep the terminal **running** while the dashboard is active.
4. In MT5: **Tools → Options → Expert Advisors** → enable "Allow DLL imports"
   and "Allow WebRequest".

---

### Step 3: Clone / Download the Project

```bash
# If using git:
git clone <your-repo-url>
cd trading-dashboard

# Or just download and extract the zip
```

---

### Step 4: Create Virtual Environment & Install Dependencies

```bash
# Create virtual environment
python -m venv venv

# Activate it
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

> **Note:** The `MetaTrader5` package only works on Windows.
> On Mac/Linux, the dashboard will automatically start in Demo Mode.

---

### Step 5: Configure Your Accounts

Edit the `.env` file in the project root:

```env
# Add your MT5 accounts as a JSON array
MT5_ACCOUNTS=[
  {
    "login": 12345678,
    "password": "your_mt5_password",
    "server": "YourBroker-Live",
    "label": "DRFX Live"
  },
  {
    "login": 87654321,
    "password": "another_password",
    "server": "AnotherBroker-Demo",
    "label": "DRFX Prop"
  }
]

# Server settings
HOST=0.0.0.0
PORT=8000
WS_UPDATE_INTERVAL=5

# Optional: Financial Modeling Prep API key for live economic news
# Get a free key at https://financialmodelingprep.com/developer/docs/
FMP_API_KEY=your_api_key_here
```

**Finding your MT5 credentials:**
- **Login**: The account number shown in MT5 Navigator panel
- **Password**: Your investor or trading password
- **Server**: Shown in MT5 → File → Login → Server field

---

### Step 6: Run the Server

```bash
cd backend
python main.py
```

You should see output like:
```
INFO:     Started server process
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Loaded 2 MT5 accounts
```

If MT5 is not available:
```
WARNING:  MT5 terminal not available — running in DEMO MODE
INFO:     Uvicorn running on http://0.0.0.0:8000
```

---

### Step 7: Open the Dashboard

Open your browser and navigate to:

```
http://localhost:8000
```

The dashboard will:
1. Connect via WebSocket for real-time updates every 5 seconds.
2. Display all configured MT5 account data.
3. Show live market prices, forex heatmap, and economic calendar.

---

## API Endpoints

| Method | Path                | Description                          |
|--------|---------------------|--------------------------------------|
| GET    | `/`                 | Serve the dashboard HTML             |
| GET    | `/api/snapshot`     | Full data snapshot (all panels)      |
| GET    | `/api/portfolio`    | Portfolio summary only               |
| GET    | `/api/market`       | Market prices for major instruments  |
| GET    | `/api/heatmap`      | Currency strength + heatmap matrix   |
| GET    | `/api/news`         | Economic calendar events             |
| GET    | `/api/equity/{id}`  | Equity curve for a specific account  |
| WS     | `/ws`               | WebSocket real-time feed             |

---

## Customisation

### Add more symbols to Market Overview

In `mt5_service.py`, modify the default symbols list in `get_market_overview()`:
```python
symbols = ["EURUSD", "GBPUSD", "USDJPY", "BTCUSD", "XAUUSD", "USTEC", "US30"]
```

### Change update interval

In `.env`:
```env
WS_UPDATE_INTERVAL=3    # seconds between WebSocket updates
```

### Add more TradingView chart options

In `index.html`, add buttons to the chart panel:
```html
<button onclick="changeChartSymbol('NASDAQ:AAPL')">AAPL</button>
```

---

## Troubleshooting

| Issue                        | Solution                                                          |
|------------------------------|-------------------------------------------------------------------|
| MT5 connection fails         | Ensure MT5 terminal is running and logged in                      |
| `ModuleNotFoundError: mt5`   | Install: `pip install MetaTrader5` (Windows only)                 |
| Port already in use          | Change `PORT` in `.env` or kill the process on port 8000          |
| WebSocket disconnects        | Dashboard auto-reconnects with exponential backoff                |
| Blank heatmap                | Check that forex pairs exist on your broker (symbol names vary)   |
| No news data                 | Add an FMP API key in `.env` or use mock data (default)           |

---

## Tech Stack

- **Backend**: Python 3.10+ · FastAPI · MetaTrader5 API · Pandas · WebSocket
- **Frontend**: HTML5 · JavaScript · Chart.js · TradingView Widget · Custom CSS
- **Data**: Real-time MT5 terminal · FinancialModelingPrep API (optional)

---

## License

Internal use — DRFX BOT BUILDERS
