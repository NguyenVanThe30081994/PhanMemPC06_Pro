# -*- coding: utf-8 -*-
"""Xóa toàn bộ CategoryItem và tạo mới cho các popup"""

from app import app, db
from models import CategoryItem, CategoryGroup

def reset_categories():
    with app.app_context():
        # Xóa tất cả CategoryItem
        db.session.query(CategoryItem).delete()
        db.session.commit()
        print("Da xoa tat ca CategoryItem")
        
        # Create groups (empty, no items)
        group_danhba = CategoryGroup.query.filter_by(name='Nhom danh ba').first()
        if not group_danhba:
            group_danhba = CategoryGroup(name='Nhom danh ba', linked_modules='Danh ba')
            db.session.add(group_danhba)
            print("Created: Nhom danh ba")
        
        group_chucvu = CategoryGroup.query.filter_by(name='Chuc vu').first()
        if not group_chucvu:
            group_chucvu = CategoryGroup(name='Chuc vu', linked_modules='Danh ba')
            db.session.add(group_chucvu)
            print("Created: Chuc vu")
        
        group_donvi = CategoryGroup.query.filter_by(name='Don vi').first()
        if not group_donvi:
            group_donvi = CategoryGroup(name='Don vi', linked_modules='Cong viec')
            db.session.add(group_donvi)
            print("Created: Don vi")
        
        # Add: Dong nghiep vu (Tasks)
        group_dongnghiepvu = CategoryGroup.query.filter_by(name='Dong nghiep vu').first()
        if not group_dongnghiepvu:
            group_dongnghiepvu = CategoryGroup(name='Dong nghiep vu', linked_modules='Cong viec,Bang tin,Thu vien')
            db.session.add(group_dongnghiepvu)
            print("Created: Dong nghiep vu")
        
        # Add: Linh vuc (News/Library)
        group_linhvuc = CategoryGroup.query.filter_by(name='Linh vuc').first()
        if not group_linhvuc:
            group_linhvuc = CategoryGroup(name='Linh vuc', linked_modules='Bang tin,Thu vien')
            db.session.add(group_linhvuc)
            print("Created: Linh vuc")
        
        db.session.commit()
        print("Done: 5 groups created!")

if __name__ == '__main__':
    reset_categories()
