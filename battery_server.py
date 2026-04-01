#!/usr/bin/env python3
"""
battery_server.py — minimal Flask server to receive battery readings
from the BatteryLogger Connect IQ app.

Usage:
    pip install flask
    python battery_server.py

The watch POSTs JSON like:
    {
      "readings": [
        {"ts": 1711123456, "bat": 73.5, "charging": 0, "device_id": "006-B3258-00", "version": "1.0.3"},
        {"ts": 1711123756, "bat": 72.1, "charging": 0, "device_id": "006-B3258-00", "version": "1.0.3"}
      ]
    }

Readings are appended to readings.jsonl (one JSON object per line)
so they're easy to load into pandas / R for analysis.

For a production study, swap the file append with a real database
(SQLite, PostgreSQL, etc.) and add API key auth.
"""

import json
import os
import time
from datetime import datetime, timezone
from flask import Flask, request, jsonify, abort

app = Flask(__name__)
DATA_FILE = "readings.jsonl"

# ── Optional: very simple shared-secret auth ──────────────────────────────────
# Set the env var BATTERY_API_KEY to require it in the X-Api-Key header.
# Leave unset (or empty) to disable auth during development.
REQUIRED_API_KEY = os.environ.get("BATTERY_API_KEY", "")


def check_auth():
    if REQUIRED_API_KEY:
        key = request.headers.get("X-Api-Key", "")
        if key != REQUIRED_API_KEY:
            abort(401, description="Invalid or missing X-Api-Key header")


# ── POST /api/battery-readings ────────────────────────────────────────────────

@app.route("/api/battery-readings", methods=["POST"])
def ingest_readings():
    check_auth()

    data = request.get_json(silent=True)
    if data is None or "readings" not in data:
        return jsonify({"error": "missing 'readings' array"}), 400

    readings = data["readings"]
    if not isinstance(readings, list):
        return jsonify({"error": "'readings' must be an array"}), 400

    received_at = int(time.time())

    saved = 0
    with open(DATA_FILE, "a") as f:
        for r in readings:
            # Validate required fields.
            if not all(k in r for k in ("ts", "bat")):
                continue  # skip malformed entries

            record = {
                "device_id":   r.get("device_id", "unknown"),
                "version":     r.get("version", "unknown"),
                "ts":          int(r["ts"]),
                "bat":         float(r["bat"]),
                "charging":    int(r.get("charging", 0)),
                "received_at": received_at,
                # Human-readable for quick grepping.
                "ts_iso": datetime.fromtimestamp(
                    int(r["ts"]), tz=timezone.utc).isoformat(),
            }
            f.write(json.dumps(record) + "\n")
            saved += 1

    return jsonify({"saved": saved}), 200


# ── GET /api/battery-readings — basic inspection endpoint ─────────────────────

@app.route("/api/battery-readings", methods=["GET"])
def list_readings():
    check_auth()
    if not os.path.exists(DATA_FILE):
        return jsonify([])

    rows = []
    with open(DATA_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    # Newest first, capped at 500 for the browser.
    rows.sort(key=lambda r: r.get("ts", 0), reverse=True)
    return jsonify(rows[:500])


# ── GET /api/status — health check ───────────────────────────────────────────

@app.route("/api/status")
def status():
    count = 0
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            count = sum(1 for line in f if line.strip())
    return jsonify({"status": "ok", "readings_stored": count})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    print(f"Battery Logger server starting — writing to {DATA_FILE}")
    print("POST /api/battery-readings to ingest readings")
    print("GET  /api/battery-readings to inspect stored data")
    app.run(host="0.0.0.0", port=port, debug=True)
