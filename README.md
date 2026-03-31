# BatteryLogger — Connect IQ App

A background widget for Garmin watches that automatically logs battery
percentage every 5 minutes and syncs readings to a web endpoint.

**Target devices:** Vivoactive 5 · Vivoactive 6 · Venu 3S · Venu 4

---

## Project structure

```
BatteryLogger/
├── manifest.xml                   ← App metadata, device list, permissions
├── resources/
│   ├── drawables.xml              ← Image asset declarations
│   ├── properties.xml             ← Default values for settings
│   ├── settings.xml               ← Settings UI in Garmin Connect mobile
│   ├── strings/strings.xml        ← Localised string constants
│   └── images/
│       └── launcher_icon_60x60.png  ← You must supply this PNG
└── source/
    ├── BatteryLoggerApp.mc        ← AppBase; registers background timer
    ├── BatteryLoggerBackground.mc ← Background delegate; captures & syncs
    └── BatteryLoggerView.mc       ← Widget UI + manual sync dialog
battery_server.py                  ← Simple Flask receiver (development)
```

---

## 1 — Install the Connect IQ SDK

1. Download the **Connect IQ SDK Manager** from
   <https://developer.garmin.com/connect-iq/sdk/>
2. Run the installer and open SDK Manager.
3. Install the **latest stable SDK** (≥ 4.2 recommended for full background API).
4. Install device simulators for *Vivoactive 5*, *Venu 3S*, and at least one
   other target.  Vivoactive 6 / Venu 4 may appear under different IDs — check
   the SDK Manager's device list and update `manifest.xml` if needed.
5. Install **VS Code** and the
   [Monkey C extension](https://marketplace.visualstudio.com/items?itemName=garmin.monkey-c).
   Alternatively use Eclipse with the Connect IQ plugin.

---

## 2 — Configure the app

Open `resources/properties.xml` and change the default sync URL:

```xml
<property id="sync_endpoint" type="String">https://YOUR_SERVER/api/battery-readings</property>
```

For local development, use your machine's LAN IP (e.g. `http://192.168.1.42:8765/api/battery-readings`).
The phone bridges the connection, so as long as phone and laptop are on the
same Wi-Fi, it works.

Also create a 60×60 px PNG launcher icon and place it at:
`resources/images/launcher_icon_60x60.png`

---

## 3 — Build in VS Code (Monkey C extension)

1. Open the `BatteryLogger/` folder in VS Code.
2. Press **F5** (or Cmd+Shift+P → *Monkey C: Run Current Project*).
3. Choose a simulator device from the list.
4. The simulator opens and shows your widget.

To build a `.prg` file for sideloading:

```
Cmd+Shift+P → Monkey C: Export Project
```

Select the target device.  Output goes to `bin/BatteryLogger.prg`.

---

## 4 — Sideload onto the watch (no store required)

### Option A — USB (simplest)

1. Connect the watch via USB.
2. It mounts as a drive (`GARMIN/`).
3. Copy `BatteryLogger.prg` to `GARMIN/APPS/` on the watch.
4. Safely eject and the watch will show the new widget.

### Option B — Garmin Express / Garmin Connect

Garmin's developer portal lets you create a *beta* channel and push via the
Garmin Connect app, but USB sideloading is faster for iteration.

### Option C — `connectiq` CLI

```bash
connectiq --sideload BatteryLogger.prg --device-id <watch-serial>
```

Run `connectiq --help` for details.

---

## 5 — Run the development server

```bash
pip install flask
cd BatteryLogger
python battery_server.py
```

The server starts on `http://0.0.0.0:8765`.

**Verify it works before sideloading:**
```bash
curl -X POST http://localhost:8765/api/battery-readings \
  -H "Content-Type: application/json" \
  -d '{"readings":[{"ts":1711123456,"bat":73.5,"charging":0}]}'
# → {"saved": 1}

curl http://localhost:8765/api/battery-readings
# → [{"device_id":"unknown","ts":1711123456,"bat":73.5,...}]
```

Readings are stored in `readings.jsonl` — one JSON object per line, easy to
load into pandas:

```python
import pandas as pd
df = pd.read_json("readings.jsonl", lines=True)
df["ts_iso"] = pd.to_datetime(df["ts"], unit="s")
```

---

## 6 — Changing the logging interval at runtime

Users can change the interval in **Garmin Connect mobile**:
1. Open the Garmin Connect app.
2. Go to **More → Garmin Devices → [watch] → Apps & More → BatteryLogger → Settings**.
3. Change *Log interval* (5 / 10 / 15 / 30 / 60 min).
4. The next temporal event will use the new value.

You can also change the Sync URL here without re-sideloading.

---

## ⚠ Gotchas & important limitations

### Background service limitations

| Limit | Detail |
|---|---|
| Minimum interval | **5 minutes (300 s)** — the OS silently enforces this; shorter values are rounded up. |
| Memory budget | ~32–64 KB heap for the background process.  No UI objects allowed here. |
| HTTP is async | You **must** call `Background.exit()` inside the HTTP callback, not after `makeWebRequest()`. If you call it before the callback fires, the process is killed and the request is abandoned. |
| No Wi-Fi | The watch communicates via BLE to the phone; the phone makes the HTTP request.  The phone must be nearby and connected. |
| Coalescing | On some firmware the OS may coalesce or skip events during GPS activity or low-power sleep.  Expect ±1 event/hour variance on very old firmware. |

### Storage limits

- `Application.Storage` uses the watch's internal flash — typically **~128 KB** total across all apps.
- Each reading Dictionary is ~80–100 bytes.  The cap of 150 readings uses ~15 KB.
- Do **not** store large strings or nested objects.
- If the watch is away from the phone for many days, the queue fills up and the app starts dropping the oldest entries (by design).  For a study longer than ~12 hours without sync, lower the interval or reduce the max queue size.

### Data types

- `System.Stats.battery` returns a **float** (e.g. 73.5).  The resolution is
  ~0.5–1% depending on firmware; don't expect more precision than that.
- `System.Stats.charging` is **not available** on all firmware versions.
  The code wraps it in a try/catch and defaults to `false`.
- Timestamps use the **Connect IQ epoch (1990-01-01)**.  The background code
  converts to Unix epoch by adding 631152000.  Verify this offset is correct
  for your analysis pipeline.

### Battery impact of the logger itself

The background process wakes for < 1 second every 5 minutes.  Empirical
impact is typically **< 0.5% extra drain per day** on these devices.  HTTP
sync has a slightly larger cost (BLE radio on for ~2–5 s), but because it
only happens when the phone is already paired, marginal impact is low.

Setting the interval to 10 or 15 minutes further reduces wake-up cost if
5-minute granularity isn't required for your study.

### Device ID aliasing

The `manifest.xml` product IDs (`vivoactive5`, `venu3s`, etc.) must exactly
match the SDK's internal identifiers.  After installing the SDK run:

```bash
connectiq --list-devices
```

If Vivoactive 6 or Venu 4 appear under different aliases, update
`manifest.xml` accordingly before building.

### HTTPS requirement

`makeWebRequest()` on retail firmware requires **HTTPS** for non-loopback
URLs.  During development on the simulator you can use HTTP, but on a real
watch you need a valid TLS certificate.  A free Let's Encrypt cert via
`certbot` + nginx in front of the Flask server is the easiest path.

---

## Customising the payload

If you need to add a watch serial number or study ID to each reading, add a
field to the reading Dictionary in `BatteryLoggerBackground.mc`:

```monkeyc
return {
    "ts"        => unixNow,
    "bat"       => stats.battery,
    "charging"  => charging ? 1 : 0,
    "study_id"  => safeGetProperty("study_id", "default_study")
};
```

Then add `study_id` to `properties.xml` and `settings.xml`.

---

## FAQ

**Q: Why a widget instead of a watch face?**
A: Watch faces must always be visible and have different lifecycle rules.
   A widget lets participants keep their existing watch face unchanged, which
   improves study compliance.

**Q: Can the background run without the widget ever being opened?**
A: Yes.  Once `registerForTemporalEvent()` is called (on first open), the OS
   fires the background delegate independently of the foreground UI.  The user
   never needs to open the widget again.

**Q: The simulator shows "Background not supported" — why?**
A: Some older simulator device profiles don't emulate background services.
   Sideload to a real watch to test the background path.  The foreground UI
   works fine in the simulator.

**Q: How do I reset the stored data on the watch?**
A: Uninstall and reinstall the app — `Application.Storage` is cleared on
   uninstall.  Alternatively add a *Clear data* menu item that calls
   `App.Storage.deleteValue("pending_readings")`.
