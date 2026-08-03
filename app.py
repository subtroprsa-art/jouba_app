import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify, render_template, redirect, url_for, session

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "jdw-fresh-secret-key-2026")

# Defined Team Users & Passwords
USER_ACCOUNTS = {
    "riaan": {"name": "Riaan Joubert", "pass": os.environ.get("RIAAN_PASSWORD", "riaan2026")},
    "christoff": {"name": "Christoff de Wet", "pass": os.environ.get("CHRISTOFF_PASSWORD", "christoff2026")}
}

def get_db_connection():
    return psycopg2.connect(
        os.environ.get("DATABASE_URL"),
        cursor_factory=RealDictCursor
    )

def get_current_user():
    return session.get("user_fullname")

# --- AUTHENTICATION ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '').strip()

        if username in USER_ACCOUNTS and USER_ACCOUNTS[username]["pass"] == password:
            session['logged_in'] = True
            session['user_id'] = username
            session['user_fullname'] = USER_ACCOUNTS[username]["name"]
            return redirect(url_for('dashboard'))
        else:
            error = "Invalid username or password."
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('dashboard.html', user_name=get_current_user())

@app.route('/pipeline')
def pipeline_page():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('pipeline.html', user_name=get_current_user())

# --- PIPELINE API WITH CLAIM/LOCK STATUS ---
@app.route('/api/sales-pipeline', methods=['GET'])
def get_sales_pipeline():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Retrieves buyers, total spent, phone numbers, matching commodities, and contact tracking status
    query = """
        SELECT 
            h.buyer,
            COUNT(DISTINCT h.id) AS total_orders,
            SUM(h.total) AS total_spent,
            SUM(h.qty) AS total_units,
            p.phone,
            ARRAY_AGG(DISTINCT h.commodity) AS matching_commodities,
            l.contacted_by,
            l.contacted_at
        FROM buyer_history h
        LEFT JOIN buyer_phones p ON UPPER(h.buyer) = UPPER(p.buyer_name)
        LEFT JOIN (
            SELECT DISTINCT ON (buyer) buyer, contacted_by, contacted_at
            FROM buyer_contact_log
            ORDER BY buyer, contacted_at DESC
        ) l ON UPPER(h.buyer) = UPPER(l.buyer)
        GROUP BY h.buyer, p.phone, l.contacted_by, l.contacted_at
        ORDER BY total_spent DESC;
    """
    try:
        cursor.execute(query)
        results = cursor.fetchall()
        pipeline = []
        for row in results:
            commodities = row['matching_commodities'] if row['matching_commodities'] else []
            pipeline.append({
                "buyer": row['buyer'],
                "total_spent": float(row['total_spent'] or 0.0),
                "total_units": int(row['total_units'] or 0),
                "phone": row['phone'] or '',
                "commodities": commodities,
                "contacted_by": row['contacted_by'],
                "contacted_at": row['contacted_at'].strftime('%Y-%m-%d %H:%M') if row['contacted_at'] else None
            })
        cursor.close()
        conn.close()
        return jsonify({"pipeline": pipeline, "current_user": get_current_user()}), 200
    except Exception as e:
        if cursor: cursor.close()
        if conn: conn.close()
        return jsonify({"error": str(e)}), 500

# API to fetch detailed pack/size commodity matches for a specific buyer modal
@app.route('/api/buyer-details/<path:buyer_name>', methods=['GET'])
def get_buyer_details(buyer_name):
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        SELECT commodity, pack, SUM(qty) as total_qty, MAX(date) as last_purchased
        FROM buyer_history
        WHERE UPPER(buyer) = UPPER(%s)
        GROUP BY commodity, pack
        ORDER BY total_qty DESC;
    """
    cursor.execute(query, (buyer_name,))
    matches = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(matches), 200

# API Endpoint to register WhatsApp contact action and lock out buyer
@app.route('/api/mark-contacted', methods=['POST'])
def mark_contacted():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    buyer = data.get('buyer', '').strip()
    user_name = get_current_user()

    if not buyer:
        return jsonify({"error": "Buyer name required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        INSERT INTO buyer_contact_log (buyer, contacted_by)
        VALUES (%s, %s);
    """
    cursor.execute(query, (buyer, user_name))
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"status": "success", "contacted_by": user_name}), 200

# Endpoint to handle slip processing
@app.route('/process-buyer-slip', methods=['POST'])
def process_buyer_slip():
    data = request.get_json() or {}
    parsed_date, buyer = data.get('date'), data.get('buyer', '').strip()
    producer, commodity = data.get('producer', '').strip(), data.get('commodity', '').strip()
    pack, qty = data.get('pack', '').strip(), data.get('qty', 0)
    price, total = data.get('price', 0.0), data.get('total', 0.0)

    if not buyer or not commodity:
        return jsonify({"error": "Missing details"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    query = """
        INSERT INTO buyer_history (date, buyer, producer, commodity, pack, qty, price, total)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (buyer, commodity, pack, qty, price, total) DO NOTHING;
    """
    cursor.execute(query, (parsed_date, buyer, producer, commodity, pack, qty, price, total))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"status": "success"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)