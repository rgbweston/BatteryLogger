#!/usr/bin/env python3
"""
battery_server.py — Flask server to receive battery readings
from the BatteryLogger Connect IQ app.

The watch POSTs JSON like:
    {
      "readings": [
        {"ts": 1711123456, "bat": 73.5, "charging": 0, "device_id": "006-B3258-00", "version": "1.0.3"},
        {"ts": 1711123756, "bat": 72.1, "charging": 0, "device_id": "006-B3258-00", "version": "1.0.3"}
      ]
    }

Requires a PostgreSQL database. Set DATABASE_URL in the environment
(Render provides this automatically when you attach a PostgreSQL database).
"""

import os
import time
from datetime import datetime, timezone
from flask import Flask, request, jsonify, abort
import psycopg2
import psycopg2.extras

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Render's PostgreSQL URL starts with "postgres://", but psycopg2 requires "postgresql://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ── Optional: very simple shared-secret auth ──────────────────────────────────
REQUIRED_API_KEY = os.environ.get("BATTERY_API_KEY", "")


def check_auth():
    if REQUIRED_API_KEY:
        key = request.headers.get("X-Api-Key", "")
        if key != REQUIRED_API_KEY:
            abort(401, description="Invalid or missing X-Api-Key header")


def get_db():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS readings (
                    id          SERIAL PRIMARY KEY,
                    device_id   TEXT    NOT NULL DEFAULT 'unknown',
                    version     TEXT    NOT NULL DEFAULT 'unknown',
                    ts          BIGINT  NOT NULL,
                    ts_iso      TEXT    NOT NULL,
                    bat         REAL    NOT NULL,
                    charging    INTEGER NOT NULL DEFAULT 0,
                    received_at BIGINT  NOT NULL
                )
            """)


# Initialise the table on startup.
with app.app_context():
    init_db()


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

    with get_db() as conn:
        with conn.cursor() as cur:
            for r in readings:
                if not all(k in r for k in ("ts", "bat")):
                    continue  # skip malformed entries

                ts = int(r["ts"])
                cur.execute("""
                    INSERT INTO readings (device_id, version, ts, ts_iso, bat, charging, received_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    r.get("device_id", "unknown"),
                    r.get("version", "unknown"),
                    ts,
                    datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                    float(r["bat"]),
                    int(r.get("charging", 0)),
                    received_at,
                ))
                saved += 1

    return jsonify({"saved": saved}), 200


# ── GET /api/battery-readings — basic inspection endpoint ─────────────────────

@app.route("/api/battery-readings", methods=["GET"])
def list_readings():
    check_auth()

    limit     = int(request.args.get("limit", 500))
    device_id = request.args.get("device_id")
    from_ts   = request.args.get("from", type=int)
    to_ts     = request.args.get("to", type=int)

    filters = []
    params  = []
    if device_id:
        filters.append("device_id = %s")
        params.append(device_id)
    if from_ts is not None:
        filters.append("ts >= %s")
        params.append(from_ts)
    if to_ts is not None:
        filters.append("ts <= %s")
        params.append(to_ts)

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    params.append(limit)

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"""
                SELECT device_id, version, ts, ts_iso, bat, charging, received_at
                FROM readings
                {where}
                ORDER BY ts DESC
                LIMIT %s
            """, params)
            rows = [dict(r) for r in cur.fetchall()]

    return jsonify(rows), 200


# ── GET /api/status — health check ───────────────────────────────────────────

@app.route("/api/status")
def status():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM readings")
            count = cur.fetchone()[0]
    return jsonify({"status": "ok", "readings_stored": count})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    print(f"Battery Logger server starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=True)
