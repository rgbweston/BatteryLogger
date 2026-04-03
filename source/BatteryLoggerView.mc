import Toybox.Application;
import Toybox.Application.Storage;
import Toybox.Background;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.Time;
import Toybox.WatchUi;

(:typecheck(disableBackgroundCheck))
class BatteryLoggerView extends WatchUi.View {

    private static const VERSION as String = "1.1.0";

    private var _status as String = "Tap to sync";

    public function initialize() {
        View.initialize();
    }

    public function onLayout(dc as Graphics.Dc) as Void {
    }

    public function onShow() as Void {
        updateStatusFromStorage();
        WatchUi.requestUpdate();
    }

    public function onUpdate(dc as Graphics.Dc) as Void {
        updateStatusFromStorage();
        var w  = dc.getWidth();
        var h  = dc.getHeight();
        var cx = w / 2;

        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();

        var stats  = System.getSystemStats();
        var batPct = stats.battery;
        var batStr = batPct.format("%d") + "%";

        var batColor = Graphics.COLOR_GREEN;
        if (batPct <= 20) {
            batColor = Graphics.COLOR_RED;
        } else if (batPct <= 50) {
            batColor = Graphics.COLOR_YELLOW;
        }

        dc.setColor(batColor, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.15, Graphics.FONT_NUMBER_MEDIUM, batStr, Graphics.TEXT_JUSTIFY_CENTER);

        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.03, Graphics.FONT_XTINY, "v" + VERSION, Graphics.TEXT_JUSTIFY_CENTER);

        var queue  = loadQueue();
        var qLabel = queue.size().toString() + " reading" + (queue.size() == 1 ? "" : "s") + " pending";
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.50, Graphics.FONT_XTINY, qLabel, Graphics.TEXT_JUSTIFY_CENTER);

        var lastSync = Storage.getValue("last_sync_ts");
        var syncLabel = "Never synced";
        if (lastSync instanceof Number) {
            syncLabel = "Last sync: " + formatRelativeTime(lastSync);
        }
        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.62, Graphics.FONT_XTINY, syncLabel, Graphics.TEXT_JUSTIFY_CENTER);

        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.78, Graphics.FONT_XTINY, _status, Graphics.TEXT_JUSTIFY_CENTER);
    }

    public function setStatus(msg as String) as Void {
        _status = msg;
        WatchUi.requestUpdate();
    }

    private function updateStatusFromStorage() as Void {
        var result = Storage.getValue("last_sync_result");
        if (result instanceof String) {
            var msg = result as String;
            if (msg.equals("synced")) {
                _status = "Synced!";
            } else if (msg.equals("queue_empty")) {
                _status = "Nothing to sync";
            } else if (msg.equals("no_url_configured")) {
                _status = "No URL set";
            } else {
                _status = msg;
            }
            Storage.setValue("last_sync_result", null);
        }
    }

    public function triggerSync() as Void {
        Storage.setValue("sync_requested", true);
        try {
            Background.registerForTemporalEvent(Time.now());
            setStatus("Sync queued...");
        } catch (ex instanceof Lang.Exception) {
            // 5-min cooldown still active — background will pick it up on next cycle
            setStatus("Queued (~5 min)");
        }
    }

    private function loadQueue() as Array {
        var stored = Storage.getValue("pending_readings");
        if (stored instanceof Array) {
            return stored;
        }
        return [] as Array;
    }

    private function formatRelativeTime(unixTs as Number) as String {
        var nowUnix = Time.now().value();
        var diff    = nowUnix - unixTs;
        if (diff < 60)   { return diff.toString() + "s ago"; }
        if (diff < 3600) { return (diff / 60).toString() + "m ago"; }
        return (diff / 3600).toString() + "h ago";
    }
}

(:typecheck(disableBackgroundCheck))
class BatteryLoggerDelegate extends WatchUi.BehaviorDelegate {

    private var _view as BatteryLoggerView;

    public function initialize(view as BatteryLoggerView) {
        BehaviorDelegate.initialize();
        _view = view;
    }

    public function onSelect() as Boolean {
        _view.triggerSync();
        return true;
    }
}
