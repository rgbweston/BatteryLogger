import Toybox.Application;
import Toybox.Application.Storage;
import Toybox.Background;
import Toybox.Communications;
import Toybox.Lang;
import Toybox.System;
import Toybox.Time;

(:background)
class BatteryLoggerBackground extends System.ServiceDelegate {

    private static const QUEUE_KEY    = "pending_readings";
    private static const MAX_QUEUE    = 150;
    private static const DEFAULT_URL  = "https://346144f088c5fa.lhr.life/api/battery-readings";

    public function initialize() {
        ServiceDelegate.initialize();
    }

    public function onTemporalEvent() as Void {
        enqueue(captureReading());
        syncReadings();
    }

    private function captureReading() as Dictionary {
        var stats = System.getSystemStats();
        var charging = false;
        try { charging = stats.charging; } catch (ex instanceof Lang.Exception) {}
        var unixNow = Time.now().value() + 631152000;
        return {
            "ts"       => unixNow,
            "bat"      => stats.battery,
            "charging" => charging ? 1 : 0
        };
    }

    private function enqueue(reading as Dictionary) as Void {
        var queue = loadQueue();
        while (queue.size() >= MAX_QUEUE) {
            queue.remove(queue[0]);
        }
        queue.add(reading);
        Storage.setValue(QUEUE_KEY, queue);
    }

    private function loadQueue() as Array {
        var stored = Storage.getValue(QUEUE_KEY);
        if (stored instanceof Array) {
            return stored;
        }
        return [] as Array;
    }

    private function syncReadings() as Void {
        var queue = loadQueue();
        if (queue.size() == 0) {
            Background.exit("queue_empty");
            return;
        }

        var url = DEFAULT_URL;
        try {
            var prop = Application.Properties.getValue("sync_endpoint");
            if (prop instanceof String && (prop as String).length() > 0) {
                url = prop;
            }
        } catch (ex instanceof Lang.Exception) {}

        if (url.length() == 0) {
            Background.exit("no_url_configured");
            return;
        }

        var options = {
            :method       => Communications.HTTP_REQUEST_METHOD_POST,
            :headers      => { "Content-Type" => "application/json" },
            :responseType => Communications.HTTP_RESPONSE_CONTENT_TYPE_JSON
        };

        Communications.makeWebRequest(url, { "readings" => queue }, options, method(:onSyncComplete));
    }

    public function onSyncComplete(responseCode as Number, data as Dictionary or String or Null) as Void {
        if (responseCode == 200 || responseCode == 201 || responseCode == 204) {
            Storage.setValue(QUEUE_KEY, [] as Array);
            Background.exit("synced");
        } else {
            Background.exit("sync_fail:" + responseCode.toString());
        }
    }
}
