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


# ===================== DATA API ROUTES =====================

@app.route("/api/inventory/<inventory_type>", methods=["GET"])
def get_inventory(inventory_type):
    """Fetches stock or floor inventory grouped by salesman."""
    if not session.get("user"):
        return jsonify({"error": "Unauthorized"}), 401

    table = "stock_records" if inventory_type == "stock" else "floor_records"
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Drop the complex CASE mapping into SQL directly for speed
        if inventory_type == "stock":
            query = f"""
                SELECT 
                    salesman, 
                    producer AS farmer_name, 
                    commodity, 
                    variety, 
                    size, 
                    pack AS pack_weight, 
                    qty_floor AS qty,
                    date_received
                FROM {table}
                WHERE qty_floor > 0
                ORDER BY salesman, date_received DESC
            """
        else: # floor_records
            query = f"""
                SELECT 
                    salesman, 
                    prod AS farmer_name, 
                    commodity, 
                    variety, 
                    container AS pack_weight, 
                    qty AS qty,
                    dn_date AS date_received
                FROM {table}
                WHERE qty > 0
                ORDER BY salesman, dn_date DESC
            """

        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        # GROUP + PARSE IN PYTHON (No SQL crashes!)
        from datetime import datetime, date
        inventory = {}
        today = date.today()

        for row in rows:
            # 1. Map salesman to proper short name
            raw_salesman = row['salesman']
            if raw_salesman == "DE WET, CHRISTOFF REINHARDT":
                sm = "Christoff"
            elif raw_salesman == "JOUBERT, RIAAN":
                sm = "Riaan"
            elif raw_salesman == "POTGIETER":
                sm = "Pot"
            else:
                sm = raw_salesman

            if sm not in inventory:
                inventory[sm] = []

            # 2. Parse the raw date safely
            raw_date = row['date_received']
            try:
                # Try converting to string and parsing
                d_str = str(raw_date).strip()
                
                # If it's like 20260803 (YYYYMMDD)
                if d_str.isdigit() and len(d_str) == 8:
                    dt = datetime.strptime(d_str, '%Y%m%d').date()
                
                # If it's like 2026-08-03 (Already standard date)
                elif '-' in d_str and d_str.replace('-', '').isdigit():
                    dt = datetime.strptime(d_str, '%Y-%m-%d').date()
                
                # If it's like 28-JUL-26 (Old text format)
                else:
                    dt = datetime.strptime(d_str, '%d-%b-%y').date()
                
                age_days = (today - dt).days
            except Exception:
                # If parsing completely fails, default to 0
                age_days = 0

            # 3. Build the final object
            item = dict(row)
            item['salesman'] = sm
            item['age_days'] = age_days
            # Remove raw date to keep JSON clean
            item.pop('date_received', None)
            
            inventory[sm].append(item)

        return jsonify({"inventory": inventory}), 200

    except Exception as e:
        logger.exception("Error fetching inventory")
        return jsonify({"error": str(e)}), 500


@app.route("/api/sales-pipeline", methods=["GET"])
def get_sales_pipeline():
    if not session.get("user"):
        return jsonify({"error": "Unauthorized"}), 401

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get top buyers and their phones
        cursor.execute("""
            SELECT 
                bh.buyer AS buyer, 
                SUM(bh.total) as total_spent, 
                COUNT(*) as total_units, 
                bp.phone
            FROM buyer_history bh
            LEFT JOIN buyer_phones bp ON bh.buyer = bp.buyer_name
            GROUP BY bh.buyer, bp.phone
            ORDER BY total_spent DESC
            LIMIT 20
        """)
        buyers = cursor.fetchall()

        # Get distinct commodities currently on floor/stock
        cursor.execute("""
            SELECT DISTINCT commodity FROM stock_records WHERE qty_floor > 0
            UNION
            SELECT DISTINCT commodity FROM floor_records WHERE qty > 0
        """)
        commodities_raw = cursor.fetchall()
        commodities = [row['commodity'] for row in commodities_raw if row['commodity']]

        cursor.close()
        conn.close()

        pipeline = []
        for b in buyers:
            pipeline.append({
                "buyer": b['buyer'],
                "total_spent": float(b['total_spent']) if b['total_spent'] else 0,
                "total_units": int(b['total_units']) if b['total_units'] else 0,
                "phone": b['phone'] or "",
                "commodities": commodities,
                "contacted_by": None
            })

        return jsonify({"pipeline": pipeline}), 200

    except Exception as e:
        logger.exception("Error fetching pipeline")
        return jsonify({"pipeline": [], "error": str(e)}), 500


@app.route("/api/buyer-details/<buyer_name>", methods=["GET"])
def get_buyer_details(buyer_name):
    if not session.get("user"):
        return jsonify({"error": "Unauthorized"}), 401

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT commodity, pack, SUM(qty) as total_qty
            FROM buyer_history
            WHERE buyer = %s
            GROUP BY commodity, pack
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
    if not session.get("user"):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    buyer = data.get("buyer")
    user = session.get("user_name")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO buyer_contact_log (buyer, contacted_by, contacted_at)
            VALUES (%s, %s, NOW())
        """, (buyer, user))
        
        conn.commit()
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

            for f in raw_files:
                file_id = f["id"]
                file_name = f["name"]
                mime_type = f.get("mimeType", "")

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
                else:
                    qty_idx = col_index("qty_floor")
                    pack_idx = col_index("pack")

                def get_val(row, i):
                    return row[i].strip() if i is not None and i < len(row) else ""

                for idx, row in enumerate(reader, start=1):
                    if not row or not any(row):
                        continue
                    qty_val = get_val(row, qty_idx)
                    qty = int(qty_val) if qty_val.isdigit() else 0
                    pack = get_val(row, pack_idx)

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
                "files": [{"id": f["id"], "name": f["name"], "mimeType": f.get("mimeType", "")} for f in raw_files]
            }

        except Exception as e:
            logger.exception(f"Error checking folder {folder_name}")
            debug_info[folder_name] = {"folder_id": folder_id, "error": str(e)}

    return jsonify({
        "success": True,
        "total_files_found": total_files_found,
        "processed_records_count": len(all_records),
        "debug_folders": debug_info,
        "records": all_records
    }), 200


def parse_salesman(filename: str) -> str:
    name = filename.lower()
    if name.startswith("cdw"):
        return "Christoff"
    if name.startswith("riaa") or name.startswith("riaan"):
        return "Riaan"
    if name.startswith("pot"):
        return "Pot"
    return "Unassigned"

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)