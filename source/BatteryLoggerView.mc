import Toybox.Application;
import Toybox.Application.Storage;
import Toybox.Communications;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.Time;
import Toybox.WatchUi;

(:typecheck(disableBackgroundCheck))
class BatteryLoggerView extends WatchUi.View {

    private var _status as String = "Tap for menu";

    public function initialize() {
        View.initialize();
    }

    public function onLayout(dc as Graphics.Dc) as Void {
    }

    public function onShow() as Void {
        WatchUi.requestUpdate();
    }

    public function onUpdate(dc as Graphics.Dc) as Void {
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
        dc.drawText(cx, h * 0.03, Graphics.FONT_XTINY, "Battery Logger", Graphics.TEXT_JUSTIFY_CENTER);

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

    public function triggerSync() as Void {
        var queue = loadQueue();
        if (queue.size() == 0) {
            setStatus("Nothing to sync");
            return;
        }

        var url = "https://346144f088c5fa.lhr.life/api/battery-readings";
        try {
            var prop = Application.Properties.getValue("sync_endpoint");
            if (prop instanceof String && (prop as String).length() > 0) {
                url = prop;
            }
        } catch (ex instanceof Lang.Exception) {}

        if (url.length() == 0) {
            setStatus("No URL configured");
            return;
        }

        var options = {
            :method       => Communications.HTTP_REQUEST_METHOD_POST,
            :headers      => { "Content-Type" => "application/json" },
            :responseType => Communications.HTTP_RESPONSE_CONTENT_TYPE_JSON
        };

        setStatus("Syncing...");
        Communications.makeWebRequest(url, { "readings" => queue }, options, method(:onSyncDone));
    }

    public function onSyncDone(code as Number, data as Dictionary or String or Null) as Void {
        if (code == 200 || code == 201 || code == 204) {
            Storage.setValue("pending_readings", [] as Array);
            Storage.setValue("last_sync_ts", Time.now().value() + 631152000);
            setStatus("Synced!");
        } else {
            setStatus("Failed: " + code.toString());
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
        var nowUnix = Time.now().value() + 631152000;
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
