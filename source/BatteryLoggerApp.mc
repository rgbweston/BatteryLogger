import Toybox.Application;
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
        Background.registerForTemporalEvent(new Time.Duration(intervalSec));
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
        WatchUi.requestUpdate();
    }
}
