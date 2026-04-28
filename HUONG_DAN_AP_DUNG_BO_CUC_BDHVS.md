# 🚀 Hướng Dẫn Áp Dụng Bố Cục BDHVS vào PC06

## 📋 Tổng Quan

Tài liệu này hướng dẫn chi tiết cách áp dụng bố cục "đẳng cấp" của BDHVS vào hệ thống PC06.

---

## 📦 Files Đã Tạo

1. ✅ **PHAN_TICH_BO_CUC_BDHVS.md** - Phân tích chi tiết
2. ✅ **static/css/bdhvs-layout.css** - CSS bố cục BDHVS
3. ✅ **templates/demo_bdhvs_layout.html** - Demo HTML

---

## 🎯 Các Bước Áp Dụng

### Bước 1: Thêm CSS vào Base Template

**File: `templates/base.html`**

Thêm vào phần `<head>`:

```html
<!-- BDHVS Layout System -->
<link rel="stylesheet" href="{{ url_for('static', filename='css/bdhvs-layout.css') }}?v=1.0.0">
```

### Bước 2: Áp Dụng Dark Background (Tùy chọn)

**Cách 1: Áp dụng cho toàn bộ trang**

Thêm class vào `<body>`:

```html
<body class="page-dark-hero">
```

**Cách 2: Áp dụng cho một phần cụ thể**

```html
<div class="page-dark-hero" style="min-height: 100vh;">
    <!-- Nội dung trang -->
</div>
```

### Bước 3: Cập Nhật Reporting Index Page

**File: `templates/reporting/index.html`**

**Thay thế phần hero hiện tại:**

```html
<!-- CŨ -->
<div class="reporting-hero">
    <div>
        <h3>Danh sách biểu mẫu báo cáo</h3>
    </div>
    ...
</div>

<!-- MỚI - BDHVS Style -->
<section class="bdhvs-hero">
    <article class="bdhvs-hero-panel">
        <div class="bdhvs-hero-kicker">
            <i class="fa-solid fa-file-circle-check"></i>
            Hệ thống báo cáo thống kê
        </div>
        <h1>Quản lý và theo dõi biểu mẫu báo cáo</h1>
        <p>
            Tập trung tất cả biểu mẫu báo cáo, dữ liệu thống kê và công cụ phân tích tại một nơi. 
            Hệ thống hỗ trợ nhập liệu, xuất Excel, và theo dõi tiến độ theo thời gian thực.
        </p>
        <div class="d-flex flex-wrap gap-2 mt-3">
            <span class="bdhvs-pill"><i class="fa-solid fa-upload"></i> Tải biểu mẫu</span>
            <span class="bdhvs-pill"><i class="fa-solid fa-pen"></i> Nhập liệu</span>
            <span class="bdhvs-pill"><i class="fa-solid fa-file-excel"></i> Xuất Excel</span>
        </div>
    </article>

    <aside class="bdhvs-summary-panel">
        <h2 class="bdhvs-summary-title">Tổng quan hệ thống</h2>
        <div class="bdhvs-summary-stat">
            <span>Biểu mẫu hoạt động</span>
            <strong>{{ templates|length }}</strong>
        </div>
        <div class="bdhvs-summary-stat">
            <span>Đội nghiệp vụ</span>
            <strong>{{ department_dashboard|length }}</strong>
        </div>
        <div class="bdhvs-summary-stat">
            <span>Báo cáo đã nộp</span>
            <strong>{{ total_submissions|default(0) }}</strong>
        </div>
    </aside>
</section>
```

### Bước 4: Cập Nhật Cards

**Thay thế class cards:**

```html
<!-- CŨ -->
<div class="reporting-template-card">
    ...
</div>

<!-- MỚI -->
<div class="bdhvs-card">
    <div class="bdhvs-icon blue">
        <i class="fa-solid fa-file-lines"></i>
    </div>
    <h2 class="bdhvs-heading-md">{{ template.name }}</h2>
    <p>{{ template.description }}</p>
    ...
</div>
```

### Bước 5: Thêm Stats Cards

**Thêm vào đầu trang (sau hero section):**

```html
<div class="row g-3 mb-4">
    <div class="col-6 col-lg-3">
        <div class="bdhvs-stat-card blue">
            <div class="bdhvs-stat-value" style="color: #1A73E8;">{{ templates|length }}</div>
            <div class="bdhvs-stat-label">Biểu mẫu</div>
        </div>
    </div>
    <div class="col-6 col-lg-3">
        <div class="bdhvs-stat-card green">
            <div class="bdhvs-stat-value" style="color: #059669;">{{ total_submissions }}</div>
            <div class="bdhvs-stat-label">Đã nộp</div>
        </div>
    </div>
    <div class="col-6 col-lg-3">
        <div class="bdhvs-stat-card yellow">
            <div class="bdhvs-stat-value" style="color: #D97706;">{{ pending_count }}</div>
            <div class="bdhvs-stat-label">Đang xử lý</div>
        </div>
    </div>
    <div class="col-6 col-lg-3">
        <div class="bdhvs-stat-card blue">
            <div class="bdhvs-stat-value" style="color: #1A73E8;">92%</div>
            <div class="bdhvs-stat-label">Hoàn thành</div>
        </div>
    </div>
</div>
```

---

## 🎨 Tùy Chỉnh Màu Sắc

### Gradient Icons

Có 5 màu gradient có sẵn:

```html
<div class="bdhvs-icon blue">...</div>    <!-- Xanh dương -->
<div class="bdhvs-icon purple">...</div>  <!-- Tím -->
<div class="bdhvs-icon orange">...</div>  <!-- Cam -->
<div class="bdhvs-icon pink">...</div>    <!-- Hồng -->
<div class="bdhvs-icon green">...</div>   <!-- Xanh lá -->
```

### Stats Cards

```html
<div class="bdhvs-stat-card blue">...</div>    <!-- Xanh dương -->
<div class="bdhvs-stat-card green">...</div>   <!-- Xanh lá -->
<div class="bdhvs-stat-card yellow">...</div>  <!-- Vàng -->
<div class="bdhvs-stat-card red">...</div>     <!-- Đỏ -->
```

---

## 📐 Layout Options

### Option 1: Full Dark Background

```html
<body class="page-dark-hero">
    <div class="bdhvs-shell">
        <!-- Nội dung -->
    </div>
</body>
```

### Option 2: Partial Dark Section

```html
<body>
    <!-- Navbar thông thường -->
    
    <div class="page-dark-hero" style="min-height: 60vh;">
        <div class="bdhvs-shell">
            <section class="bdhvs-hero">
                <!-- Hero content -->
            </section>
        </div>
    </div>
    
    <!-- Phần còn lại light background -->
    <div class="container">
        <!-- Content -->
    </div>
</body>
```

### Option 3: Light Background với BDHVS Cards

```html
<body>
    <!-- Giữ background sáng -->
    <div class="container">
        <!-- Chỉ dùng BDHVS cards -->
        <div class="bdhvs-grid">
            <div class="bdhvs-card">...</div>
            <div class="bdhvs-card">...</div>
        </div>
    </div>
</body>
```

---

## 🔧 Utility Classes

### Shadows

```html
<div class="bdhvs-shadow-sm">...</div>  <!-- Shadow nhỏ -->
<div class="bdhvs-shadow-md">...</div>  <!-- Shadow vừa -->
<div class="bdhvs-shadow-lg">...</div>  <!-- Shadow lớn -->
<div class="bdhvs-shadow-xl">...</div>  <!-- Shadow rất lớn -->
```

### Border Radius

```html
<div class="bdhvs-rounded-sm">...</div>   <!-- 16px -->
<div class="bdhvs-rounded-md">...</div>   <!-- 24px -->
<div class="bdhvs-rounded-lg">...</div>   <!-- 32px -->
<div class="bdhvs-rounded-full">...</div> <!-- 999px -->
```

### Glass Panels

```html
<div class="bdhvs-glass-light">...</div>   <!-- Glass sáng -->
<div class="bdhvs-glass-dark">...</div>    <!-- Glass tối -->
<div class="bdhvs-glass-medium">...</div>  <!-- Glass vừa -->
```

---

## 📱 Responsive

Layout tự động responsive:

- **Desktop (>1080px)**: Grid 2 cột
- **Tablet (768px-1080px)**: Grid 1 cột
- **Mobile (<768px)**: Stack vertical, border radius nhỏ hơn

---

## 🎯 Ví Dụ Cụ Thể

### Ví Dụ 1: Reporting Index với Dark Hero

```html
{% extends "base.html" %}

{% block content %}
<div class="page-dark-hero" style="min-height: 100vh;">
    <div class="bdhvs-shell">
        <!-- Hero Section -->
        <section class="bdhvs-hero">
            <article class="bdhvs-hero-panel">
                <div class="bdhvs-hero-kicker">
                    <i class="fa-solid fa-chart-line"></i>
                    {{ templates|length }} biểu mẫu
                </div>
                <h1>Hệ thống Báo cáo PC06</h1>
                <p>Quản lý biểu mẫu, nhập liệu và xuất báo cáo thống kê.</p>
            </article>
            
            <aside class="bdhvs-summary-panel">
                <h2 class="bdhvs-summary-title">Tổng quan</h2>
                <div class="bdhvs-summary-stat">
                    <span>Biểu mẫu</span>
                    <strong>{{ templates|length }}</strong>
                </div>
            </aside>
        </section>

        <!-- Stats -->
        <div class="row g-3 mb-4">
            <div class="col-6 col-lg-3">
                <div class="bdhvs-stat-card blue">
                    <div class="bdhvs-stat-value" style="color: #1A73E8;">12</div>
                    <div class="bdhvs-stat-label">Biểu mẫu</div>
                </div>
            </div>
            <!-- More stats... -->
        </div>

        <!-- Grid Cards -->
        <div class="bdhvs-grid">
            {% for template in templates %}
            <a href="{{ url_for('reporting_bp.template_workspace', template_id=template.id) }}" 
               class="bdhvs-card text-decoration-none">
                <div class="bdhvs-icon blue">
                    <i class="fa-solid fa-file-lines"></i>
                </div>
                <h2 class="bdhvs-heading-md">{{ template.name }}</h2>
                <p style="color: #64748b;">{{ template.description }}</p>
            </a>
            {% endfor %}
        </div>
    </div>
</div>
{% endblock %}
```

### Ví Dụ 2: Dashboard với Light Background

```html
{% extends "base.html" %}

{% block content %}
<div class="container py-4">
    <!-- Stats Cards với BDHVS style -->
    <div class="row g-3 mb-4">
        <div class="col-md-3">
            <div class="bdhvs-stat-card blue">
                <div class="bdhvs-stat-value" style="color: #1A73E8;">156</div>
                <div class="bdhvs-stat-label">Công việc</div>
            </div>
        </div>
        <!-- More stats... -->
    </div>

    <!-- Cards Grid -->
    <div class="bdhvs-grid">
        <div class="bdhvs-card">
            <div class="bdhvs-icon green">
                <i class="fa-solid fa-check"></i>
            </div>
            <h2 class="bdhvs-heading-md">Hoàn thành</h2>
            <p style="color: #64748b;">120 công việc đã hoàn thành</p>
        </div>
        <!-- More cards... -->
    </div>
</div>
{% endblock %}
```

---

## ⚠️ Lưu Ý Quan Trọng

### 1. Dark Background

- Chỉ nên dùng cho landing pages hoặc hero sections
- Không nên dùng cho form nhập liệu (khó đọc)
- Test kỹ với dark mode toggle

### 2. Border Radius

- 32px có thể quá lớn cho một số components nhỏ
- Có thể điều chỉnh xuống 24px nếu cần

### 3. Shadows

- Shadows sâu có thể ảnh hưởng performance trên mobile
- Cân nhắc giảm shadow depth trên mobile

### 4. Font Weights

- Font weight 900 rất đậm, cần font hỗ trợ
- Đảm bảo đã load font Inter hoặc Be Vietnam Pro

---

## 🧪 Testing

### Test Checklist

- [ ] Desktop (1920px)
- [ ] Laptop (1366px)
- [ ] Tablet (768px)
- [ ] Mobile (375px)
- [ ] Dark mode
- [ ] Light mode
- [ ] Safari
- [ ] Chrome
- [ ] Firefox

---

## 🚀 Deployment

### Bước 1: Test Local

```bash
cd /Users/thenguyen/Documents/GitHub/PhanMemPC06_Pro
python app.py
```

Mở: `http://localhost:5000/demo-bdhvs` (nếu đã tạo route)

### Bước 2: Review

- Kiểm tra responsive
- Test dark mode
- Verify performance

### Bước 3: Deploy

- Commit changes
- Push to repository
- Deploy to production

---

## 📊 So Sánh Trước/Sau

### Trước (PC06 Original)

```
- Background: Light (#f1f5f9)
- Cards: Border radius 22px
- Shadow: Nhẹ (0 18px 48px)
- Hover: translateY(-4px)
- Font weight: 700
```

### Sau (BDHVS Style)

```
- Background: Dark gradient (optional)
- Cards: Border radius 32px
- Shadow: Sâu (0 24px 52px)
- Hover: translateY(-6px)
- Font weight: 800-900
```

---

## 💡 Tips & Tricks

### Tip 1: Kết Hợp Cả Hai Styles

Không nhất thiết phải thay thế hoàn toàn. Có thể:
- Dùng dark hero cho landing page
- Giữ light background cho admin pages

### Tip 2: Gradient Icons

Gradient icons rất đẹp nhưng nên dùng có chọn lọc:
- Dùng cho feature cards
- Không dùng cho buttons nhỏ

### Tip 3: Performance

- Minify CSS trước khi deploy
- Lazy load images nếu có
- Test trên mobile thật

---

## 📞 Hỗ Trợ

Nếu gặp vấn đề:

1. Đọc lại `PHAN_TICH_BO_CUC_BDHVS.md`
2. Xem demo tại `templates/demo_bdhvs_layout.html`
3. Check CSS tại `static/css/bdhvs-layout.css`

---

**Chúc bạn áp dụng thành công! 🎉**

*Ngày tạo: 28/04/2026*  
*Version: 1.0.0*
