import os
import requests

# Your Render app URL
SERVER_URL = "https://jdw-sync.onrender.com"
# CHANGE THIS FOLDER PATH to match what you created on your PC
FOLDER_PATH = r"C:\project jouba\daily_uploads"  

def upload_file(endpoint, file_path):
    filename = os.path.basename(file_path)
    url = f"{SERVER_URL}/{endpoint}"
    try:
        with open(file_path, 'rb') as f:
            files = {'file': f}
            response = requests.post(url, files=files)
            print(f"[{filename}] -> Status {response.status_code}: {response.text}")
    except Exception as e:
        print(f"[{filename}] -> Error: {e}")

if __name__ == "__main__":
    if not os.path.exists(FOLDER_PATH):
        print(f"❌ Folder not found: {FOLDER_PATH}")
    else:
        files = os.listdir(FOLDER_PATH)
        csv_files = [f for f in files if f.endswith('.csv') or f.endswith('.txt')]
        
        if not csv_files:
            print("⚠️ No CSV/TXT files found in daily_uploads folder.")
        else:
            print(f"Found {len(csv_files)} file(s). Starting upload...\n")
            for file in csv_files:
                file_path = os.path.join(FOLDER_PATH, file)
                
                # Check filename to route to stock or floor
                if 'stock' in file.lower():
                    upload_file('upload-stock', file_path)
                elif 'floor' in file.lower():
                    upload_file('upload-floor', file_path)
                else:
                    print(f"Skipped [{file}] (Filename must contain 'stock' or 'floor')")

            print("\n🎉 Upload process finished!")