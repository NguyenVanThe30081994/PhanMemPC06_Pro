# -*- coding: utf-8 -*-
"""
Form Engine - Xử lý render form và validation
Theo kiến trúc tài liệu: Form Engine + Metadata
"""
import ast
import json
import operator as op
from datetime import datetime
from excel_renderer import format_excel_number
from models_reporting import db, FormTemplate, FormVersion, FormField, ReportInstance, ReportFieldValue, ReportAuditLog, ReportingPeriod
from flask import session


class _SafeFormulaEvaluator(ast.NodeVisitor):
    """Evaluate arithmetic formulas safely without eval()."""

    _bin_ops = {
        ast.Add: op.add,
        ast.Sub: op.sub,
        ast.Mult: op.mul,
        ast.Div: op.truediv,
        ast.FloorDiv: op.floordiv,
        ast.Mod: op.mod,
        ast.Pow: op.pow,
    }
    _unary_ops = {
        ast.UAdd: op.pos,
        ast.USub: op.neg,
    }
    _safe_funcs = {
        'round': round,
        'min': min,
        'max': max,
        'abs': abs,
    }

    def __init__(self, values):
        self.values = values or {}

    def visit_Expression(self, node):
        return self.visit(node.body)

    def visit_Constant(self, node):
        if isinstance(node.value, (int, float, bool)):
            return node.value
        raise ValueError('Unsupported constant type')

    def visit_Name(self, node):
        if node.id not in self.values:
            raise ValueError(f'Unknown field code: {node.id}')
        return self.values[node.id]

    def visit_BinOp(self, node):
        operator = self._bin_ops.get(type(node.op))
        if not operator:
            raise ValueError('Unsupported operator')
        return operator(self.visit(node.left), self.visit(node.right))

    def visit_UnaryOp(self, node):
        operator = self._unary_ops.get(type(node.op))
        if not operator:
            raise ValueError('Unsupported unary operator')
        return operator(self.visit(node.operand))

    def visit_Call(self, node):
        if not isinstance(node.func, ast.Name):
            raise ValueError('Unsupported function call')
        func = self._safe_funcs.get(node.func.id)
        if not func or node.keywords:
            raise ValueError('Unsupported function call')
        args = [self.visit(arg) for arg in node.args]
        return func(*args)

    def generic_visit(self, node):
        raise ValueError(f'Unsupported expression element: {type(node).__name__}')


class FormEngine:
    """Engine xử lý form động từ metadata"""

    @staticmethod
    def _current_unit():
        return session.get('unit_area', session.get('unit', ''))

    @staticmethod
    def _is_numeric_field(field):
        return bool(field and (field.field_type == 'number' or field.data_type in ('integer', 'decimal')))

    @staticmethod
    def _coerce_numeric(raw_value):
        if raw_value in (None, ''):
            raise ValueError('Empty numeric value')
        return float(str(raw_value).replace(',', '').strip())

    @staticmethod
    def _format_display_value(raw_value, field=None):
        if raw_value in (None, ''):
            return ''
        if field and FormEngine._is_numeric_field(field):
            try:
                numeric = FormEngine._coerce_numeric(raw_value)
                return format_excel_number(numeric, None)
            except Exception:
                return str(raw_value)
        return str(raw_value)

    @staticmethod
    def _normalize_storage_value(raw_value, field=None):
        if raw_value in (None, ''):
            return None, 'string'
        if field and FormEngine._is_numeric_field(field):
            try:
                numeric = FormEngine._coerce_numeric(raw_value)
                return format_excel_number(numeric, None), 'decimal'
            except Exception:
                return str(raw_value).strip(), 'string'
        return str(raw_value).strip(), 'string'

    def _ensure_report_access(self, instance, user_unit=None, is_admin=False, write=False):
        if not instance:
            raise ValueError('Report instance không tồn tại')

        if is_admin:
            return instance

        current_unit = user_unit if user_unit is not None else self._current_unit()
        if (instance.org_unit or '') != current_unit:
            raise PermissionError('Bạn không có quyền truy cập báo cáo của đơn vị khác.')

        if write and getattr(instance.period, 'is_locked', False):
            raise PermissionError('Kỳ báo cáo này đã bị khóa.')

        return instance
    
    def get_form_schema(self, version_id):
        """
        Lấy schema form để render frontend
        Returns: dict với structure, fields, validation rules
        """
        version = FormVersion.query.get(version_id)
        if not version:
            raise ValueError(f"Version {version_id} không tồn tại")
        
        # Parse metadata
        metadata = json.loads(version.metadata_json) if version.metadata_json else {}
        
        # Lấy tất cả fields
        fields = FormField.query.filter_by(version_id=version_id).order_by(FormField.display_order).all()
        
        # Group fields by section
        sections = {}
        for field in fields:
            section_name = field.section or 'default'
            if section_name not in sections:
                sections[section_name] = []
            
            field_validation = json.loads(field.validation_rules_json) if field.validation_rules_json else {}
            sections[section_name].append({
                'code': field.field_code,
                'name': field.field_name,
                'type': field.field_type,
                'data_type': field.data_type,
                'required': field.is_required,
                'readonly': field.is_readonly,
                'calculated': field.is_calculated,
                'hidden': bool(field_validation.get('hidden', False)),
                'formula': field.calculation_formula,
                'default_value': field.default_value,
                'excel_cell': field.excel_cell_ref,
                'help_text': field.help_text,
                'validation': field_validation
            })
        
        return {
            'version_id': version_id,
            'version_number': version.version_number,
            'template_id': version.template_id,
            'template_name': version.template.name,
            'metadata': metadata,
            'sections': sections
        }
    
    def create_report_instance(self, template_id, period_id, user_id, org_unit):
        """
        Tạo báo cáo mới
        """
        period = db.session.get(ReportingPeriod, period_id)
        if not period:
            raise ValueError(f"Kỳ báo cáo {period_id} không tồn tại")
        if period.template_id not in (None, template_id):
            raise ValueError('Kỳ báo cáo không khớp với biểu mẫu được chọn')
        if period.is_locked:
            raise ValueError('Kỳ báo cáo đã bị khóa, không thể tạo báo cáo mới')

        # Lấy version published mới nhất
        version = FormVersion.query.filter_by(
            template_id=template_id,
            is_published=True
        ).order_by(FormVersion.created_at.desc()).first()
        
        if not version:
            raise ValueError(f"Template {template_id} chưa có version published")
        
        # Kiểm tra đã có báo cáo chưa
        existing = ReportInstance.query.filter_by(
            template_id=template_id,
            period_id=period_id,
            org_unit=org_unit
        ).first()
        
        if existing:
            return existing
        
        # Tạo mới
        instance = ReportInstance(
            template_id=template_id,
            version_id=version.id,
            period_id=period_id,
            user_id=user_id,
            org_unit=org_unit,
            status='draft'
        )
        db.session.add(instance)
        db.session.flush()
        
        # Audit log
        self._log_audit(
            user_id=user_id,
            org_unit=org_unit,
            entity_type='report_instance',
            entity_id=instance.id,
            action='create',
            new_value=f"Created report for period {period_id}"
        )
        
        db.session.commit()
        return instance
    
    def get_report_data(self, instance_id):
        """
        Lấy dữ liệu báo cáo
        Returns: dict với instance info và field values
        """
        instance = ReportInstance.query.get(instance_id)
        if not instance:
            raise ValueError(f"Report instance {instance_id} không tồn tại")
        
        # Lấy schema
        schema = self.get_form_schema(instance.version_id)
        
        field_map = {
            field.field_code: field
            for field in FormField.query.filter_by(version_id=instance.version_id).all()
        }

        # Lấy values
        values = {}
        for fv in instance.field_values:
            field = field_map.get(fv.field_code)
            raw_value = fv.value if fv.value is not None else ''
            values[fv.field_code] = {
                'value': raw_value,
                'display_value': self._format_display_value(raw_value, field),
                'type': fv.value_type,
                'row_index': fv.row_index
            }
            
        # Ensure all fields in schema have at least an empty dict in values
        for section in schema['sections'].values():
            for field in section:
                if field['code'] not in values:
                    values[field['code']] = {'value': ''}
        
        return {
            'instance': {
                'id': instance.id,
                'status': instance.status,
                'org_unit': instance.org_unit,
                'period_id': instance.period_id,
                'created_at': instance.created_at.isoformat(),
                'updated_at': instance.updated_at.isoformat(),
                'submitted_at': instance.submitted_at.isoformat() if instance.submitted_at else None
            },
            'schema': schema,
            'values': values
        }
    
    def save_draft(self, instance_id, data, user_id, user_unit=None, is_admin=False):
        """
        Lưu nháp - không validate
        data: dict {field_code: value}
        """
        instance = ReportInstance.query.get(instance_id)
        self._ensure_report_access(instance, user_unit=user_unit, is_admin=is_admin, write=True)
        field_map = {
            field.field_code: field
            for field in FormField.query.filter_by(version_id=instance.version_id).all()
        }

        if instance.status not in ['draft', 'returned']:
            raise ValueError(f"Không thể sửa báo cáo ở trạng thái {instance.status}")
        
        # Lưu từng field
        for field_code, value in data.items():
            field = field_map.get(field_code)
            stored_value, value_type = self._normalize_storage_value(value, field)
            # Tìm field value hiện tại
            fv = ReportFieldValue.query.filter_by(
                instance_id=instance_id,
                field_code=field_code
            ).first()
            
            old_value = fv.value if fv else None
            
            if fv:
                fv.value = stored_value
                fv.value_type = value_type
                fv.updated_at = datetime.now()
            else:
                fv = ReportFieldValue(
                    instance_id=instance_id,
                    field_code=field_code,
                    value=stored_value,
                    value_type=value_type
                )
                db.session.add(fv)
            
            # Audit log nếu có thay đổi
            if old_value != stored_value:
                self._log_audit(
                    user_id=user_id,
                    org_unit=instance.org_unit,
                    entity_type='field_value',
                    entity_id=fv.id if fv.id else 0,
                    action='update',
                    field_code=field_code,
                    old_value=old_value,
                    new_value=stored_value
                )
        
        instance.updated_at = datetime.now()
        db.session.commit()
        
        return {'success': True, 'message': 'Đã lưu nháp'}
    
    def calculate_fields(self, instance_id):
        """
        Tính toán các trường công thức
        """
        instance = ReportInstance.query.get(instance_id)
        if not instance:
            raise ValueError(f"Report instance {instance_id} không tồn tại")
        
        # Lấy các field calculated
        calc_fields = FormField.query.filter_by(
            version_id=instance.version_id,
            is_calculated=True
        ).order_by(FormField.display_order).all()
        
        # Lấy tất cả values hiện tại
        values = {}
        for fv in instance.field_values:
            try:
                values[fv.field_code] = self._coerce_numeric(fv.value) if fv.value not in (None, '') else 0
            except Exception:
                values[fv.field_code] = 0
        
        # Tính toán
        for field in calc_fields:
            if not field.calculation_formula:
                continue
            
            try:
                # Evaluate arithmetic formula safely using AST.
                formula = (field.calculation_formula or '').strip()
                if not formula:
                    continue

                tree = ast.parse(formula, mode='eval')
                result = _SafeFormulaEvaluator(values).visit(tree)
                
                # Save
                fv = ReportFieldValue.query.filter_by(
                    instance_id=instance_id,
                    field_code=field.field_code
                ).first()
                
                normalized_result = format_excel_number(float(result), None)
                if fv:
                    fv.value = normalized_result
                    fv.value_type = 'decimal'
                else:
                    fv = ReportFieldValue(
                        instance_id=instance_id,
                        field_code=field.field_code,
                        value=normalized_result,
                        value_type='decimal'
                    )
                    db.session.add(fv)

                values[field.field_code] = self._coerce_numeric(result)
                
            except Exception as e:
                print(f"Error calculating {field.field_code}: {e}")
                continue
        
        db.session.commit()
    
    def validate_report(self, instance_id):
        """
        Validate dữ liệu trước khi submit
        Returns: dict {valid: bool, errors: []}
        """
        instance = ReportInstance.query.get(instance_id)
        if not instance:
            raise ValueError(f"Report instance {instance_id} không tồn tại")
        
        errors = []
        
        # Lấy tất cả fields required
        required_fields = FormField.query.filter_by(
            version_id=instance.version_id,
            is_required=True
        ).all()
        
        # Lấy values hiện tại
        values = {fv.field_code: fv.value for fv in instance.field_values}
        
        # Check required
        for field in required_fields:
            if field.field_code not in values or not values[field.field_code]:
                errors.append({
                    'field': field.field_code,
                    'message': f'{field.field_name} là bắt buộc'
                })
        
        return {
            'valid': len(errors) == 0,
            'errors': errors
        }
    
    def submit_report(self, instance_id, user_id, user_unit=None, is_admin=False):
        """
        Submit báo cáo
        """
        instance = ReportInstance.query.get(instance_id)
        self._ensure_report_access(instance, user_unit=user_unit, is_admin=is_admin, write=True)

        if instance.status != 'draft':
            raise ValueError(f"Chỉ có thể submit báo cáo ở trạng thái draft")

        if getattr(instance.period, 'is_locked', False):
            raise ValueError('Kỳ báo cáo đã bị khóa')
        
        # Validate
        validation = self.validate_report(instance_id)
        if not validation['valid']:
            return {
                'success': False,
                'message': 'Dữ liệu chưa hợp lệ',
                'errors': validation['errors']
            }
        
        # Calculate fields
        self.calculate_fields(instance_id)
        
        # Update status
        instance.status = 'submitted'
        instance.submitted_at = datetime.now()
        
        # Audit log
        self._log_audit(
            user_id=user_id,
            org_unit=instance.org_unit,
            entity_type='report_instance',
            entity_id=instance.id,
            action='submit',
            new_value='Submitted report'
        )
        
        db.session.commit()
        
        return {
            'success': True,
            'message': 'Đã nộp báo cáo thành công'
        }
    
    def _log_audit(self, user_id, org_unit, entity_type, entity_id, action, field_code=None, old_value=None, new_value=None, reason=None):
        """Helper: Ghi audit log"""
        from models import User
        user = User.query.get(user_id)
        
        log = ReportAuditLog(
            user_id=user_id,
            user_name=user.fullname if user else 'Unknown',
            org_unit=org_unit,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            field_code=field_code,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            ip_address=session.get('ip_address'),
            session_id=session.get('session_id')
        )
        db.session.add(log)
