# BatteryLogger — Project Guide

A plain-English explanation of what this project is, how it works, and how to develop and deploy it.

---

## What does this app do?

BatteryLogger is a small app that runs on a Garmin smartwatch. Every 5 minutes (configurable), it quietly wakes up in the background, records the current battery percentage, and stores it on the watch. When the watch has a phone nearby, it sends those readings over the internet to a server on your computer, where they get saved to a file you can analyse.

The goal is to collect long-term battery drain data from real watch usage — useful for research studies, testing firmware changes, or just understanding battery life patterns.

---

## The two main systems

### 1. The Garmin watch app (Monkey C)

Garmin watches run apps written in a language called **Monkey C**. It looks similar to Java or Swift but is designed for tiny devices with very limited memory (typically less than 1 MB for your whole app).

The platform is called **Connect IQ**, and Garmin provides an SDK (Software Development Kit) — a set of tools that let you write, build, and test apps. The SDK version used here is **9.1.0** (released March 2026).

The watch app has three parts:

**BatteryLoggerApp** (`BatteryLoggerApp.mc`)
The entry point. When the widget opens, this runs `onStart()`, which tells the watch to wake the background process every N seconds. Think of it as the "manager" that sets the schedule.

**BatteryLoggerBackground** (`BatteryLoggerBackground.mc`)
This is the "worker" that runs silently even when the watch screen is off. Every time the interval fires, it:
1. Reads the current battery level
2. Saves it to a queue on the watch
3. Tries to POST the queue to your server via HTTP
4. If the POST succeeds, clears the queue

**BatteryLoggerView** (`BatteryLoggerView.mc`)
The visual screen the user sees when they open the widget. Shows current battery %, how many readings are waiting to sync, and when the last sync happened. Also has a manual "Sync now" button.

### 2. The Python server (`battery_server.py`)

A small web server that runs on your Mac (or any computer). It listens for incoming data from the watch and saves readings to a file called `readings.jsonl`. Each line in that file is one batch of readings in JSON format — easy to load into Python/pandas or R for analysis.

---

## How data flows

```
Watch (background, every 5 min)
  → captures battery %
  → saves to on-watch queue
  → if phone nearby: HTTP POST → your Mac's server
  → server saves to readings.jsonl
```

The watch never connects directly to the internet. It sends data to the **Garmin Connect** app on the paired iPhone, which then forwards the HTTP request over Wi-Fi or cellular to your server. This is called the **BLE (Bluetooth Low Energy) bridge**.

---

## Project file structure

```
BatteryLogger/
├── source/
│   ├── BatteryLoggerApp.mc         — app entry point, registers background timer
│   ├── BatteryLoggerBackground.mc  — background worker: capture + sync
│   └── BatteryLoggerView.mc        — watch screen UI + manual sync button
├── resources/
│   ├── drawables.xml               — registers the launcher icon
│   ├── images/
│   │   └── launcher_icon_56x56.png — app icon (currently a white placeholder)
│   ├── properties.xml              — default settings (interval, server URL)
│   ├── settings.xml                — settings UI shown in Garmin Connect app
│   └── strings/
│       └── strings.xml             — app name string
├── manifest.xml                    — app metadata: supported devices, permissions
├── monkey.jungle                   — build config: where to find source + resources
├── battery_server.py               — Python/Flask server that receives readings
├── .vscode/
│   └── settings.json               — VS Code: path to developer key + jungle file
├── developer_key.der               — your private signing key (never share/commit)
├── developer_key.pem               — your private signing key (never share/commit)
└── .gitignore                      — excludes keys, build output, venv
```

---

## Key concepts explained

### Background processes
Garmin watches conserve battery by only running apps when needed. A "background process" is a tiny slice of code the watch runs on a schedule — in our case every 5 minutes. It has strict limits: it must finish quickly, can only use a small amount of memory, and cannot draw on screen. That's why there are two separate classes: the background worker handles data collection, and the view handles display.

### The queue / offline storage
The watch stores readings locally (in `Application.Storage`) in case it can't reach the server right away — no phone nearby, no internet, etc. Up to 150 readings can queue up (~12.5 hours at 5-min intervals) before old ones are dropped. Every sync attempt sends the whole queue at once and clears it on success.

### Time and timestamps
Garmin's internal clock counts seconds since **January 1, 1990**. The rest of the world uses **Unix time**, which counts seconds since **January 1, 1970**. To convert, we add `631152000` (the number of seconds between those two dates). This is why you'll see `+ 631152000` in the code.

### Properties vs Storage
- **Properties** (`Application.Properties`) — settings the user can change in the Garmin Connect app on their phone. Things like the sync URL or the logging interval. Set once, rarely changed.
- **Storage** (`Application.Storage`) — on-watch persistent data the app writes itself. The reading queue lives here. Survives app restarts and watch reboots.

### Annotations: `(:background)` and `(:typecheck(...))`
Monkey C uses annotations (the things starting with `:`in brackets) to give the compiler extra instructions:
- `(:background)` — marks code that runs in the background process. The compiler checks that background code doesn't use APIs unavailable in that context (e.g. you can't draw on screen from the background).
- `(:typecheck(disableBackgroundCheck))` — tells the compiler "I know this is view code, don't apply background restrictions to it."

### The developer key
Before the Garmin toolchain will build your app, it requires you to sign it with a private key. This is just a security measure. The key was generated with `openssl` and lives in `developer_key.der`. Keep it private — anyone with this key could sign apps as you. It is excluded from git via `.gitignore`.

---

## Development setup

### What you need
| Tool | Purpose |
|---|---|
| Garmin Connect IQ SDK 9.1.0 | Compiler, simulator, device definitions |
| VS Code + Monkey C extension | Editor, build tasks, debugger |
| Java (Temurin 21) | The compiler runs on Java |
| Python 3 + Flask | The receiving server |

### Install dependencies
```bash
# Install Java (if not already done)
brew install --cask temurin

# Set up Python server
cd /path/to/BatteryLogger
python3 -m venv .venv
source .venv/bin/activate
pip install flask
```

### Build the app
In VS Code: `Cmd+Shift+P` → **Monkey C: Build Current Project** → pick a device.

This produces a `.prg` file (the compiled watch app) in the `bin/` folder.

### Run in the simulator
Press **F5** in VS Code (or use the Run & Debug panel). The Connect IQ simulator launches and loads the app. Note: the background process does not fire automatically in the simulator — use **Simulation → Background Events** to trigger it manually.

### Start the server
```bash
source .venv/bin/activate
python battery_server.py
```
The server runs at `http://0.0.0.0:8765`. Check it's working:
```bash
curl http://localhost:8765/api/status
# → {"status": "ok", "readings_stored": 0}
```

---

## Deploying to a real watch

### Sideloading (developer testing)
1. Build with **Monkey C: Build for Device** → pick your specific watch model
2. Connect the watch via USB — it mounts as a drive in Finder
3. Copy `BatteryLogger.prg` to `GARMIN/APPS/` on the watch
4. Eject safely and disconnect

The widget appears in the watch's widget glance loop (swipe up/down from the watch face).

### Changing the server URL
The sync URL is set in `resources/properties.xml` as the default. Users (or you) can also change it without reinstalling — open **Garmin Connect** app on the phone → **More** → **Connect IQ Apps** → **Battery Logger** → **Settings** → **Sync URL**.

For a real study, the server needs a public URL (not `localhost`). Options:
- A cheap VPS with a domain name and HTTPS certificate
- A cloud function (AWS Lambda, Fly.io, Render, etc.)
- **ngrok** for short-term testing: `ngrok http 8765` gives you a temporary public URL

### Phone and watch on the same network (development)
When testing with a real watch, the phone (not the watch) makes the HTTP request. The phone and your Mac must be on the same Wi-Fi network, and your Mac's LAN IP (e.g. `172.20.10.3`) must be used as the server address, not `localhost`.

---

## Reading the data

Readings are saved to `readings.jsonl`. Each line looks like:
```json
{"device_id": "unknown", "ts": 1711123456, "bat": 73.5, "charging": 0, "received_at": 1711123460, "ts_iso": "2024-03-22T18:04:16+00:00"}
```

Load in Python:
```python
import pandas as pd
df = pd.read_json("readings.jsonl", lines=True)
df["ts_iso"] = pd.to_datetime(df["ts_iso"])
df.plot(x="ts_iso", y="bat")
```

---

## Things to know / current limitations

| Issue | Notes |
|---|---|
| Simulator HTTP | The simulator can't POST to `localhost` — it routes through Garmin's servers. Test HTTP sync on a real watch or use ngrok. |
| Background not in simulator | `Simulation → Background Events` triggers it manually. The real 5-min timer only works on the watch. |
| Timestamps in simulator | The simulator returns a nonsense CIQ epoch value for `Time.now()`. Timestamps will look wrong in the simulator but are correct on a real watch. |
| Icon is a placeholder | `resources/images/launcher_icon_56x56.png` is a blank white square. Replace it with a real icon before sharing. |
| HTTP only | The server uses plain HTTP. For a real study with participant data, use HTTPS. You'll need to update `properties.xml` with an `https://` URL. |
| `vivoactive6` in manifest | Listed as a target device but may not be in all SDK versions. If it causes build errors, remove it from `manifest.xml`. |

---

## Useful links

- Garmin Connect IQ API reference: https://developer.garmin.com/connect-iq/api-docs/
- Background processes guide: https://developer.garmin.com/connect-iq/core-topics/background-processes/
- SDK samples (on your machine): `~/Library/Application Support/Garmin/ConnectIQ/Sdks/connectiq-sdk-mac-9.1.0-.../samples/`
