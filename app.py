import os
import logging
from flask import Flask, request, jsonify

# Initialize Flask application (Name must be 'app' for 'gunicorn app:app')
app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration / Constants
AUTH_TOKEN = os.getenv("SYNC_TOKEN", "jdw_sync_secret_token_2026")


def process_floor_record_file(file_path: str):
    """
    Parses an individual floor record file.
    Returns a tuple: (items_count, bag_total)
    
    Includes 15kg and 20kg counts in the bag total.
    """
    items_count = 0
    bag_count = 0

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                items_count += 1
                
                # Business Logic: 15kg and 20kg count toward bag total
                line_lower = line.lower()
                if "15kg" in line_lower or "20kg" in line_lower or "bag" in line_lower:
                    bag_count += 1

    except Exception as err:
        logger.error(f"Error reading file {file_path}: {err}")

    return items_count, bag_count


def process_drive_folder(folder_path: str):
    """
    Scans the local drive directory for floor records and aggregates stats.
    """
    if not os.path.exists(folder_path):
        return {
            "status": "error",
            "message": f"Directory not found: {folder_path}",
            "processed_files": 0,
            "total_items": 0,
            "total_bags": 0,
            "records": ()
        }

    # IMPORTANT: Keep accumulators as integers to avoid tuple-int addition errors
    processed_files_count = 0
    total_items = 0
    total_bags = 0
    floor_records = ()  # Holds individual file record tuples

    for root, _, files in os.walk(folder_path):
        for file_name in files:
            if file_name.endswith((".csv", ".json", ".txt", ".dat")):
                file_path = os.path.join(root, file_name)
                
                # Unpack the returned tuple (items, bags) into integer variables
                file_items, file_bags = process_floor_record_file(file_path)
                
                processed_files_count += 1
                total_items += file_items
                total_bags += file_bags

                record_entry = {
                    "file_name": file_name,
                    "items": file_items,
                    "bags": file_bags
                }
                
                # Correct tuple concatenation (note the trailing comma)
                floor_records = floor_records + (record_entry,)

    return {
        "status": "success",
        "processed_files": processed_files_count,
        "total_items": total_items,
        "total_bags": total_bags,
        "records": floor_records
    }


@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "service": "jdw-sync"}), 200


@app.route("/dashboard", methods=["GET"])
def dashboard():
    return jsonify({"message": "Welcome to the JDW Sync Dashboard"}), 200


@app.route("/api/sync-drive", methods=["GET", "POST"])
def sync_drive():
    # Verify authentication token
    token = request.args.get("token") or request.headers.get("X-Sync-Token")
    if token != AUTH_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401

    folder_target = os.getenv("FLOOR_RECORDS_PATH", "./floor_records")

    try:
        result = process_drive_folder(folder_target)
        return jsonify(result), 200
    except Exception as e:
        logger.exception("Error during sync process")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)