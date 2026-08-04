@app.route('/api/inventory/<inv_type>', methods=['GET'])
def get_inventory_data(inv_type):
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401

    table_name = "stock_records" if inv_type == "stock" else "floor_records"
    conn = get_db_connection()
    cursor = conn.cursor()

    # Sort floor balance by Sequence Number, stock by Age
    order_clause = "seq_nr ASC NULLS LAST, age_days DESC" if inv_type == "floor" else "salesman, age_days DESC"

    query = f"""
        SELECT 
            COALESCE(seq_nr, 0) AS seq_nr,
            COALESCE(NULLIF(salesman, ''), 'Unassigned') AS salesman,
            COALESCE(producer, farmer_name, '') AS farmer_name,
            COALESCE(commodity, '') AS commodity,
            COALESCE(variety, '') AS variety,
            COALESCE(size, '') AS size,
            COALESCE(pack_weight, pack, '') AS pack_weight,
            COALESCE(qty, 0) AS qty,
            intake_date,
            CASE 
                WHEN intake_date IS NOT NULL THEN (CURRENT_DATE - intake_date)
                ELSE 0 
            END AS age_days
        FROM {table_name}
        ORDER BY {order_clause};
    """
    try:
        cursor.execute(query)
        rows = cursor.fetchall()

        salesmen_data = {}
        for r in rows:
            sm = r['salesman']
            if sm not in salesmen_data:
                salesmen_data[sm] = []
            
            salesmen_data[sm].append({
                "seq_nr": r['seq_nr'],
                "farmer": r['farmer_name'],
                "commodity": r['commodity'],
                "variety": r['variety'],
                "size": r['size'],
                "pack_weight": r['pack_weight'],
                "qty": r['qty'],
                "intake_date": r['intake_date'].strftime('%Y-%m-%d') if r['intake_date'] else 'N/A',
                "age_days": r['age_days']
            })

        cursor.close()
        conn.close()
        return jsonify({"inventory": salesmen_data}), 200
    except Exception as e:
        if cursor: cursor.close()
        if conn: conn.close()
        return jsonify({"error": str(e)}), 500