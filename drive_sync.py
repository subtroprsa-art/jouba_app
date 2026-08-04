import os
import io
import json
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

DATABASE_URL = os.environ.get("DATABASE_URL")

FOLDERS = {
    "floor_raw": "1akYejLRp-bOvdjJEat4Z1XC1frru9j_Y",
    "floor_processed": "1DKEmqlTMJDBfqv9NsGZJYOuCEZWaf6SG",
    "stock_raw": "1DrYmim6xThu6KfKRplr5SDBVZc-BFMBm",
    "stock_processed": "1fLBZHRN9VsR5OfY2eercGPe8BLhVSO2E"
}

SCOPES = ['https://www.googleapis.com/auth/drive']

def get_drive_service():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        info = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        creds = service_account.Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def parse_salesman(filename):
    name = filename.lower()
    if name.startswith("cdw"):
        return "Christoff"
    elif name.startswith("riaa") or name.startswith("riaan"):
        return "Riaan"
    elif name.startswith("pot"):
        return "Pot"
    return "Unassigned"

def move_file(service, file_id, target_folder_id):
    file = service.files().get(file_id=file_id, fields='parents').execute()
    previous_parents = ",".join(file.get('parents', []))
    service.files().update(
        fileId=file_id,
        addParents=target_folder_id,
        removeParents=previous_parents,
        fields='id, parents'
    ).execute()

def process_folder(service, raw_folder_id, processed_folder_id, target_table):
    query = f"'{raw_folder_id}' in parents and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])

    if not files:
        print(f"✨ No new files in folder: {raw_folder_id}")
        return

    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    for file_item in files:
        file_id = file_item['id']
        file_name = file_item['name']
        salesman = parse_salesman(file_name)

        print(f"⚡ Processing {file_name} for {salesman} into {target_table}...")

        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.seek(0)

        # Handle tab-delimited or comma-delimited CSVs
        if file_name.lower().endswith(('.csv', '.txt')):
            try:
                df = pd.read_csv(fh, sep='\t')
                if len(df.columns) <= 1:
                    fh.seek(0)
                    df = pd.read_csv(fh, sep=',')
            except Exception:
                fh.seek(0)
                df = pd.read_csv(fh)
        elif file_name.lower().endswith(('.xls', '.xlsx')):
            df = pd.read_excel(fh)
        else:
            continue

        df.columns = [str(c).strip().upper() for c in df.columns]

        cursor.execute(f"DELETE FROM {target_table} WHERE salesman = %s;", (salesman,))

        records = []
        for idx, row in df.iterrows():
            seq_val = idx + 1
            grn_val = str(row.get('GRN_NO', '')).strip() if pd.notna(row.get('GRN_NO')) else ''
            producer_val = str(row.get('PRODUCER', '')).strip() if pd.notna(row.get('PRODUCER')) else ''

            # Parse composite COMMODITY string ("AVOS,BG150,AH,2,M,*,*")
            comm_raw = str(row.get('COMMODITY', '')) if pd.notna(row.get('COMMODITY')) else ''
            comm_parts = [p.strip() for p in comm_raw.split(',')] if comm_raw else []

            commodity = comm_parts[0] if len(comm_parts) > 0 else comm_raw
            pack      = comm_parts[1] if len(comm_parts) > 1 else str(row.get('PACK', ''))
            variety   = comm_parts[2] if len(comm_parts) > 2 else str(row.get('VARIETY', ''))
            grade     = comm_parts[3] if len(comm_parts) > 3 else str(row.get('GRADE', '1'))
            size      = comm_parts[4] if len(comm_parts) > 4 else str(row.get('SIZE', '*'))
            count     = comm_parts[5] if len(comm_parts) > 5 else str(row.get('COUNT', '*'))

            # Parse quantities cleanly
            def parse_int(val):
                try:
                    return int(float(val)) if pd.notna(val) and str(val).strip() != '' else 0
                except (ValueError, TypeError):
                    return 0

            qty_rec   = parse_int(row.get('QTY_REC', 0))
            qty_sold  = parse_int(row.get('QTY_SOLD', 0))
            qty_floor = parse_int(row.get('QTY_FLOOR', 0))
            
            # Default single qty for floor_records table fallback
            qty = qty_floor if qty_floor > 0 else (qty_rec - qty_sold)

            records.append((
                seq_val, salesman, grn_val, producer_val, 
                commodity, pack, variety, grade, size, count, 
                qty, qty_rec, qty_sold, qty_floor
            ))

        if records:
            insert_query = f"""
                INSERT INTO {target_table} 
                (seq_nr, salesman, grn, producer, commodity, pack, variety, grade, size, count, qty, qty_rec, qty_sold, qty_floor, intake_date)
                VALUES %s;
            """
            # Append CURRENT_DATE to each record row
            records_with_date = [r + (pd.Timestamp.now().date(),) for r in records]
            execute_values(cursor, insert_query, records_with_date)

        conn.commit()
        print(f"✅ Imported {len(records)} rows for {salesman}.")
        move_file(service, file_id, processed_folder_id)

    cursor.close()
    conn.close()

def run_sync():
    service = get_drive_service()
    process_folder(service, FOLDERS["floor_raw"], FOLDERS["floor_processed"], "floor_records")
    process_folder(service, FOLDERS["stock_raw"], FOLDERS["stock_processed"], "stock_records")

if __name__ == "__main__":
    run_sync()