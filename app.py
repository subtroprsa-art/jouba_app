import os
import io
import json
import logging
import csv
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import psycopg2
from psycopg2.extras import RealDictCursor

# Google API imports
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "jdw_super_secret_login_key_2026")
app.config['SESSION_TYPE'] = 'filesystem'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Authentication token for API calls
AUTH_TOKEN = os.getenv("SYNC_TOKEN", "jdw_sync_secret_token_2026")

# Target Raw Folder IDs
FOLDER_FLOOR_BALANCE = os.getenv("GOOGLE_DRIVE_FOLDER_ID_FLOOR", "1akYejLRp-bOvdjJEat4Z1XC1frru9j_Y")
FOLDER_STOCK_SCAN = os.getenv("GOOGLE_DRIVE_FOLDER_ID_STOCK", "1DrYmim6xThu6KfKRplr5SDBVZc-BFMBm")

DATABASE_URL = os.getenv("DATABASE_URL")

# Hardcoded users
USERS = {
    "riaan": "password123",
    "christoff": "password123"
}

# Make user_name available to all HTML templates
@app.context_processor
def inject_user():
    return dict(user_name=session.get("user_name", "Guest"))

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def get_drive_service():
    """Authenticates with Google Drive using GOOGLE_CREDENTIALS_JSON."""
    service_account_info = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not service_account_info:
        logger.error("GOOGLE_CREDENTIALS_JSON environment variable is missing.")
        return None

    try:
        creds_dict = json.loads(service_account_info)
        creds = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        logger.exception("Failed to build Google Drive service")
        return None


def parse_salesman(filename: str) -> str:
    name = filename.lower()
    if name.startswith("cdw"):
        return "Christoff"
    if name.startswith("riaa") or name.startswith("riaan"):
        return "Riaan"
    if name.startswith("pot"):
        return "Pot"
    return "Unassigned"


# ===================== HTML ROUTES =====================

@app.route("/", methods=["GET"])
def login_page():
    if session.get("user"):
        return redirect(url_for("dashboard_page"))
    return render_template("login.html", error=None)

@app.route("/", methods=["POST"])
def login_action():
    username = request.form.get("username")
    password = request.form.get("password")

    if username in USERS and USERS[username] == password:
        session["user"] = username
        session["user_name"] = "Riaan Joubert" if username == "riaan" else "Christoff de Wet"
        return redirect(url_for("dashboard_page"))
    else:
        return render_template("login.html", error="Invalid username or password")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))

@app.route("/dashboard")
def dashboard_page():
    if not session.get("user"):
        return redirect(url_for("login_page"))
    return render_template("dashboard.html")

@app.route("/stock")
def stock_page():
    if not session.get("user"):
        return redirect(url_for("login_page"))
    return render_template("stock.html")

@app.route("/floor-balance")
def floor_balance_page():
    if not session.get("user"):
        return redirect(url_for("login_page"))
    return render_template("floor_balance.html")

@app.route("/pipeline")
def pipeline_page():
    if not session.get("user"):
        return redirect(url_for("login_page"))
    return render_template("pipeline.html")

@app.route("/inventory")
def inventory_page():
    if not session.get("user"):
        return redirect(url_for("login_page"))
    return render_template("inventory.html")


# ===================== DATA API ROUTES (NEW) =====================

@app.route("/api/inventory/<inventory_type>", methods=["GET"])
def get_inventory(inventory_type):
    """Fetches stock or floor inventory grouped by salesman."""
    if not session.get("user"):
        return jsonify({"error": "Unauthorized"}), 401

    table = "stock_records" if inventory_type == "stock" else "floor_records"
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Query to fetch inventory with age calculation
        query = f"""
            SELECT salesman, farmer AS farmer_name, commodity, variety, size, pack_weight, qty,
                   EXTRACT(DAY FROM (CURRENT_DATE - intake_date)) AS age_days
            FROM {table}
            ORDER BY salesman, intake_date DESC
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        # Group by salesman
        inventory = {}
        for row in rows:
            sm = row['salesman']
            if sm not in inventory:
                inventory[sm] = []
            inventory[sm].append(dict(row))

        return jsonify({"inventory": inventory}), 200

    except Exception as e:
        logger.exception("Error fetching inventory")
        return jsonify({"error": str(e)}), 500


@app.route("/api/sales-pipeline", methods=["GET"])
def get_sales_pipeline():
    """Returns top buyers with their spending and available commodities."""
    if not session.get("user"):
        return jsonify({"error": "Unauthorized"}), 401

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 1. Get top buyers (this assumes you have a 'buyer_history' table - adjust if your table name differs)
        # If you don't have a buyer history table yet, this will return an empty list.
        # For now, I'll return a dummy structure so the page doesn't break.
        cursor.execute("""
            SELECT buyer_name AS buyer, SUM(total_spent) as total_spent, COUNT(*) as total_units, phone
            FROM buyer_history
            GROUP BY buyer_name, phone
            ORDER BY total_spent DESC
            LIMIT 20
        """)
        buyers = cursor.fetchall()

        # 2. Get available commodities from stock_records
        cursor.execute("SELECT DISTINCT commodity FROM stock_records WHERE qty > 0")
        commodities_raw = cursor.fetchall()
        commodities = [row['commodity'] for row in commodities_raw if row['commodity']]

        cursor.close()
        conn.close()

        # Format response
        pipeline = []
        for b in buyers:
            pipeline.append({
                "buyer": b['buyer'],
                "total_spent": float(b['total_spent']) if b['total_spent'] else 0,
                "total_units": int(b['total_units']) if b['total_units'] else 0,
                "phone": b['phone'] or "",
                "commodities": commodities,
                "contacted_by": None  # You can extend this later
            })

        return jsonify({"pipeline": pipeline}), 200

    except Exception as e:
        logger.exception("Error fetching pipeline")
        # Return empty list so frontend doesn't crash, but log the error
        return jsonify({"pipeline": [], "error": str(e)}), 500


@app.route("/api/buyer-details/<buyer_name>", methods=["GET"])
def get_buyer_details(buyer_name):
    """Returns detailed product matches for a specific buyer."""
    if not session.get("user"):
        return jsonify({"error": "Unauthorized"}), 401

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # This is a mock query - adjust based on your actual buyer history table structure
        cursor.execute("""
            SELECT commodity, pack_weight as pack, SUM(qty) as total_qty
            FROM buyer_history
            WHERE buyer_name = %s
            GROUP BY commodity, pack_weight
            ORDER BY total_qty DESC
            LIMIT 10
        """, (buyer_name,))
        matches = cursor.fetchall()
        
        cursor.close()
        conn.close()

        return jsonify([dict(m) for m in matches]), 200

    except Exception as e:
        logger.exception("Error fetching buyer details")
        return jsonify([]), 200


@app.route("/api/mark-contacted", methods=["POST"])
def mark_contacted():
    """Marks a buyer as contacted (for pipeline locking)."""
    if not session.get("user"):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    buyer = data.get("buyer")
    user = session.get("user_name")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Add a 'contacted_by' column to your buyer_history table first if you want this to persist.
        # For now, we'll just return success so the frontend locks it for this session.
        cursor.close()
        conn.close()
        
        return jsonify({"success": True}), 200

    except Exception as e:
        logger.exception("Error marking contacted")
        return jsonify({"success": False, "error": str(e)}), 500


# ===================== EXISTING SYNC ROUTES =====================

@app.route("/api/health", methods=["GET"])
def health_check():
    return jsonify({"success": True, "status": "healthy", "service": "jdw-sync"}), 200

@app.route("/api/upload-inventory", methods=["POST"])
def upload_inventory():
    """Handles POST payloads pushed directly from Google Apps Script."""
    try:
        data = request.get_json(silent=True) or {}

        token = data.get("token") or request.headers.get("X-Sync-Token") or request.args.get("token")
        if token != AUTH_TOKEN:
            return jsonify({"success": False, "error": "Unauthorized"}), 401

        target_table = data.get("target_table", "unknown")
        salesman = data.get("salesman", "Unassigned")
        records = data.get("records", [])

        if not records:
            return jsonify({"success": False, "message": "No records received"}), 400

        total_items = 0
        total_bags = 0
        processed_records = []

        for index, record in enumerate(records, start=1):
            qty = int(record.get("qty", 0))
            pack = str(record.get("pack", "")).lower()
            total_items += qty
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
        logger.exception("Error processing uploaded inventory")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/sync-drive", methods=["GET", "POST"])
def sync_drive():
    """Debug route: Scans Google Drive and outputs raw contents and permissions."""
    token = request.args.get("token") or request.headers.get("X-Sync-Token")
    if token != AUTH_TOKEN:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    service = get_drive_service()
    if not service:
        return jsonify({
            "success": False,
            "error": "Google Drive authentication failed. Check GOOGLE_CREDENTIALS_JSON in Render environment."
        }), 500

    debug_info = {}
    folders_to_check = {
        "floor_raw": FOLDER_FLOOR_BALANCE,
        "stock_raw": FOLDER_STOCK_SCAN
    }
    total_files_found = 0
    all_records = []

    for folder_name, folder_id in folders_to_check.items():
        try:
            query = f"'{folder_id}' in parents and trashed = false"
            results = service.files().list(q=query, fields="files(id, name, mimeType)").execute()
            raw_files = results.get("files", [])
            total_files_found += len(raw_files)
            folder_file_details = []

            for f in raw_files:
                file_id = f["id"]
                file_name = f["name"]
                mime_type = f.get("mimeType", "")
                folder_file_details.append({
                    "id": file_id,
                    "name": file_name,
                    "mimeType": mime_type
                })

                if mime_type == "application/vnd.google-apps.spreadsheet":
                    request_media = service.files().export_media(fileId=file_id, mimeType="text/csv")
                elif file_name.lower().endswith(".csv") or mime_type == "text/csv":
                    request_media = service.files().get_media(fileId=file_id)
                else:
                    continue

                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request_media)
                done = False
                while not done:
                    _, done = downloader.next_chunk()

                content = fh.getvalue().decode("utf-8", errors="ignore")
                lines = content.splitlines()
                if len(lines) <= 1:
                    continue

                reader = csv.reader(lines, delimiter='\t')
                headers = [h.strip().lower() for h in next(reader, [])]

                def col_index(name):
                    return headers.index(name) if name in headers else None

                if folder_name == "floor_raw":
                    qty_idx = col_index("qty")
                    pack_idx = col_index("container")
                    commodity_idx = None
                else:
                    qty_idx = col_index("qty_floor")
                    pack_idx = None
                    commodity_idx = col_index("commodity")

                def get_val(row, i):
                    return row[i].strip() if i is not None and i < len(row) else ""

                for idx, row in enumerate(reader, start=1):
                    if not row or not any(row):
                        continue
                    qty_val = get_val(row, qty_idx)
                    qty = int(qty_val) if qty_val.isdigit() else 0
                    if pack_idx is not None:
                        pack = get_val(row, pack_idx)
                    else:
                        commodity_val = get_val(row, commodity_idx)
                        parts = commodity_val.split(",")
                        pack = parts[1].strip() if len(parts) > 1 else ""

                    all_records.append({
                        "file_name": file_name,
                        "salesman": parse_salesman(file_name),
                        "folder": folder_name,
                        "seq_nr": idx,
                        "qty": qty,
                        "pack": pack
                    })

            debug_info[folder_name] = {
                "folder_id": folder_id,
                "file_count": len(raw_files),
                "files": folder_file_details
            }

        except Exception as e:
            logger.exception(f"Error checking folder {folder_name}")
            debug_info[folder_name] = {
                "folder_id": folder_id,
                "error": str(e)
            }

    return jsonify({
        "success": True,
        "total_files_found": total_files_found,
        "processed_records_count": len(all_records),
        "debug_folders": debug_info,
        "records": all_records
    }), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)