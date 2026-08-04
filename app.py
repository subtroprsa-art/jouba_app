import os
import logging
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Authentication token (Matches APP_SYNC_TOKEN in Apps Script)
AUTH_TOKEN = os.getenv("SYNC_TOKEN", "jdw_sync_secret_token_2026")


@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"success": True, "status": "healthy", "service": "jdw-sync"}), 200


@app.route("/dashboard", methods=["GET"])
def dashboard():
    return jsonify({"success": True, "message": "Welcome to the JDW Sync Dashboard"}), 200


@app.route("/api/upload-inventory", methods=["POST"])
def upload_inventory():
    try:
        data = request.get_json(silent=True) or {}

        # 1. Validate Token
        token = data.get("token") or request.headers.get("X-Sync-Token") or request.args.get("token")
        if token != AUTH_TOKEN:
            logger.warning("Unauthorized access attempt with invalid token.")
            return jsonify({"success": False, "error": "Unauthorized"}), 401

        # 2. Extract payload variables sent by Apps Script
        target_table = data.get("target_table", "unknown")
        salesman = data.get("salesman", "Unassigned")
        records = data.get("records", [])

        if not records:
            return jsonify({"success": False, "message": "No records received"}), 400

        total_items = 0
        total_bags = 0
        processed_records = []

        # 3. Process parsed rows sent by Apps Script
        for index, record in enumerate(records, start=1):
            qty = int(record.get("qty", 0))
            pack = str(record.get("pack", "")).lower()

            total_items += qty

            # Business Logic: 15kg and 20kg are included in bag total
            if "15kg" in pack or "20kg" in pack or "bag" in pack:
                total_bags += qty

            processed_records.append({
                "seq_nr": record.get("seq_nr", index),
                "farmer": record.get("farmer", ""),
                "commodity": record.get("commodity", ""),
                "variety": record.get("variety", ""),
                "size": record.get("size", ""),
                "pack": record.get("pack", ""),
                "qty": qty,
                "salesman": salesman,
                "target_table": target_table
            })

        logger.info(
            f"Successfully processed {len(records)} rows | Table: {target_table} | Salesman: {salesman} | Bags: {total_bags}"
        )

        # 4. Return success JSON matching Apps Script's expected check: resText.includes('"success":true')
        return jsonify({
            "success": True,
            "status": "success",
            "table": target_table,
            "salesman": salesman,
            "processed_files": 1,
            "total_items": total_items,
            "total_bags": total_bags,
            "records": processed_records
        }), 200

    except Exception as e:
        logger.exception("Error during inventory upload")
        return jsonify({"success": False, "error": str(e)}), 500


# Fallback endpoint for backwards compatibility or GET testing
@app.route("/api/sync-drive", methods=["GET", "POST"])
def sync_drive():
    token = request.args.get("token") or request.headers.get("X-Sync-Token")
    if token != AUTH_TOKEN:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    return jsonify({
        "success": True,
        "status": "success",
        "processed_files": 0,
        "total_items": 0,
        "total_bags": 0,
        "records": []
    }), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)