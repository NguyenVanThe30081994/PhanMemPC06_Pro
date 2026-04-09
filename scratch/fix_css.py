import os

file_path = r'c:\Users\THE\Downloads\PhanMemPC06_Pro\static\css\style.css'

with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Truncate at line 1577 (index 1576)
clean_lines = lines[:1577]

new_content = """
/* Global Dropdown Consistency */
.dropdown-menu {
    border-radius: 16px !important;
    overflow: hidden;
    border: 1px solid var(--border) !important;
    box-shadow: var(--shadow-lg) !important;
    backdrop-filter: blur(10px);
}

@media print {
    .top-navbar, .sidebar, .mobile-bottom-nav, .offcanvas, .no-print, .btn, .breadcrumb {
        display: none !important;
    }
    .main-content-area {
        margin: 0 !important;
        padding: 0 !important;
    }
    body {
        padding-top: 0 !important;
    }
}
"""

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(clean_lines)
    f.write(new_content)

print("CSS cleaned and updated successfully.")
