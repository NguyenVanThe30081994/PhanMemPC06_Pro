# -*- coding: utf-8 -*-
import re

# Đọc file
with open('templates/task_detail.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Tìm và sửa lỗi HTML ở phần báo cáo
# Lỗi: thiếu </form> và </div>, có dấu " thừa
old_pattern = r'''                        <button type="submit" class="btn btn-success btn-lg rounded-pill px-5 fw-bold shadow-sm">
                            <i class="fa-solid fa-paper-plane me-2"></i>GỬI BÁO CÁO
                        </button>" style="border-radius: 24px; background: linear-gradient\(145deg, #ffffff, #f8fafc\); box-shadow: 0 8px 32px rgba\(0,0,0,0\.08\);">
            <div class="card-header border-0 bg-transparent py-4 px-4" style="border-radius: 24px 24px 0 0;">
                <div class="d-flex align-items-center gap-3">
                    <div style="width: 56px; height: 56px; background: linear-gradient\(135deg, #8B5CF6, #7C3AED\); border-radius: 16px; display: flex; align-items: center; justify-content: center; box-shadow: 0 8px 20px rgba\(139,92,246,0\.35\);">
                        <i class="fa-solid fa-comments text-white fs-5"></i>
                    </div>
                    <div>
                        <h5 class="fw-bold mb-0" style="color: #1e293b;">Phản hồi & Thảo luận</h5>
                        <p class="text-muted mb-0 small">Trao đổi và cập nhật tiến độ</p>
                    </div>
                </div'''

new_code = '''                        <button type="submit" class="btn btn-success btn-lg rounded-pill px-5 fw-bold shadow-sm">
                            <i class="fa-solid fa-paper-plane me-2"></i>GỬI BÁO CÁO
                        </button>
                    </div>
                </form>
            </div>
        </div>
        {% endif %}

        <!-- 4. COMMENTS SECTION -->
        <div class="card border-0 mb-4" style="border-radius: 24px; background: linear-gradient(145deg, #ffffff, #f8fafc); box-shadow: 0 8px 32px rgba(0,0,0,0.08);">
            <div class="card-header border-0 bg-transparent py-4 px-4" style="border-radius: 24px 24px 0 0;">
                <div class="d-flex align-items-center gap-3">
                    <div style="width: 56px; height: 56px; background: linear-gradient(135deg, #8B5CF6, #7C3AED); border-radius: 16px; display: flex; align-items: center; justify-content: center; box-shadow: 0 8px 20px rgba(139,92,246,0.35);">
                        <i class="fa-solid fa-comments text-white fs-5"></i>
                    </div>
                    <div>
                        <h5 class="fw-bold mb-0" style="color: #1e293b;">Phản hồi & Thảo luận</h5>
                        <p class="text-muted mb-0 small">Trao đổi và cập nhật tiến độ</p>
                    </div>
                </div'''

# Thay thế
content = re.sub(old_pattern, new_code, content)

# Ghi lại
with open('templates/task_detail.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("✓ Đã sửa lỗi HTML trong task_detail.html")
