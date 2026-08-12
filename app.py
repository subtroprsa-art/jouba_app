import os
import io
import json
import logging
import csv
import pandas as pd
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import date, datetime

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

        if inventory_type == "stock":
            query = f"""
                SELECT *
                FROM {table}
                WHERE flr > 0
                ORDER BY date_received DESC
            """
        else:
            query = f"""
                SELECT *
                FROM {table}
                WHERE qty > 0
                ORDER BY date_received DESC
            """
            
        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        inventory = {}
        today = date.today()

        for row in rows:
            # 1. Map salesman
            raw_salesman = row.get('salesman')
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

            # 2. Normalize column names (CRITICAL FIX FOR FLOOR)
            if inventory_type == "floor":
                # The database uses CSV-style names; the frontend expects these keys
                row['commodity'] = row.get('commodty') or row.get('COMMODTY') or row.get('commodity') or ''
                row['farmer_name'] = row.get('producer') or row.get('PRODUCER') or row.get('farmer_name') or ''
                row['pack_weight'] = row.get('pack') or row.get('PACK') or row.get('packing') or row.get('PACKING') or ''
                row['size'] = row.get('size') or row.get('SIZE') or ''
                row['variety'] = row.get('variety') or row.get('VARIETY') or ''
            else:
                # Stock already uses the correct keys from the CSV parser
                row['farmer_name'] = row.get('producer') or row.get('PRODUCER') or row.get('farmer_name') or ''

            # 3. Determine Qty
            if inventory_type == "stock":
                qty = row.get('flr') or 0
            else:
                qty = row.get('qty') or 0

            if qty == 0:
                continue

            # 4. SEQ (Only for floor)
            seq_nr = row.get('seq_nr') or 0

            # 5. Date Calculation
            raw_date = row.get('date_received')
            age_days = 0
            if raw_date:
                try:
                    if isinstance(raw_date, str):
                        dt = datetime.strptime(raw_date.split(' ')[0], '%Y-%m-%d').date()
                    else:
                        dt = raw_date
                    
                    if hasattr(dt, 'year') and dt.year < 2026:
                        dt = date(2026, dt.month, dt.day)
                    age_days = (today - dt).days
                except Exception:
                    age_days = 0

            # 6. Build Item
            item = {
                "salesman": sm,
                "farmer_name": row['farmer_name'],
                "commodity": row['commodity'],
                "variety": row['variety'],
                "size": row['size'],
                "pack_weight": row['pack_weight'],
                "qty": int(qty) if qty else 0,
                "age_days": age_days
            }
            
            # 7. Add SEQ to the item if it's floor
            if inventory_type == "floor":
                item["seq_nr"] = int(seq_nr) if seq_nr else 0
                
            inventory[sm].append(item)

        return jsonify({"inventory": inventory}), 200

    except Exception as e:
        logger.exception("Error fetching inventory")
        return jsonify({"error": str(e)}), 500


# ===================== UPLOAD ENDPOINTS =====================

@app.route("/upload-stock", methods=["POST"])
def upload_stock():
    return handle_upload("stock_records")

@app.route("/upload-floor", methods=["POST"])
def upload_floor():
    return handle_upload("floor_records")

def handle_upload(table_name):
    try:
        if 'file' not in request.files:
            return jsonify({"success": False, "error": "No file part"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"success": False, "error": "No selected file"}), 400

        if file.filename.endswith('.xlsx'):
            df = pd.read_excel(file)
        else:
            stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
            df = pd.read_csv(stream, delimiter='\t')

        df.columns = [str(c).strip().upper() for c in df.columns]

        conn = get_db_connection()
        cursor = conn.cursor()

        inserted_count = 0
        for _, row in df.iterrows():
            if table_name == "stock_records":
                producer = str(row.get('PRODUCER', '')).strip() if pd.notna(row.get('PRODUCER')) else ''
                grn = str(row.get('GRN NO', '')).strip() if pd.notna(row.get('GRN NO')) else ''
                commodity = str(row.get('COMMODTY', '')).strip() if pd.notna(row.get('COMMODTY')) else ''
                packing = str(row.get('PACKING', '')).strip() if pd.notna(row.get('PACKING')) else ''
                variety = str(row.get('VARIETY', '')).strip() if pd.notna(row.get('VARIETY')) else ''
                size = str(row.get('SIZE', '')).strip() if pd.notna(row.get('SIZE')) else ''
                count = str(row.get('COUNT', '')).strip() if pd.notna(row.get('COUNT')) else ''
                flr = int(row.get('FLR', 0)) if pd.notna(row.get('FLR')) else 0
                date_received = row.get('DATE') if pd.notna(row.get('DATE')) else None

                if flr == 0 or not grn:
                    continue

                salesman = parse_salesman(file.filename)

                cursor.execute(f"""
                    INSERT INTO {table_name} 
                    (salesman, grn, producer, commodity, packing, variety, size, count, flr, date_received)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    salesman,
                    grn,
                    producer,
                    commodity,
                    packing,
                    variety,
                    size,
                    count,
                    flr,
                    date_received
                ))
                inserted_count += 1

            else:  # floor_records
                seq_nr = int(row.get('SEQ', 0)) if pd.notna(row.get('SEQ')) else 0
                grn = str(row.get('GRN', '')).strip() if pd.notna(row.get('GRN')) else ''
                producer = str(row.get('PRODUCER', '')).strip() if pd.notna(row.get('PRODUCER')) else ''
                commodity = str(row.get('COMMODTY', '')).strip() if pd.notna(row.get('COMMODTY')) else ''
                pack = str(row.get('PACKING', '')).strip() if pd.notna(row.get('PACKING')) else ''
                variety = str(row.get('VARIETY', '')).strip() if pd.notna(row.get('VARIETY')) else ''
                grade = str(row.get('CLASS', '')).strip() if pd.notna(row.get('CLASS')) else ''
                size = str(row.get('SIZE', '')).strip() if pd.notna(row.get('SIZE')) else ''
                count = str(row.get('COUNT', '')).strip() if pd.notna(row.get('COUNT')) else ''
                qty = int(row.get('BALANCE', 0)) if pd.notna(row.get('BALANCE')) else 0
                date_received = row.get('RECEIVED') if pd.notna(row.get('RECEIVED')) else None

                if qty == 0:
                    continue

                salesman = parse_salesman(file.filename)

                cursor.execute(f"""
                    INSERT INTO {table_name} 
                    (salesman, seq_nr, grn, producer, commodity, pack, variety, grade, size, count, qty, date_received)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    salesman,
                    seq_nr,
                    grn,
                    producer,
                    commodity,
                    pack,
                    variety,
                    grade,
                    size,
                    count,
                    qty,
                    date_received
                ))
                inserted_count += 1

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"success": True, "message": f"Inserted {inserted_count} rows"}), 200

    except Exception as e:
        logger.exception("Error handling upload")
        return jsonify({"success": False, "error": str(e)}), 500


# ===================== EXISTING SYNC ROUTES =====================

@app.route("/api/health", methods=["GET"])
def health_check():
    return jsonify({"success": True, "status": "healthy", "service": "jdw-sync"}), 200


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
