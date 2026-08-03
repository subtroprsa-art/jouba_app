import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

# Database connection helper
def get_db_connection():
    conn = psycopg2.connect(
        os.environ.get("DATABASE_URL"),
        cursor_factory=RealDictCursor
    )
    return conn

@app.route('/')
def home():
    return render_template('index.html')

# Endpoint 1: Direct sync of buyer contacts (Phone mapping)
@app.route('/update-buyer-phone', methods=['POST'])
def update_buyer_phone():
    data = request.get_json() or {}
    buyer_name = data.get('buyer_name', '').strip()
    phone_number = data.get('phone_number', '').strip()

    if not buyer_name or not phone_number:
        return jsonify({"error": "buyer_name and phone_number required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        INSERT INTO buyer_phones (buyer_name, phone_number)
        VALUES (%s, %s)
        ON CONFLICT (buyer_name) 
        DO UPDATE SET phone_number = EXCLUDED.phone_number;
    """
    cursor.execute(query, (buyer_name, phone_number))
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"status": "success", "message": f"Updated phone for {buyer_name}"}), 200

# Endpoint 2: Upload buyer history slips (Handles duplicates safely)
@app.route('/process-buyer-slip', methods=['POST'])
def process_buyer_slip():
    data = request.get_json() or {}
    
    parsed_date = data.get('date')
    buyer = data.get('buyer', '').strip()
    producer = data.get('producer', '').strip()
    commodity = data.get('commodity', '').strip()
    pack = data.get('pack', '').strip()
    qty = data.get('qty', 0)
    price = data.get('price', 0.0)
    total = data.get('total', 0.0)

    if not buyer or not commodity:
        return jsonify({"error": "Missing required slip details"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # ON CONFLICT prevents 500 crashes when unique constraint is triggered
    query = """
        INSERT INTO buyer_history (date, buyer, producer, commodity, pack, qty, price, total)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (buyer, commodity, pack, qty, price, total) 
        DO NOTHING;
    """
    cursor.execute(query, (parsed_date, buyer, producer, commodity, pack, qty, price, total))
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"status": "success", "message": "Record processed successfully"}), 200

# Endpoint 3: Pipeline data with multi-commodity matching array
@app.route('/api/sales-pipeline', methods=['GET'])
def get_sales_pipeline():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT 
            h.buyer,
            COUNT(DISTINCT h.id) AS total_orders,
            SUM(h.total) AS total_spent,
            SUM(h.qty) AS total_units,
            p.phone_number,
            ARRAY_AGG(DISTINCT h.commodity) FILTER (
                WHERE h.commodity IN (SELECT DISTINCT commodity FROM active_stock WHERE qty > 0)
            ) AS matching_commodities
        FROM buyer_history h
        LEFT JOIN buyer_phones p ON UPPER(h.buyer) = UPPER(p.buyer_name)
        GROUP BY h.buyer, p.phone_number
        ORDER BY total_spent DESC;
    """
    cursor.execute(query)
    results = cursor.fetchall()
    
    pipeline = []
    for row in results:
        commodities = row['matching_commodities'] if row['matching_commodities'] else ['ALL PRODUCE']
        pipeline.append({
            "buyer": row['buyer'],
            "total_spent": float(row['total_spent'] or 0.0),
            "total_units": int(row['total_units'] or 0),
            "phone": row['phone_number'] or '',
            "commodities": commodities
        })
        
    cursor.close()
    conn.close()
    return jsonify(pipeline), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)