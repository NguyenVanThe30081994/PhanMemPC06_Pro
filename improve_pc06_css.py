# -*- coding: utf-8 -*-
"""
Cải thiện CSS của PC06 dựa trên phân tích BDHVS
KHÔNG thay đổi chức năng, chỉ cải thiện giao diện
"""

# Đọc CSS hiện tại của PC06
with open('static/css/style.css', 'r', encoding='utf-8') as f:
    css = f.read()

# Các cải thiện cần thêm vào đầu file
improvements = """
/* ===== IMPROVEMENTS FROM BDHVS DESIGN ===== */

/* 1. Better CSS Variables */
:root {
    /* Màu sắc cải thiện */
    --primary: #0066FF;
    --primary-light: #4D94FF;
    --primary-gradient: linear-gradient(135deg, #0052CC 0%, #0066FF 100%);
    
    /* Background mượt mà hơn */
    --bg-body: #f1f5f9;
    --bg-surface: #ffffff;
    
    /* Text rõ ràng hơn */
    --text-main: #0f172a;
    --text-muted: #64748b;
    
    /* Shadows đẹp hơn */
    --shadow-sm: 0 1px 2px rgba(0,0,0,0.06);
    --shadow-md: 0 10px 15px -3px rgba(0,0,0,0.08);
    --shadow-lg: 0 20px 25px -5px rgba(0,0,0,0.1);
    --shadow-primary: 0 10px 20px rgba(0, 102, 255, 0.2);
    
    /* Border radius mượt mà */
    --radius-sm: 12px;
    --radius-md: 16px;
    --radius-lg: 24px;
    --radius-full: 100px;
    
    /* Transitions */
    --transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

/* 2. Cải thiện Cards */
.card {
    border-radius: var(--radius-lg) !important;
    box-shadow: var(--shadow-md) !important;
    border: none !important;
    transition: var(--transition) !important;
}

.card:hover {
    transform: translateY(-4px);
    box-shadow: var(--shadow-lg) !important;
}

/* 3. Cải thiện Buttons */
.btn {
    border-radius: var(--radius-sm) !important;
    transition: var(--transition) !important;
    font-weight: 600 !important;
}

.btn:hover {
    transform: scale(1.02);
}

.btn-primary {
    background: var(--primary-gradient) !important;
    border: none !important;
    box-shadow: var(--shadow-primary) !important;
}

.btn-primary:hover {
    box-shadow: 0 12px 24px rgba(0, 102, 255, 0.3) !important;
}

/* 4. Glass Effect cho Header */
.navbar, .page-header {
    background: rgba(255, 255, 255, 0.9) !important;
    backdrop-filter: blur(20px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(20px) saturate(180%) !important;
    border-bottom: 1px solid rgba(0, 0, 0, 0.05) !important;
    box-shadow: var(--shadow-sm) !important;
}

/* 5. Cải thiện Form Inputs */
.form-control, .form-select {
    border-radius: var(--radius-sm) !important;
    border: 1px solid #e2e8f0 !important;
    transition: var(--transition) !important;
}

.form-control:focus, .form-select:focus {
    border-color: var(--primary) !important;
    box-shadow: 0 0 0 3px rgba(0, 102, 255, 0.1) !important;
}

/* 6. Cải thiện Tables */
.table {
    border-radius: var(--radius-md) !important;
    overflow: hidden;
}

.table thead th {
    background: linear-gradient(145deg, #f8fafc, #f1f5f9) !important;
    border: none !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    font-size: 0.75rem !important;
    letter-spacing: 0.5px !important;
    padding: 1rem !important;
}

.table tbody tr {
    transition: var(--transition) !important;
}

.table tbody tr:hover {
    background: rgba(0, 102, 255, 0.02) !important;
    transform: scale(1.01);
}

/* 7. Cải thiện Badges */
.badge {
    border-radius: var(--radius-full) !important;
    padding: 0.5rem 1rem !important;
    font-weight: 600 !important;
}

/* 8. Smooth Scrollbar */
::-webkit-scrollbar {
    width: 8px;
    height: 8px;
}

::-webkit-scrollbar-track {
    background: #f1f5f9;
}

::-webkit-scrollbar-thumb {
    background: #cbd5e1;
    border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
    background: #94a3b8;
}

/* ===== END IMPROVEMENTS ===== */

"""

# Thêm improvements vào đầu CSS
new_css = improvements + "\n" + css

# Ghi lại file
with open('static/css/style.css', 'w', encoding='utf-8') as f:
    f.write(new_css)

print("✓ Đã cải thiện CSS của PC06")
print("  - Thêm CSS variables tốt hơn")
print("  - Cải thiện cards, buttons, forms")
print("  - Thêm glass effect cho header")
print("  - Cải thiện shadows và transitions")
print("  - Giữ nguyên 100% chức năng")
