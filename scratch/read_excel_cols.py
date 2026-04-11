import pandas as pd
import os

files = [f for f in os.listdir('.') if 'XẾP HẠNG' in f and f.endswith('.xlsx')]
if files:
    file_path = files[0]
    print(f"Reading file: {file_path}")
    try:
        df = pd.read_excel(file_path)
        print("Columns found:")
        for col in df.columns:
            print(f"- {col}")
    except Exception as e:
        print(f"Error: {e}")
else:
    print("No ranking file found.")
