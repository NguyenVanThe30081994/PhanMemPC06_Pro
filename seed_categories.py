# -*- coding: utf-8 -*-
"""
Script tự động tạo danh mục mặc định cho hệ thống PC06.
Chạy một lần để khởi tạo các CategoryGroup và CategoryItem cơ bản.
"""

from app import app
from models import db, CategoryGroup, CategoryItem

# Định nghĩa các nhóm danh mục và các mục mặc định của chúng
DEFAULT_CATEGORIES = {
    # Nhóm danh bạ
    "Nhóm danh bạ": {
        "linked_modules": "Danh bạ",
        "items": [
            "Cán bộ chủ chốt",
            "Cán bộ địa bàn", 
            "Cộng tác viên",
            "Cơ quan ban ngành",
            "Tổ chức xã hội",
            "Doanh nghiệp",
            "Kế hoạch",
            "Ngoại lệ"
        ]
    },
    
    # Chức vụ
    "Chức vụ": {
        "linked_modules": "Danh bạ",
        "items": [
            "Trưởng CA xã",
            "Phó CA xã",
            "Công an viên",
            "Cộng tác viên",
            "Cán bộ địa bàn",
            "Chủ tịch UBND",
            "Phó Chủ tịch UBND",
            "Cán bộ văn phòng",
            "Trưởng phòng",
            "Phó phòng",
            "Chuyên viên",
            "Khác"
        ]
    },
    
    # Lĩnh vực (dùng chung cho Bảng tin, Thư viện, Danh bạ)
    "Lĩnh vực": {
        "linked_modules": "Bảng tin,Thư viện,Danh bạ",
        "items": [
            "An ninh chính trị nội bộ",
            "An ninh kinh tế",
            "An ninh mạng",
            "Trật tự xã hội",
            "Phòng cháy chữa cháy",
            "Giao thông",
            "Cứu nạn cứu hộ",
            "Phòng ngừa tội phạm",
            "Đấu tranh tội phạm",
            "Xây dựng phong trào",
            "Cải cách hành chính",
            "Hợp tác quốc tế",
            "Tuyên truyền pháp luật",
            "Đào tạo bồi dưỡng",
            "Công tác xây dựng lực lượng",
            "Khen thưởng kỷ luật",
            "Quản lý hành chính",
            "Tổng hợp"
        ]
    },
    
    # Đơn vị (phân loại đơn vị)
    "Đơn vị": {
        "linked_modules": "Danh bạ",
        "items": [
            "Phòng PC06",
            "Công an huyện",
            "Công an thị xã",
            "Công an thành phố",
            "Công an xã",
            "Công an phường",
            "Công an thị trấn",
            "UBND xã",
            "UBND phường",
            "UBND thị trấn",
            "Ban Công an xã"
        ]
    },
    
    # Đội nghiệp vụ
    "Đội nghiệp vụ": {
        "linked_modules": "Công việc",
        "items": [
            "Đội An ninh",
            "Đội Trật tự",
            "Đội PC&CC",
            "Đội Giao thông",
            "Đội Cảnh sát hình sự",
            "Đội Cảnh sát kinh tế",
            "Đội Cảnh sát ma túy",
            "Đội Cảnh sát môi trường",
            "Đội Cảnh sát giao thông",
            "Đội Cảnh sát PCCC&CNCH",
            "Phòng Tổng hợp",
            "Phòng Chính trị",
            "Phòng Hậu cần"
        ]
    },
    
    # Loại công việc
    "Loại công việc": {
        "linked_modules": "Công việc",
        "items": [
            "Công việc thường xuyên",
            "Công việc đột xuất",
            "Chỉ đạo điều hành",
            "Đề án dự án",
            "Kế hoạch",
            "Báo cáo",
            "Tổng kết",
            "Kiểm tra",
            "Thanh tra",
            "Phối hợp liên ngành",
            "Hội nghị",
            "Tập huấn",
            "Học tập"
        ]
    },
    
    # Mức độ ưu tiên
    "Mức độ ưu tiên": {
        "linked_modules": "Công việc",
        "items": [
            "Khẩn cấp",
            "Cao",
            "Trung bình",
            "Thấp"
        ]
    },
    
    # Trạng thái công việc
    "Trạng thái công việc": {
        "linked_modules": "Công việc",
        "items": [
            "Chưa bắt đầu",
            "Đang thực hiện",
            "Tạm dừng",
            "Hoàn thành",
            "Quá hạn",
            "Đã hủy"
        ]
    },
    
    # Loại tài liệu
    "Loại tài liệu": {
        "linked_modules": "Thư viện",
        "items": [
            "Văn bản pháp luật",
            "Công văn chỉ đạo",
            "Biểu mẫu",
            "Quy trình quy chế",
            "Tài liệu đào tạo",
            "Tài liệu tham khảo",
            "Báo cáo tổng kết",
            "Kế hoạch",
            "Dự thảo",
            "Khác"
        ]
    }
}


def seed_categories():
    """Tạo tất cả các danh mục mặc định nếu chưa tồn tại."""
    with app.app_context():
        print("🔄 Bắt đầu khởi tạo danh mục mặc định...")
        
        created_groups = 0
        created_items = 0
        
        for group_name, group_data in DEFAULT_CATEGORIES.items():
            # Kiểm tra nhóm đã tồn tại chưa
            group = CategoryGroup.query.filter_by(name=group_name).first()
            
            if not group:
                # Tạo nhóm mới
                group = CategoryGroup(
                    name=group_name,
                    linked_modules=group_data.get("linked_modules", "")
                )
                db.session.add(group)
                db.session.flush()  # Để lấy ID
                created_groups += 1
                print(f"  ✅ Tạo nhóm: {group_name}")
            else:
                print(f"  ⏭️  Nhóm đã tồn tại: {group_name}")
            
            # Tạo các mục trong nhóm
            existing_items = {item.name for item in group.items}
            
            for item_name in group_data.get("items", []):
                if item_name not in existing_items:
                    item = CategoryItem(
                        group_id=group.id,
                        name=item_name
                    )
                    db.session.add(item)
                    created_items += 1
                    print(f"      ➕ Thêm mục: {item_name}")
        
        # Commit tất cả thay đổi
        db.session.commit()
        
        print(f"\n✅ Hoàn thành!")
        print(f"   - Nhóm danh mục mới: {created_groups}")
        print(f"   - Mục danh mục mới: {created_items}")
        print(f"\n📝 Người quản trị có thể vào 'Thiết lập danh mục' để thêm/sửa/xóa các mục.")


if __name__ == "__main__":
    seed_categories()