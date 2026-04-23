#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Seed dữ liệu mẫu cho hệ thống nhập liệu báo cáo
Tạo template từ file Excel "Báo cáo ngày đất đai.xlsx"
"""
import sys
import os
import json
from datetime import datetime, date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from models_reporting import db, ReportingPeriod, FormTemplate, FormVersion, FormField
import openpyxl

db.init_app(app)

def seed_reporting_data():
    """Seed dữ liệu mẫu"""
    print("=" * 60)
    print("SEED: Tạo dữ liệu mẫu cho hệ thống báo cáo")
    print("=" * 60)
    
    with app.app_context():
        try:
            # 1. Tạo kỳ báo cáo mẫu
            print("\n📅 Tạo kỳ báo cáo...")
            periods = []
            
            # Kỳ hiện tại (tháng này)
            today = date.today()
            period_code = today.strftime("%Y-%m")
            period = ReportingPeriod.query.filter_by(code=period_code).first()
            if not period:
                period = ReportingPeriod(
                    code=period_code,
                    name=f"Tháng {today.month} năm {today.year}",
                    period_type='monthly',
                    start_date=date(today.year, today.month, 1),
                    end_date=date(today.year, today.month, 28),  # Simplified
                    deadline=datetime(today.year, today.month, 28, 17, 0, 0),
                    is_locked=False,
                    created_by=1
                )
                db.session.add(period)
                periods.append(period)
                print(f"   ✓ Tạo kỳ: {period.name}")
            
            db.session.commit()
            
            # 2. Tạo mẫu biểu từ Excel
            print("\n📋 Tạo mẫu biểu từ Excel...")
            excel_path = os.path.join(os.path.dirname(__file__), 'Báo cáo ngày đất đai.xlsx')
            
            if not os.path.exists(excel_path):
                print(f"   ⚠️  Không tìm thấy file: {excel_path}")
                return False
            
            # Đọc file Excel
            with open(excel_path, 'rb') as f:
                excel_blob = f.read()
            
            # Parse Excel structure
            wb = openpyxl.load_workbook(excel_path, data_only=False)
            ws = wb.active
            
            # Tạo template
            template = FormTemplate.query.filter_by(code='BAO_CAO_DAT_DAI').first()
            if not template:
                template = FormTemplate(
                    code='BAO_CAO_DAT_DAI',
                    name='Báo cáo ngày đất đai',
                    description='Tổng hợp kết quả và nhu cầu khối lượng thực hiện đo đạc lập bản đồ địa chính, cấp GCN và xây dựng CSDL đất đai',
                    category='Đất đai',
                    excel_template_blob=excel_blob,
                    is_active=True,
                    created_by=1
                )
                db.session.add(template)
                db.session.flush()
                print(f"   ✓ Tạo template: {template.name}")
            
            # 3. Tạo version
            version = FormVersion.query.filter_by(template_id=template.id, version_number='v1.0').first()
            if not version:
                # Parse metadata từ Excel
                metadata = {
                    'title': 'Báo cáo ngày đất đai',
                    'header_rows': 10,
                    'data_start_row': 11,
                    'sections': [
                        {
                            'name': 'Lưới địa chính',
                            'columns': ['C', 'D', 'E']
                        },
                        {
                            'name': 'Đo đạc lập mới bản đồ địa chính',
                            'columns': ['F', 'G', 'H']
                        },
                        {
                            'name': 'Đo đạc chỉnh lý bản đồ địa chính',
                            'columns': ['I', 'J', 'K']
                        },
                        {
                            'name': 'Cấp mới GCN',
                            'columns': ['L', 'M', 'N']
                        },
                        {
                            'name': 'Cấp đổi GCN',
                            'columns': ['O', 'P', 'Q']
                        },
                        {
                            'name': 'Xây dựng mới CSDL',
                            'columns': ['R', 'S', 'T']
                        },
                        {
                            'name': 'Hoàn thiện CSDL',
                            'columns': ['U', 'V', 'W']
                        }
                    ]
                }
                
                version = FormVersion(
                    template_id=template.id,
                    version_number='v1.0',
                    metadata_json=json.dumps(metadata, ensure_ascii=False),
                    is_published=True,
                    effective_from=date.today(),
                    created_by=1
                )
                db.session.add(version)
                db.session.flush()
                print(f"   ✓ Tạo version: {version.version_number}")
            
            # 4. Tạo fields
            print("\n📝 Tạo định nghĩa trường...")
            
            # Danh sách fields theo cấu trúc Excel
            fields_config = [
                # Lưới địa chính
                {'code': 'luoi_chi_tieu', 'name': 'Lưới địa chính - Chỉ tiêu', 'type': 'number', 'section': 'Lưới địa chính', 'cell': 'C', 'order': 1},
                {'code': 'luoi_ket_qua', 'name': 'Lưới địa chính - Kết quả ngày', 'type': 'number', 'section': 'Lưới địa chính', 'cell': 'D', 'order': 2},
                {'code': 'luoi_ti_le', 'name': 'Lưới địa chính - Tỉ lệ hoàn thành', 'type': 'number', 'section': 'Lưới địa chính', 'cell': 'E', 'order': 3, 'calculated': True, 'formula': '(luoi_ket_qua / luoi_chi_tieu) * 100'},
                
                # Đo đạc lập mới
                {'code': 'do_dac_moi_chi_tieu', 'name': 'Đo đạc lập mới - Chỉ tiêu (ha)', 'type': 'number', 'section': 'Đo đạc lập mới', 'cell': 'F', 'order': 4},
                {'code': 'do_dac_moi_ket_qua', 'name': 'Đo đạc lập mới - Kết quả ngày (ha)', 'type': 'number', 'section': 'Đo đạc lập mới', 'cell': 'G', 'order': 5},
                {'code': 'do_dac_moi_ti_le', 'name': 'Đo đạc lập mới - Tỉ lệ hoàn thành', 'type': 'number', 'section': 'Đo đạc lập mới', 'cell': 'H', 'order': 6, 'calculated': True, 'formula': '(do_dac_moi_ket_qua / do_dac_moi_chi_tieu) * 100'},
                
                # Đo đạc chỉnh lý
                {'code': 'chinh_ly_chi_tieu', 'name': 'Đo đạc chỉnh lý - Chỉ tiêu (ha/thửa)', 'type': 'number', 'section': 'Đo đạc chỉnh lý', 'cell': 'I', 'order': 7},
                {'code': 'chinh_ly_ket_qua', 'name': 'Đo đạc chỉnh lý - Kết quả ngày (ha/thửa)', 'type': 'number', 'section': 'Đo đạc chỉnh lý', 'cell': 'J', 'order': 8},
                {'code': 'chinh_ly_ti_le', 'name': 'Đo đạc chỉnh lý - Tỉ lệ hoàn thành', 'type': 'number', 'section': 'Đo đạc chỉnh lý', 'cell': 'K', 'order': 9, 'calculated': True, 'formula': '(chinh_ly_ket_qua / chinh_ly_chi_tieu) * 100'},
                
                # Cấp mới GCN
                {'code': 'cap_moi_chi_tieu', 'name': 'Cấp mới GCN - Chỉ tiêu (số thửa)', 'type': 'number', 'section': 'Cấp mới GCN', 'cell': 'L', 'order': 10},
                {'code': 'cap_moi_ket_qua', 'name': 'Cấp mới GCN - Kết quả ngày (số thửa)', 'type': 'number', 'section': 'Cấp mới GCN', 'cell': 'M', 'order': 11},
                {'code': 'cap_moi_ti_le', 'name': 'Cấp mới GCN - Tỉ lệ hoàn thành', 'type': 'number', 'section': 'Cấp mới GCN', 'cell': 'N', 'order': 12, 'calculated': True, 'formula': '(cap_moi_ket_qua / cap_moi_chi_tieu) * 100'},
                
                # Cấp đổi GCN
                {'code': 'cap_doi_chi_tieu', 'name': 'Cấp đổi GCN - Chỉ tiêu (số thửa)', 'type': 'number', 'section': 'Cấp đổi GCN', 'cell': 'O', 'order': 13},
                {'code': 'cap_doi_ket_qua', 'name': 'Cấp đổi GCN - Kết quả ngày (số thửa)', 'type': 'number', 'section': 'Cấp đổi GCN', 'cell': 'P', 'order': 14},
                {'code': 'cap_doi_ti_le', 'name': 'Cấp đổi GCN - Tỉ lệ hoàn thành', 'type': 'number', 'section': 'Cấp đổi GCN', 'cell': 'Q', 'order': 15, 'calculated': True, 'formula': '(cap_doi_ket_qua / cap_doi_chi_tieu) * 100'},
                
                # Xây dựng mới CSDL
                {'code': 'xd_moi_chi_tieu', 'name': 'Xây dựng mới CSDL - Chỉ tiêu', 'type': 'number', 'section': 'Xây dựng mới CSDL', 'cell': 'R', 'order': 16},
                {'code': 'xd_moi_ket_qua', 'name': 'Xây dựng mới CSDL - Kết quả ngày', 'type': 'number', 'section': 'Xây dựng mới CSDL', 'cell': 'S', 'order': 17},
                {'code': 'xd_moi_ti_le', 'name': 'Xây dựng mới CSDL - Tỉ lệ hoàn thành', 'type': 'number', 'section': 'Xây dựng mới CSDL', 'cell': 'T', 'order': 18, 'calculated': True, 'formula': '(xd_moi_ket_qua / xd_moi_chi_tieu) * 100'},
                
                # Hoàn thiện CSDL
                {'code': 'hoan_thien_chi_tieu', 'name': 'Hoàn thiện CSDL - Chỉ tiêu', 'type': 'number', 'section': 'Hoàn thiện CSDL', 'cell': 'U', 'order': 19},
                {'code': 'hoan_thien_ket_qua', 'name': 'Hoàn thiện CSDL - Kết quả ngày', 'type': 'number', 'section': 'Hoàn thiện CSDL', 'cell': 'V', 'order': 20},
                {'code': 'hoan_thien_ti_le', 'name': 'Hoàn thiện CSDL - Tỉ lệ hoàn thành', 'type': 'number', 'section': 'Hoàn thiện CSDL', 'cell': 'W', 'order': 21, 'calculated': True, 'formula': '(hoan_thien_ket_qua / hoan_thien_chi_tieu) * 100'},
            ]
            
            for field_cfg in fields_config:
                field = FormField.query.filter_by(
                    version_id=version.id,
                    field_code=field_cfg['code']
                ).first()
                
                if not field:
                    field = FormField(
                        version_id=version.id,
                        field_code=field_cfg['code'],
                        field_name=field_cfg['name'],
                        field_type=field_cfg['type'],
                        data_type='decimal',
                        is_required=False,
                        is_readonly=field_cfg.get('calculated', False),
                        is_calculated=field_cfg.get('calculated', False),
                        calculation_formula=field_cfg.get('formula'),
                        display_order=field_cfg['order'],
                        section=field_cfg['section'],
                        excel_cell_ref=field_cfg['cell']
                    )
                    db.session.add(field)
            
            db.session.commit()
            print(f"   ✓ Đã tạo {len(fields_config)} trường dữ liệu")
            
            print("\n✨ Seed dữ liệu hoàn thành!")
            print("\nDữ liệu đã tạo:")
            print(f"   - {len(periods)} kỳ báo cáo")
            print(f"   - 1 mẫu biểu: {template.name}")
            print(f"   - 1 phiên bản: {version.version_number}")
            print(f"   - {len(fields_config)} trường dữ liệu")
            
            print("\nBước tiếp theo:")
            print("1. Khởi động server: python app.py")
            print("2. Truy cập: http://localhost:5000/reporting")
            
            return True
            
        except Exception as e:
            print(f"\n❌ Lỗi: {str(e)}")
            import traceback
            traceback.print_exc()
            db.session.rollback()
            return False

if __name__ == '__main__':
    success = seed_reporting_data()
    sys.exit(0 if success else 1)
