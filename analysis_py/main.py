import argparse
import pandas as pd
from load import load_all
from battery import plot_annotated, plot_interactive
from dashboard import generate_dashboard

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BatteryLogger analysis")
    parser.add_argument("--days", type=int, default=None,
                        help="Only plot the last N days of data (default: all)")
    args = parser.parse_args()

    data = load_all()

    if args.days is not None:
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=args.days)
        data = data[data['timestamp'] >= cutoff].reset_index(drop=True)
        print(f"Filtered to last {args.days} days: {len(data)} readings")

    plot_annotated(data,   save_path="battery_annotated.png")
    generate_dashboard(data, save_path="dashboard.html")
    # plot_interactive(data, save_path="battery_interactive.html")
