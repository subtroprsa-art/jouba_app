import pandas as pd

# Change this to the EXACT path of your today's floor file
file_path = r"C:\project jouba\daily_uploads\cdwfloor13082026.csv"

try:
    # Try reading as tab-delimited first
    df = pd.read_csv(file_path, delimiter='\t')
    if len(df.columns) <= 1:
        # If that fails, try comma-delimited
        df = pd.read_csv(file_path, delimiter=',')
        
    print("✅ File read successfully!")
    print(f"📌 Found {len(df.columns)} columns.")
    
    print("\n📌 EXACT COLUMN NAMES:")
    for i, col in enumerate(df.columns):
        print(f"  {i+1}: '{col}'")
        
    # Check for farmer name columns
    print("\n🔍 Checking for farmer name column:")
    possible_columns = ['WHOLESALER', 'PROD', 'PRODUCER', 'wholesaler', 'prod', 'producer']
    found = False
    for col in possible_columns:
        if col in df.columns:
            print(f"  ✅ Found: '{col}'")
            print(f"  📊 First value: '{df[col].iloc[0]}'")
            found = True
            break
            
    if not found:
        print("  ❌ No farmer name column found!")
        print("  📌 All columns found:", list(df.columns))
        
except Exception as e:
    print(f"❌ Error: {e}")