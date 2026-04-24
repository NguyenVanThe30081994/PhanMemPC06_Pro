#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Migration Script: Tạo bảng cho hệ thống nhập liệu báo cáo mới
Chạy script này để tạo schema database cho reporting system
"""
import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from models_reporting import db, ReportingPeriod, FormTemplate, FormVersion, FormField, ValidationRule, ReportInstance, ReportFieldValue, ReportAuditLog, ReportAttachment

def create_reporting_tables():
    """Tạo tất cả bảng cho reporting system"""
    print("=" * 60)
    print("MIGRATION: Tạo bảng hệ thống nhập liệu báo cáo mới")
    print("=" * 60)
    
    with app.app_context():
        try:
            # Import models để SQLAlchemy biết
            from models_reporting import (
                ReportingPeriod, FormTemplate, FormVersion, FormField,
                ValidationRule, ReportInstance, ReportFieldValue,
                ReportAuditLog, ReportAttachment
            )
            
            # Tạo tất cả bảng
            print("\n📦 Đang tạo bảng...")
            db.create_all()
            
            print("\n✅ Đã tạo các bảng:")
            print("   - reporting_period (Kỳ báo cáo)")
            print("   - form_template (Mẫu biểu)")
            print("   - form_version (Phiên bản mẫu)")
            print("   - form_field (Định nghĩa trường)")
            print("   - validation_rule (Quy tắc kiểm tra)")
            print("   - report_instance (Báo cáo instance)")
            print("   - report_field_value (Giá trị trường)")
            print("   - report_audit_log (Audit trail)")
            print("   - report_attachment (File đính kèm)")
            
            print("\n✨ Migration hoàn thành!")
            print("\nBước tiếp theo:")
            print("1. Chạy seed_reporting_data.py để tạo dữ liệu mẫu")
            print("2. Khởi động server và truy cập /reporting")
            
            return True
            
        except Exception as e:
            print(f"\n❌ Lỗi khi tạo bảng: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

if __name__ == '__main__':
    success = create_reporting_tables()
    sys.exit(0 if success else 1)
