import sys
import os

file_path = r'c:\Users\THE\Downloads\PhanMemPC06_Pro\static\css\style.css'

def update_css(content, mode='append'):
    with open(file_path, 'r', encoding='utf-8') as f:
        original = f.read()
    
    if mode == 'append':
        if content in original:
            print("Content already exists.")
            return
        with open(file_path, 'a', encoding='utf-8') as f:
            f.write(content)
        print("CSS appended.")
    else:
        # For full cleanup/replace if needed
        pass

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Collect all args as content
        new_css = " ".join(sys.argv[1:])
        update_css(new_css)
