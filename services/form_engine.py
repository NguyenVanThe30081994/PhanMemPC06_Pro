# -*- coding: utf-8 -*-
"""
Form Engine - Xử lý render form và validation
Theo kiến trúc tài liệu: Form Engine + Metadata
"""
import json
from datetime import datetime
from models_reporting import db, FormTemplate, FormVersion, FormField, ReportInstance, ReportFieldValue, ReportAuditLog
from flask import session


class FormEngine:
    """Engine xử lý form động từ metadata"""
    
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
            
            sections[section_name].append({
                'code': field.field_code,
                'name': field.field_name,
                'type': field.field_type,
                'data_type': field.data_type,
                'required': field.is_required,
                'readonly': field.is_readonly,
                'calculated': field.is_calculated,
                'formula': field.calculation_formula,
                'default_value': field.default_value,
                'excel_cell': field.excel_cell_ref,
                'help_text': field.help_text,
                'validation': json.loads(field.validation_rules_json) if field.validation_rules_json else {}
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
        
        # Lấy values
        values = {}
        for fv in instance.field_values:
            values[fv.field_code] = {
                'value': fv.value,
                'type': fv.value_type,
                'row_index': fv.row_index
            }
        
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
    
    def save_draft(self, instance_id, data, user_id):
        """
        Lưu nháp - không validate
        data: dict {field_code: value}
        """
        instance = ReportInstance.query.get(instance_id)
        if not instance:
            raise ValueError(f"Report instance {instance_id} không tồn tại")
        
        if instance.status not in ['draft', 'returned']:
            raise ValueError(f"Không thể sửa báo cáo ở trạng thái {instance.status}")
        
        # Lưu từng field
        for field_code, value in data.items():
            # Tìm field value hiện tại
            fv = ReportFieldValue.query.filter_by(
                instance_id=instance_id,
                field_code=field_code
            ).first()
            
            old_value = fv.value if fv else None
            
            if fv:
                fv.value = str(value) if value is not None else None
                fv.updated_at = datetime.now()
            else:
                fv = ReportFieldValue(
                    instance_id=instance_id,
                    field_code=field_code,
                    value=str(value) if value is not None else None,
                    value_type='string'
                )
                db.session.add(fv)
            
            # Audit log nếu có thay đổi
            if old_value != str(value):
                self._log_audit(
                    user_id=user_id,
                    org_unit=instance.org_unit,
                    entity_type='field_value',
                    entity_id=fv.id if fv.id else 0,
                    action='update',
                    field_code=field_code,
                    old_value=old_value,
                    new_value=str(value) if value is not None else None
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
        ).all()
        
        # Lấy tất cả values hiện tại
        values = {}
        for fv in instance.field_values:
            try:
                values[fv.field_code] = float(fv.value) if fv.value else 0
            except:
                values[fv.field_code] = 0
        
        # Tính toán
        for field in calc_fields:
            if not field.calculation_formula:
                continue
            
            try:
                # Simple formula evaluation
                # VD: "(luoi_ket_qua / luoi_chi_tieu) * 100"
                formula = field.calculation_formula
                
                # Replace field codes with values
                for code, val in values.items():
                    formula = formula.replace(code, str(val))
                
                # Evaluate
                result = eval(formula)
                
                # Save
                fv = ReportFieldValue.query.filter_by(
                    instance_id=instance_id,
                    field_code=field.field_code
                ).first()
                
                if fv:
                    fv.value = str(round(result, 2))
                else:
                    fv = ReportFieldValue(
                        instance_id=instance_id,
                        field_code=field.field_code,
                        value=str(round(result, 2)),
                        value_type='decimal'
                    )
                    db.session.add(fv)
                
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
    
    def submit_report(self, instance_id, user_id):
        """
        Submit báo cáo
        """
        instance = ReportInstance.query.get(instance_id)
        if not instance:
            raise ValueError(f"Report instance {instance_id} không tồn tại")
        
        if instance.status != 'draft':
            raise ValueError(f"Chỉ có thể submit báo cáo ở trạng thái draft")
        
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
