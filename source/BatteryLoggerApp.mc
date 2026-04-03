import Toybox.Application;
import Toybox.Application.Storage;
import Toybox.Background;
import Toybox.Lang;
import Toybox.System;
import Toybox.Time;
import Toybox.WatchUi;

(:background)
class BatteryLoggerApp extends Application.AppBase {

    public function initialize() {
        AppBase.initialize();
    }

    public function onStart(state as Dictionary?) as Void {
        var intervalSec = 300;
        try {
            var stored = Application.Properties.getValue("interval_sec");
            if (stored instanceof Number && stored >= 300) {
                intervalSec = stored;
            }
        } catch (ex instanceof Lang.Exception) {
        }
        // Schedule from the last event time to avoid resetting the timer on widget open.
        // If nextTime is already in the past (e.g. after a long restart), fall back to
        // Time.now() — some firmware versions don't reliably fire past Moments.
        var lastTime = Background.getLastTemporalEventTime();
        if (lastTime != null) {
            var nextTime = lastTime.add(new Time.Duration(intervalSec));
            if (nextTime.value() <= Time.now().value()) {
                Background.registerForTemporalEvent(Time.now());
            } else {
                Background.registerForTemporalEvent(nextTime);
            }
        } else {
            Background.registerForTemporalEvent(Time.now());
        }
    }

    public function onStop(state as Dictionary?) as Void {
    }

    public function getInitialView() as [Views] or [Views, InputDelegates] {
        var view = new BatteryLoggerView();
        return [view, new BatteryLoggerDelegate(view)];
    }

    public function getServiceDelegate() as [ServiceDelegate] {
        return [new BatteryLoggerBackground()];
    }

    public function onBackgroundData(data as Application.PersistableType) as Void {
        // Write result to storage so the view can pick it up on next redraw.
        if (data instanceof String) {
            Storage.setValue("last_sync_result", data);
        }
        WatchUi.requestUpdate();
    }
}
