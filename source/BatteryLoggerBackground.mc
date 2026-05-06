import Toybox.Application;
import Toybox.Application.Storage;
import Toybox.Background;
import Toybox.Communications;
import Toybox.Lang;
import Toybox.System;
import Toybox.Time;

(:background)
class BatteryLoggerBackground extends System.ServiceDelegate {

    // Indexed queue storage keys.
    // Individual readings stored as "q_0" … "q_(MAX_QUEUE-1)".
    // "q_head" = index of oldest reading.
    // "q_size" = number of readings currently stored.
    private static const Q_PREFIX     = "q_";
    private static const Q_HEAD_KEY   = "q_head";
    private static const Q_SIZE_KEY   = "q_size";
    private static const MAX_QUEUE    = 200;
    private static const BATCH_SIZE   = 30;
    private static const DEFAULT_URL  = "https://batterylogger.onrender.com/api/battery-readings";
    private static const VERSION      = "1.2.0";

    public function initialize() {
        ServiceDelegate.initialize();
    }

    public function onTemporalEvent() as Void {
        // Always re-register the recurring interval. This handles the case where
        // a one-shot Time.now() Moment was used to trigger an immediate manual sync.
        var intervalSec = 300;
        try {
            var stored = Application.Properties.getValue("interval_sec");
            if (stored instanceof Number && stored >= 300) {
                intervalSec = stored;
            }
        } catch (ex instanceof Lang.Exception) {}
        Background.registerForTemporalEvent(new Time.Duration(intervalSec));

        Storage.setValue("sync_requested", false);

        // One-time migration: discard old array-based queue to free Storage space.
        if (Storage.getValue("pending_readings") != null) {
            Storage.setValue("pending_readings", null);
        }

        enqueue(captureReading());
        syncReadings();
    }

    private function captureReading() as Dictionary {
        // Store only minimal fields — device metadata is merged at sync time.
        var stats = System.getSystemStats();
        var charging = false;
        try { charging = stats.charging; } catch (ex instanceof Lang.Exception) {}

        return {
            "ts"       => Time.now().value(),
            "bat"      => stats.battery,
            "charging" => charging ? 1 : 0
        };
    }

    private function deviceMeta() as Dictionary {
        var deviceId = "unknown";
        var partNumber = "unknown";
        var firmwareVersion = "unknown";
        try {
            var settings = System.getDeviceSettings();
            if (settings.uniqueIdentifier != null) {
                deviceId = settings.uniqueIdentifier;
            } else if (settings.partNumber != null) {
                deviceId = settings.partNumber;
            }
            if (settings.partNumber != null) {
                partNumber = settings.partNumber;
            }
            var fw = settings.firmwareVersion;
            if (fw instanceof Array && fw.size() >= 2) {
                firmwareVersion = fw[0].toString() + "." + fw[1].toString();
            }
        } catch (ex instanceof Lang.Exception) {}

        return {
            "device_id"        => deviceId,
            "part_number"      => partNumber,
            "firmware_version" => firmwareVersion,
            "version"          => VERSION
        };
    }

    private function qHead() as Number {
        var v = Storage.getValue(Q_HEAD_KEY);
        return (v instanceof Number) ? v : 0;
    }

    private function qSize() as Number {
        var v = Storage.getValue(Q_SIZE_KEY);
        return (v instanceof Number) ? v : 0;
    }

    private function enqueue(reading as Dictionary) as Void {
        var head = qHead();
        var size = qSize();

        if (size >= MAX_QUEUE) {
            // Drop the oldest reading to make room.
            Storage.setValue(Q_PREFIX + head.toString(), null);
            head = (head + 1) % MAX_QUEUE;
            Storage.setValue(Q_HEAD_KEY, head);
            size = MAX_QUEUE - 1;
        }

        var tail = (head + size) % MAX_QUEUE;
        try {
            Storage.setValue(Q_PREFIX + tail.toString(), reading);
            Storage.setValue(Q_SIZE_KEY, size + 1);
        } catch (ex instanceof Lang.Exception) {
            // StorageFullException — reading is lost but app continues.
        }
    }

    private function syncReadings() as Void {
        var head = qHead();
        var size = qSize();

        if (size == 0) {
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

        // Load only BATCH_SIZE readings from Storage — heap usage is bounded
        // regardless of total queue size.
        var meta = deviceMeta();
        var batchCount = size < BATCH_SIZE ? size : BATCH_SIZE;
        var batch = [] as Array;

        for (var i = 0; i < batchCount; i++) {
            var idx = (head + i) % MAX_QUEUE;
            var r = Storage.getValue(Q_PREFIX + idx.toString());
            if (r instanceof Dictionary) {
                batch.add({
                    "ts"               => r["ts"],
                    "bat"              => r["bat"],
                    "charging"         => r["charging"],
                    "device_id"        => meta["device_id"],
                    "part_number"      => meta["part_number"],
                    "firmware_version" => meta["firmware_version"],
                    "version"          => meta["version"]
                });
            }
        }

        if (batch.size() == 0) {
            Background.exit("queue_empty");
            return;
        }

        var options = {
            :method       => Communications.HTTP_REQUEST_METHOD_POST,
            :headers      => { "Content-Type" => Communications.REQUEST_CONTENT_TYPE_JSON },
            :responseType => Communications.HTTP_RESPONSE_CONTENT_TYPE_JSON
        };

        Communications.makeWebRequest(url, { "readings" => batch }, options, method(:onSyncComplete));
    }

    public function onSyncComplete(responseCode as Number, data as Dictionary or String or Null) as Void {
        if (responseCode == 200 || responseCode == 201 || responseCode == 204) {
            var head = qHead();
            var size = qSize();
            var removeCount = size < BATCH_SIZE ? size : BATCH_SIZE;

            // Clear sent readings from Storage and advance the head pointer.
            for (var i = 0; i < removeCount; i++) {
                var idx = (head + i) % MAX_QUEUE;
                Storage.setValue(Q_PREFIX + idx.toString(), null);
            }
            Storage.setValue(Q_HEAD_KEY, (head + removeCount) % MAX_QUEUE);
            Storage.setValue(Q_SIZE_KEY, size - removeCount);
            Storage.setValue("last_sync_ts", Time.now().value());
            Background.exit("synced");
        } else {
            Background.exit("sync_fail:" + responseCode.toString());
        }
    }
}
