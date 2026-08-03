import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify, render_template, redirect, url_for, session

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "jdw-fresh-secret-key-2026")

# Set master password for your sales team
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "jdw2026")

def get_db_connection():
    return psycopg2.connect(
        os.environ.get("DATABASE_URL"),
        cursor_factory=RealDictCursor
    )

def is_logged_in():
    return session.get("logged_in") is True

# --- ROUTE 1: LOGIN & LOGOUT ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        password = request.form.get('password')
        if password == DASHBOARD_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        else:
            error = "Invalid Password. Please try again."
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

# --- ROUTE 2: MAIN LANDING DASHBOARD (HUB) ---
@app.route('/')
@app.route('/dashboard')
def dashboard():
    if not is_logged_in():
        return redirect(url_for('login'))
    return render_template('dashboard.html')

# --- ROUTE 3: DEDICATED FUNCTION PAGES ---
@app.route('/pipeline')
def pipeline_page():
    if not is_logged_in():
        return redirect(url_for('login'))
    return render_template('pipeline.html')

@app.route('/contacts')
def contacts_page():
    if not is_logged_in():
        return redirect(url_for('login'))
    return render_template('contacts.html')

# --- API ENDPOINTS ---
@app.route('/api/sales-pipeline', methods=['GET'])
def get_sales_pipeline():
    if not is_logged_in():
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT 
            h.buyer,
            COUNT(DISTINCT h.id) AS total_orders,
            SUM(h.total) AS total_spent,
            SUM(h.qty) AS total_units,
            p.phone,
            ARRAY_AGG(DISTINCT h.commodity) AS matching_commodities
        FROM buyer_history h
        LEFT JOIN buyer_phones p ON UPPER(h.buyer) = UPPER(p.buyer_name)
        GROUP BY h.buyer, p.phone
        ORDER BY total_spent DESC;
    """
    try:
        cursor.execute(query)
        results = cursor.fetchall()
        pipeline = []
        for row in results:
            commodities = row['matching_commodities'] if row['matching_commodities'] else ['ALL PRODUCE']
            pipeline.append({
                "buyer": row['buyer'],
                "total_spent": float(row['total_spent'] or 0.0),
                "total_units": int(row['total_units'] or 0),
                "phone": row['phone'] or '',
                "commodities": commodities
            })
        cursor.close()
        conn.close()
        return jsonify(pipeline), 200
    except Exception as e:
        if cursor: cursor.close()
        if conn: conn.close()
        return jsonify({"error": str(e)}), 500

@app.route('/process-buyer-slip', methods=['POST'])
def process_buyer_slip():
    data = request.get_json() or {}
    parsed_date, buyer = data.get('date'), data.get('buyer', '').strip()
    producer, commodity = data.get('producer', '').strip(), data.get('commodity', '').strip()
    pack, qty = data.get('pack', '').strip(), data.get('qty', 0)
    price, total = data.get('price', 0.0), data.get('total', 0.0)

    if not buyer or not commodity:
        return jsonify({"error": "Missing required details"}), 400

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