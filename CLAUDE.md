# BatteryLogger — Garmin Connect IQ Widget

## Project Overview

A Connect IQ **widget** (`type="widget"`) for the Vivoactive 5 that logs battery percentage every 5 minutes via a background `ServiceDelegate`, queues readings in `Application.Storage`, and syncs them to a remote Flask server via HTTP POST. The server is hosted on Render at `https://batterylogger.onrender.com`.

## Tech Stack

- **Language**: Monkey C — NOT Java, NOT JavaScript. It is Garmin's proprietary language with its own type system, annotations, and runtime constraints. Do not assume Java/JS patterns apply.
- **SDK**: Garmin Connect IQ SDK 9.1.0
- **Target device**: vívoactive® 5
- **App type**: Widget (`type="widget"` in manifest.xml)
- **Server**: Python Flask on Render (`https://batterylogger.onrender.com`)
- **Build tool**: Monkey C compiler via VS Code extension or CLI (`monkeyc`)

## Project Structure

```
BatteryLogger/
├── manifest.xml                   # App type, permissions, supported devices
├── monkey.jungle                  # Build config
├── resources/
│   ├── drawables.xml
│   ├── properties.xml             # Default values for app properties
│   ├── settings.xml               # Settings UI definitions
│   └── strings/strings.xml        # Localised string constants
├── source/
│   ├── BatteryLoggerApp.mc        # AppBase — lifecycle, registers background events, handles onBackgroundData
│   ├── BatteryLoggerBackground.mc # ServiceDelegate — captures readings, syncs via HTTP POST
│   └── BatteryLoggerView.mc       # View, BehaviorDelegate, and SyncConfirmDelegate (all in one file)
└── CLAUDE.md
```

## Required Permissions (manifest.xml)

```xml
<iq:permissions>
    <iq:uses-permission id="Background"/>
    <iq:uses-permission id="Communications"/>
</iq:permissions>
```

---

## CRITICAL Monkey C / Connect IQ Platform Rules

These are hard platform constraints enforced by the Connect IQ runtime. Violating them causes crashes ("!" icon on watch) or silent failures. **Always follow these rules.**

### Background Services & Temporal Events

1. **Widgets CANNOT make HTTP requests from foreground code.** Calling `Communications.makeWebRequest()` from a View or BehaviorDelegate in a widget returns error code `-200` (BLE_CONNECTION_UNAVAILABLE) immediately. HTTP requests in widgets MUST go through a background `ServiceDelegate`.

2. **`registerForTemporalEvent()` accepts either a `Time.Moment` or a `Time.Duration`:**
   - `Duration` = recurring interval. **Minimum is 300 seconds (5 minutes).** Passing `Duration(n)` where `n < 300` throws `InvalidBackgroundTimeException` and crashes the app.
   - `Moment` = one-shot at a specific time. If the moment is in the past, the event fires immediately. For widgets, **the 5-minute restriction is cleared on app startup** when using a Moment.
   - Source: https://developer.garmin.com/connect-iq/api-docs/Toybox/Background.html

3. **Only ONE temporal event can be registered at a time.** Calling `registerForTemporalEvent()` overwrites any previously registered event. If you register a one-shot `Moment` for manual sync, it replaces the recurring `Duration`. The `onTemporalEvent()` handler must re-register the recurring `Duration` to restore the periodic schedule.

4. **`Background.exit()` MUST be called** to end every background process. If not called within ~30 seconds, the OS kills the background process and `onBackgroundData()` is never called.

5. **`Background.exit()` data size limit is ~8KB.** Exceeding it throws `ExitDataSizeLimitException`. Keep data passed back to the foreground small (status strings, not full queues).

6. **Background processes are separate from the foreground.** They cannot access View classes, WatchUi, or Graphics. The ONLY communication bridge is `Application.Storage` (read/write from both contexts) and `Background.exit()` → `AppBase.onBackgroundData()`.

### The `(:background)` Annotation

7. **Any class used in the background context MUST have the `(:background)` annotation.** This includes `AppBase` and `ServiceDelegate` subclasses. Classes without this annotation are stripped from the background build and will cause "symbol not found" crashes.

8. **`AppBase` is annotated `(:background)` and compiled into both builds.** Do NOT add references to View classes or WatchUi types as instance variables on AppBase — those classes don't exist in the background build and will crash. Use `Application.Storage` to pass results to the foreground instead.

### HTTP / Communications

9. **The watch does NOT make HTTP requests directly.** All `Communications.makeWebRequest()` calls route through BLE to the Garmin Connect Mobile app on the paired phone, which makes the actual HTTP request. The phone app must be installed, running, and the watch must be paired/connected via Bluetooth.

10. **HTTP response codes:** Positive values are standard HTTP codes (200, 404, etc.). Negative values are Garmin BLE/system errors:
    - `-2` = `BLE_ERROR` (generic BLE failure)
    - `-101` = `BLE_QUEUE_FULL` (too many pending requests; single-thread your requests)
    - `-104` = `BLE_CONNECTION_UNAVAILABLE` (no BLE connection to phone)
    - `-200` = `INVALID_HTTP_HEADER_FIELDS_IN_REQUEST` — **most commonly caused by using a raw string like `"application/json"` as a header value instead of the SDK constant `Communications.REQUEST_CONTENT_TYPE_JSON`.** Also occurs if called from widget foreground context. Confirmed by Garmin staff (jim_m_58) on forums — this error appears in the simulator too, proving it is NOT a BLE error.
    - `-300` = `NETWORK_REQUEST_TIMED_OUT`
    - `-400` = `INVALID_HTTP_BODY_IN_NETWORK_RESPONSE`
    - `-1001` = `SECURE_CONNECTION_REQUIRED` (HTTP used where HTTPS required)
    - `0` = `UNKNOWN_ERROR`

12. **Always use SDK constants for Content-Type headers, never raw strings.** Using `"application/json"` as a header value causes a -200 error. The correct form is:
    ```monkeyc
    :headers => { "Content-Type" => Communications.REQUEST_CONTENT_TYPE_JSON }
    ```
    `makeWebRequest` validates header fields strictly and rejects raw MIME type strings.

13. **Single-thread web requests.** Do not call `makeWebRequest()` again until the callback from the previous request has fired. The BLE queue is very small (as few as 1 pending request on iOS).

### Storage & Data

14. **`Application.Storage` is the shared state mechanism** between foreground and background. Use it for the reading queue, sync flags, and timestamps.

15. **`Application.Properties` is for user-configurable settings** (defined in resources.xml). Read-only from the app's perspective (users set them via Garmin Connect Mobile). Note: sideloaded apps do NOT appear in Garmin Connect settings — properties can only be changed by rebuilding with new default values in `properties.xml`.

16. **`Time.now().value()` already returns Unix epoch (seconds since Jan 1, 1970).** Do NOT add `631152000`. In SDK 9.1.0, adding that offset causes 32-bit signed integer overflow (the sum exceeds ~2.1B), producing large negative values and dates around 1910. Use `Time.now().value()` directly for Unix timestamps.

### UI & Views

17. **`WatchUi.requestUpdate()`** must be called to trigger a screen redraw. The system does not automatically redraw when data changes.

18. **Widgets have limited screen time.** The OS may exit a widget at any time. Do not rely on the widget staying in the foreground.

### Memory

19. **Background processes have very limited memory** (~28KB on most devices). Keep background code minimal. Avoid large arrays, string concatenation in loops, or importing unnecessary modules.

---

## Common Patterns for This Project

### Manual Sync (Foreground → Background)

```monkeyc
// In BehaviorDelegate or View — set a flag and register a one-shot Moment
Storage.setValue("sync_requested", true);
try {
    Background.registerForTemporalEvent(Time.now());
} catch (ex instanceof Lang.Exception) {
    // 5-minute cooldown may still be active — background will pick up flag on next cycle
}
```

### Background onTemporalEvent (handles both scheduled and manual)

```monkeyc
public function onTemporalEvent() as Void {
    // ALWAYS re-register the recurring Duration first
    Background.registerForTemporalEvent(new Time.Duration(300));

    var manualSync = Storage.getValue("sync_requested");
    Storage.setValue("sync_requested", false);

    if (manualSync instanceof Boolean && manualSync == true) {
        syncReadings();  // Manual sync — just flush the queue
    } else {
        enqueue(captureReading());  // Scheduled — log a reading then sync
        syncReadings();
    }
}
```

### Safe Temporal Event Registration

```monkeyc
var lastTime = Background.getLastTemporalEventTime();
if (lastTime != null) {
    var nextTime = lastTime.add(new Time.Duration(300));
    Background.registerForTemporalEvent(nextTime);
} else {
    Background.registerForTemporalEvent(Time.now());
}
```

### Passing Results Back to Foreground

```monkeyc
// In ServiceDelegate — exit with a small string result
Background.exit("synced");           // success
Background.exit("sync_fail:-200");   // failure with code
Background.exit("queue_empty");      // nothing to do

// In AppBase.onBackgroundData — write to Storage, trigger redraw
public function onBackgroundData(data as Application.PersistableType) as Void {
    if (data instanceof String) {
        Storage.setValue("last_sync_result", data);
    }
    WatchUi.requestUpdate();
}

// In View.onUpdate (NOT onShow) — read and clear the result.
// onBackgroundData calls WatchUi.requestUpdate() which triggers onUpdate, not onShow.
// If you only read in onShow, the status will never update while the widget is open.
var result = Storage.getValue("last_sync_result");
if (result instanceof String) {
    // display result...
    Storage.setValue("last_sync_result", null);
}
```

---

## Deployment Workflow

This project uses a **Mac (build) → MacDroid → Watch** workflow. MacDroid handles MTP transfers directly from Mac via USB, replacing the previous OneDrive → Windows workaround.

### Build outputs — two different files, don't mix them up

VS Code produces two separate `.prg` files depending on which build target you select:

| Build target | Output path | Use for |
|---|---|---|
| `vivoactive5_sim` | `bin/BatteryLogger.prg` | Simulator only |
| `vivoactive5` | `BatteryLogger.prg` (project root) | Real watch |

**Always transfer `BatteryLogger.prg` from the project root, not `bin/`.** The simulator build will not run on the real watch.

### Steps

1. Edit source on Mac in VS Code
2. `Cmd+Shift+P` → **Monkey C: Build for Device** → select **vivoactive5** (not `vivoactive5_sim`) → outputs `BatteryLogger.prg` in the project root
3. Connect watch via USB, open MacDroid, copy `BatteryLogger.prg` to `GARMIN/APPS/` on the watch
4. Eject watch — it installs automatically

**Storage persists between sideloads.** The queue and timestamps carry over. Uninstall + reinstall to clear Storage.

**The Render server URL is permanent** — `https://batterylogger.onrender.com`. No tunnel or IP changes needed. Note: Render free tier spins down after 15 minutes of inactivity; first request after that takes ~30 seconds.

### Sideloading caveat

Sideloaded apps can have less stable HTTP proxy behaviour than store-installed apps — GCM registration is different. If you see persistent BLE errors on a sideloaded build that don't reproduce in the simulator, consider publishing a beta to the Connect IQ Store and installing from there instead.

---

## Reference Documentation — ALWAYS Consult Before Writing Code

When unsure about ANY Monkey C API, fetch and read the relevant documentation page. Do NOT guess — Monkey C has many subtle constraints that differ from general-purpose languages.

### Official Garmin Documentation

- **API Reference (full)**: https://developer.garmin.com/connect-iq/api-docs/
- **Toybox.Background** (temporal events, exit, ServiceDelegate): https://developer.garmin.com/connect-iq/api-docs/Toybox/Background.html
- **Toybox.Communications** (makeWebRequest, error codes, BLE): https://developer.garmin.com/connect-iq/api-docs/Toybox/Communications.html
- **Toybox.Application** (AppBase, Storage, Properties, lifecycle): https://developer.garmin.com/connect-iq/api-docs/Toybox/Application.html
- **Toybox.Application.Storage**: https://developer.garmin.com/connect-iq/api-docs/Toybox/Application/Storage.html
- **Toybox.Application.Properties**: https://developer.garmin.com/connect-iq/api-docs/Toybox/Application/Properties.html
- **Toybox.Time** (Moment, Duration, Gregorian): https://developer.garmin.com/connect-iq/api-docs/Toybox/Time.html
- **Toybox.System** (SystemStats, ServiceDelegate, DeviceSettings): https://developer.garmin.com/connect-iq/api-docs/Toybox/System.html
- **Toybox.WatchUi** (View, BehaviorDelegate, requestUpdate): https://developer.garmin.com/connect-iq/api-docs/Toybox/WatchUi.html
- **Monkey C Language Guide**: https://developer.garmin.com/connect-iq/monkey-c/
- **Core Topics (Backgrounding, Permissions, Data)**: https://developer.garmin.com/connect-iq/core-topics/
- **Background Service FAQ**: https://developer.garmin.com/connect-iq/connect-iq-faq/how-do-i-create-a-connect-iq-background-service/
- **JSON / REST Requests Guide**: https://developer.garmin.com/connect-iq/core-topics/https/
- **App Types (widget vs app vs watchface)**: https://developer.garmin.com/connect-iq/connect-iq-basics/app-types/

### Official GitHub Repos with Working Examples

- **Garmin official samples**: https://github.com/garmin/connectiq-apps
- **Community samples**: https://github.com/douglasr/connectiq-samples
- **Community projects**: https://github.com/topics/connect-iq

### Garmin Developer Forums (Edge Cases & Gotchas)

- **General discussion**: https://forums.garmin.com/developer/connect-iq/f/discussion
- **Bug reports**: https://forums.garmin.com/developer/connect-iq/i/bug-reports

---

## Debugging Checklist

When something goes wrong, check in this order:

1. **"!" crash icon on watch** → Unhandled exception. Check for: `Duration` < 300, missing `(:background)` annotation, accessing UI classes from background, null access on Storage values, View type referenced in AppBase instance variable.
2. **Error -200 on makeWebRequest** → **First suspect: raw `"application/json"` string in headers instead of `Communications.REQUEST_CONTENT_TYPE_JSON`.** This is the most common cause. **Test in the simulator first** — the simulator uses direct HTTP with no BLE, so if -200 appears there too, BLE is definitively ruled out and the cause is a code/header issue. Second suspect: calling from widget foreground context — must use background ServiceDelegate.
3. **Callback never fires** → Background process timed out (30s limit). Ensure `Background.exit()` is called on all code paths, including error paths.
4. **Error -101 (QUEUE_FULL)** → Too many pending web requests. Single-thread all requests — wait for callback before sending next.
5. **Error -300 (TIMEOUT)** → Server took too long. Render free tier cold starts take 30–60 seconds on first request after inactivity.
6. **Data not appearing in onBackgroundData** → Check that `Background.exit(data)` is called with correct data type (String, Number, Array, Dictionary, or null).
7. **Storage values seem stale** → Background and foreground run in separate memory spaces. Always re-read Storage at the start of each context.

---

## Code Style for This Project

- Use explicit type annotations on all function signatures: `as Void`, `as Number`, `as String`, `as Dictionary`, etc.
- Use `try/catch` around `Application.Properties.getValue()` — it throws if the key doesn't exist.
- Use `instanceof` checks before casting Storage/Properties values — they can be null or unexpected types.
- Keep background code minimal — import only what's needed, avoid string formatting in loops.
- Always call `WatchUi.requestUpdate()` after changing any displayed state from the foreground.
- Use `Storage.setValue` / `Storage.getValue` for all foreground↔background communication.

---

## Workflow Rules

- Before implementing any Connect IQ API call, fetch and read the relevant Garmin API docs page.
- Before using a pattern you haven't seen in this codebase, search the Garmin forums for known issues.
- When modifying background code, always verify that `Background.exit()` is called on EVERY code path (success, error, empty queue, etc.).
- When registering temporal events, always wrap in try/catch for `InvalidBackgroundTimeException`.
- Test with both the simulator AND a real device — the simulator does not enforce all BLE/timing constraints.
