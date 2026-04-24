# -*- coding: utf-8 -*-
"""
Report Exporter
Xuất dữ liệu báo cáo ra Excel từ template đã lưu trong DB.
"""
from io import BytesIO
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

    def export_to_excel_bytes(self, instance_id):
        instance = ReportInstance.query.get(instance_id)
        if not instance:
            raise ValueError(f"Report instance {instance_id} không tồn tại")

        values_map = {fv.field_code: fv.value for fv in instance.field_values}
        fields = FormField.query.filter_by(version_id=instance.version_id).all()

        # Load workbook từ blob template hoặc tạo mới
        if instance.template.excel_template_blob:
            wb = load_workbook(BytesIO(instance.template.excel_template_blob))
        else:
            wb = Workbook()

        ws = wb.active

        for field in fields:
            raw_value = values_map.get(field.field_code)
            if raw_value in (None, '') or not field.excel_cell_ref:
                continue

            cell_ref = str(field.excel_cell_ref).strip()
            target_cell = cell_ref if any(char.isdigit() for char in cell_ref) else f"{cell_ref}12"
            target_cell = self._resolve_target_cell(ws, target_cell)

            try:
                ws[target_cell] = raw_value
            except Exception:
                continue

        output = BytesIO()
        wb.save(output)
        output.seek(0)

        safe_unit = (instance.org_unit or 'unit').replace(' ', '_')
        filename = f"report_{instance.id}_{safe_unit}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        return output, filename
