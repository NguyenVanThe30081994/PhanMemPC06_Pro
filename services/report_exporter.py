# -*- coding: utf-8 -*-
"""
Report Exporter
Xuất dữ liệu báo cáo ra Excel từ template đã lưu trong DB.
"""
import os
import tempfile
from datetime import datetime
from openpyxl import load_workbook, Workbook

from models_reporting import ReportInstance, FormField


class ReportExporter:
    """Xuất báo cáo ra Excel"""

    @staticmethod
    def _resolve_target_cell(ws, cell_ref):
        """Nếu ô nằm trong merged range (không phải top-left) thì chuyển về top-left để tránh lỗi ghi."""
        for merged_range in ws.merged_cells.ranges:
            if cell_ref in merged_range:
                return merged_range.start_cell.coordinate
        return cell_ref

    def export_to_excel(self, instance_id):
        instance = ReportInstance.query.get(instance_id)
        if not instance:
            raise ValueError(f"Report instance {instance_id} không tồn tại")

        values_map = {fv.field_code: fv.value for fv in instance.field_values}
        fields = FormField.query.filter_by(version_id=instance.version_id).all()

        # Tạo workbook từ blob template nếu có, nếu không thì tạo workbook mới
        if instance.template.excel_template_blob:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_template:
                tmp_template.write(instance.template.excel_template_blob)
                tmp_template.flush()
                wb = load_workbook(tmp_template.name)
            os.unlink(tmp_template.name)
        else:
            wb = Workbook()

        ws = wb.active

        # Ghi metadata cơ bản vào vùng an toàn
        ws['A1'] = 'BÁO CÁO XUẤT TỪ HỆ THỐNG'
        ws['A2'] = f'Đơn vị: {instance.org_unit}'
        ws['A3'] = f'Kỳ báo cáo: {instance.period.name}'
        ws['A4'] = f'Trạng thái: {instance.status}'
        ws['A5'] = f'Xuất lúc: {datetime.now().strftime("%d/%m/%Y %H:%M:%S")}'

        # Fill theo mapping excel_cell_ref (seed hiện tại đang dùng ký tự cột C..W)
        for field in fields:
            raw_value = values_map.get(field.field_code)
            if raw_value in (None, ''):
                continue

            if not field.excel_cell_ref:
                continue

            cell_ref = str(field.excel_cell_ref).strip()
            if any(char.isdigit() for char in cell_ref):
                target_cell = cell_ref
            else:
                target_cell = f"{cell_ref}12"

            # Tránh lỗi khi target_cell nằm trong merged cell không phải ô gốc
            target_cell = self._resolve_target_cell(ws, target_cell)

            try:
                ws[target_cell] = raw_value
            except Exception:
                # Nếu vẫn lỗi thì bỏ qua trường để không làm hỏng toàn bộ export
                continue

        # Ghi thêm sheet dữ liệu chi tiết để dễ kiểm tra
        if 'DuLieuHeThong' in wb.sheetnames:
            del wb['DuLieuHeThong']
        detail_ws = wb.create_sheet('DuLieuHeThong')
        detail_ws.append(['Mã trường', 'Tên trường', 'Giá trị'])
        for field in sorted(fields, key=lambda x: x.display_order or 0):
            detail_ws.append([
                field.field_code,
                field.field_name,
                values_map.get(field.field_code, '')
            ])

        safe_unit = (instance.org_unit or 'unit').replace(' ', '_')
        filename = f"report_{instance.id}_{safe_unit}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        output_path = os.path.join(tempfile.gettempdir(), filename)
        wb.save(output_path)
        return output_path
