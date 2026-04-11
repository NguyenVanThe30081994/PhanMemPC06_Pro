import pandas as pd
import os

files = [f for f in os.listdir('.') if 'XẾP HẠNG' in f and f.endswith('.xlsx')]
with open('scratch/excel_structure.txt', 'w', encoding='utf-8') as f:
    if files:
        file_path = files[0]
        f.write(f"Reading file: {file_path}\n")
        try:
            df = pd.read_excel(file_path)
            f.write("Columns found:\n")
            for col in df.columns:
                f.write(f"- {col}\n")
            
            # Print first 2 rows to see data format
            f.write("\nFirst 2 rows:\n")
            f.write(df.head(2).to_string())
        except Exception as e:
            f.write(f"Error: {e}\n")
    else:
        f.write("No ranking file found.\n")
