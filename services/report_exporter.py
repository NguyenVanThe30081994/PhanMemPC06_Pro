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
        from openpyxl.utils.cell import coordinate_to_tuple
        try:
            r_idx, c_idx = coordinate_to_tuple(cell_ref)
        except Exception:
            return cell_ref

        for merged_range in ws.merged_cells.ranges:
            if merged_range.min_row <= r_idx <= merged_range.max_row and \
               merged_range.min_col <= c_idx <= merged_range.max_col:
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

        # Tìm dòng của đơn vị trong file Excel
        from utils import is_unit_match
        import re
        target_row = None
        
        # Quét cột B (cột 2) để tìm tên đơn vị
        for r in range(1, ws.max_row + 1):
            cell_val = ws.cell(row=r, column=2).value
            if cell_val and isinstance(cell_val, str):
                if is_unit_match(cell_val, instance.org_unit):
                    target_row = r
                    break
        
        # Fallback quét cột A (cột 1) nếu không thấy ở cột B
        if not target_row:
            for r in range(1, ws.max_row + 1):
                cell_val = ws.cell(row=r, column=1).value
                if cell_val and isinstance(cell_val, str):
                    if is_unit_match(cell_val, instance.org_unit):
                        target_row = r
                        break

        for field in fields:
            raw_value = values_map.get(field.field_code)
            if raw_value in (None, '') or not field.excel_cell_ref:
                continue

            # Convert sang kiểu số để Excel có thể nhận diện và tự động tính toán các ô công thức
            if field.field_type == 'number' or field.data_type in ['integer', 'decimal']:
                try:
                    raw_str = str(raw_value).replace(',', '') # Xử lý trường hợp có dấu phẩy
                    if '.' in raw_str:
                        raw_value = float(raw_str)
                    else:
                        raw_value = int(raw_str)
                except ValueError:
                    pass

            cell_ref_str = str(field.excel_cell_ref).strip()
            
            # Nếu excel_cell_ref chỉ chứa chữ cái (ví dụ 'C', 'AA'), ta ghép với target_row
            if re.match(r'^[A-Za-z]+$', cell_ref_str):
                if target_row:
                    cell_ref = f"{cell_ref_str}{target_row}"
                else:
                    # Không tìm thấy dòng đơn vị, bỏ qua ghi dữ liệu vào cột này
                    continue
            else:
                cell_ref = cell_ref_str

            target_cell = self._resolve_target_cell(ws, cell_ref)

            try:
                ws[target_cell] = raw_value
            except Exception:
                continue

        output = BytesIO()
        wb.save(output)
        output.seek(0)

        import re
        safe_unit = (instance.org_unit or 'unit')
        safe_unit = re.sub(r'[^A-Za-z0-9._-]+', '_', safe_unit).strip('_') or 'unit'
        filename = f"report_{instance.id}_{safe_unit}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        return output, filename
