"""
Seed script: Tạo dữ liệu mẫu cho CategoryGroup và CategoryItem
Chạy: python seed_categories.py
"""
from app import app, db
from models import CategoryGroup, CategoryItem

def seed_categories():
    with app.app_context():
        print("=== Seeding Category Groups & Items ===")
        
        # 1. Nhóm danh bạ
        group_danhba = CategoryGroup(name='Nhóm danh bạ')
        db.session.add(group_danhba)
        db.session.flush()
        
        danhba_items = ['Công an tỉnh', 'Công an huyện', 'Công an xã', 'UBND tỉnh', 'UBND huyện', 'UBND xã']
        for name in danhba_items:
            db.session.add(CategoryItem(group_id=group_danhba.id, name=name))
        print(f"✓ Created group '{group_danhba.name}' with {len(danhba_items)} items")
        
        # 2. Chức vụ
        group_chucvu = CategoryGroup(name='Chức vụ')
        db.session.add(group_chucvu)
        db.session.flush()
        
        chucvu_items = ['Trưởng phòng', 'Phó trưởng phòng', 'Chỉ huy', 'Đội trưởng', 'Đội phó', 'Cán bộ', 'Chiến sĩ']
        for name in chucvu_items:
            db.session.add(CategoryItem(group_id=group_chucvu.id, name=name))
        print(f"✓ Created group '{group_chucvu.name}' with {len(chucvu_items)} items")
        
        # 3. Đơn vị
        group_donvi = CategoryGroup(name='Đơn vị')
        db.session.add(group_donvi)
        db.session.flush()
        
        donvi_items = ['CA04', 'CA08', 'CA09', 'Công an thành phố', 'Công an các huyện']
        for name in donvi_items:
            db.session.add(CategoryItem(group_id=group_donvi.id, name=name))
        print(f"✓ Created group '{group_donvi.name}' with {len(donvi_items)} items")
        
        # 4. Đội nghiệp vụ
        group_dongnghiepvu = CategoryGroup(name='Đội nghiệp vụ')
        db.session.add(group_dongnghiepvu)
        db.session.flush()
        
        dong_items = ['Đội Cảnh sát Giao thông', 'Đội Cảnh sát Trật tự', 'Đội Cảnh sát Khu vực', 
                    'Đội PCCC & CNCH', 'Đội An ninh', 'Đội Công nghệ cao']
        for name in dong_items:
            db.session.add(CategoryItem(group_id=group_dongnghiepvu.id, name=name))
        print(f"✓ Created group '{group_dongnghiepvu.name}' with {len(dong_items)} items")
        
        # 5. Lĩnh vực
        group_linhvuc = CategoryGroup(name='Lĩnh vực')
        db.session.add(group_linhvuc)
        db.session.flush()
        
        linhvuc_items = ['Hồ sơ phức tạp', 'An ninh trật tự', 'Giao thông', 'PCCC', 'Quản lý hành chính', 
                        'Tiếp dân', 'Khiếu nại tố cáo', 'Tố giác tội phạm']
        for name in linhvuc_items:
            db.session.add(CategoryItem(group_id=group_linhvuc.id, name=name))
        print(f"✓ Created group '{group_linhvuc.name}' with {len(linhvuc_items)} items")
        
        # Save all
        db.session.commit()
        print("\\n=== Seeding complete! ===")
        
        # Verify
        print("\\n=== Verification ===")
        for g in CategoryGroup.query.all():
            count = CategoryItem.query.filter_by(group_id=g.id).count()
            print(f"  {g.name}: {count} items")

if __name__ == '__main__':
    seed_categories()