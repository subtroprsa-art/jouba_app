import os
import io
import json
import pandas as pd
import psycopg2
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

        if file_name.lower().endswith('.csv'):
            df = pd.read_csv(fh)
        elif file_name.lower().endswith(('.xls', '.xlsx')):
            df = pd.read_excel(fh)
        else:
            continue

        df.columns = [str(c).strip().lower() for c in df.columns]

        cursor.execute(f"DELETE FROM {target_table} WHERE salesman = %s;", (salesman,))

        inserted_count = 0
        for idx, row in df.iterrows():
            seq_val = idx + 1
            farmer_val, comm_val, var_val, size_val, pack_val, qty_val = "", "", "", "", "", 0

            for col in df.columns:
                val = str(row[col]) if pd.notna(row[col]) else ""
                if "seq" in col:
                    try: seq_val = int(row[col])
                    except: pass
                if "producer" in col or "farmer" in col: farmer_val = val
                if "commodity" in col: comm_val = val
                if "variety" in col: var_val = val
                if "size" in col: size_val = val
                if "pack" in col: pack_val = val
                if "qty" in col or "quantity" in col:
                    try: qty_val = int(row[col])
                    except: qty_val = 0

            cursor.execute(f"""
                INSERT INTO {target_table} 
                (seq_nr, salesman, producer, commodity, variety, size, pack, qty, intake_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_DATE);
            """, (seq_val, salesman, farmer_val, comm_val, var_val, size_val, pack_val, qty_val))
            inserted_count += 1

        conn.commit()
        print(f"✅ Imported {inserted_count} rows for {salesman}.")
        move_file(service, file_id, processed_folder_id)

    cursor.close()
    conn.close()

def run_sync():
    service = get_drive_service()
    process_folder(service, FOLDERS["floor_raw"], FOLDERS["floor_processed"], "floor_records")
    process_folder(service, FOLDERS["stock_raw"], FOLDERS["stock_processed"], "stock_records")

if __name__ == "__main__":
    run_sync()