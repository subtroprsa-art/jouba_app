import requests

BOT_TOKEN = "PASTE_YOUR_BOT_TOKEN_HERE"  # Replace with your actual token

print("1. Testing basic Python...")

try:
    print("2. Testing connection to Telegram...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
    response = requests.get(url, timeout=10)
    
    print(f"3. Status Code: {response.status_code}")
    print(f"4. Response Text: {response.text}")
    
except Exception as e:
    print(f"5. CRASHED WITH ERROR: {e}")
    import traceback
    traceback.print_exc()

print("6. Test finished.")