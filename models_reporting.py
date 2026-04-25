# -*- coding: utf-8 -*-
"""
Hệ thống nhập liệu báo cáo mới - Models
Theo kiến trúc: Form Engine + Metadata + Audit Trail
Độc lập hoàn toàn với V1/V2
"""

from datetime import datetime
import uuid

from models import db  # reuse the DB instance defined in models.py


# ==================== KỲ BÁO CÁO ====================

class ReportingPeriod(db.Model):
    """Kỳ báo cáo (ngày, tuần, tháng, quý, năm)"""
    __tablename__ = 'reporting_period'
    
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('form_template.id'), nullable=True) # Liên kết tới biểu mẫu cụ thể
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)  # VD: "2024-Q1", "2024-03", "2024-W14"
    name = db.Column(db.String(100), nullable=False)  # VD: "Quý 1 năm 2024"
    period_type = db.Column(db.String(20), nullable=False)  # daily, weekly, monthly, quarterly, yearly
    is_adhoc = db.Column(db.Boolean, default=False) # Đánh dấu báo cáo đột xuất
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    deadline = db.Column(db.DateTime)  # Hạn nộp báo cáo
    is_locked = db.Column(db.Boolean, default=False)  # Đã khóa kỳ
    created_at = db.Column(db.DateTime, default=datetime.now)
    created_by = db.Column(db.Integer)  # User ID
    
    def __repr__(self):
        return f'<ReportingPeriod {self.code}: {self.name}>'


# ==================== MẪU BIỂU VÀ METADATA ====================

class FormTemplate(db.Model):
    """Mẫu biểu báo cáo"""
    __tablename__ = 'form_template'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(100))  # Phân loại: thống kê, tài chính, nhân sự, đất đai...
    
    # --- Cấu hình kỳ nộp báo cáo ---
    report_type = db.Column(db.String(20), default='adhoc')  # daily, periodic, adhoc
    frequency = db.Column(db.String(20))  # weekly, monthly, quarterly, yearly (dùng cho loại periodic)
    deadline_rule = db.Column(db.String(50))  # VD: "16:30" cho daily, "5" cho monthly (ngày mùng 5)
    # --------------------------------
    
    excel_template_blob = db.Column(db.LargeBinary)  # File Excel mẫu gốc
    is_active = db.Column(db.Boolean, default=True)
    department = db.Column(db.String(100)) # Đội nghiệp vụ phụ trách báo cáo này
    created_by = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    
    def __repr__(self):
        return f'<FormTemplate {self.code}: {self.name}>'


class FormVersion(db.Model):
    """Phiên bản mẫu biểu - cho phép cập nhật mẫu theo thời gian"""
    __tablename__ = 'form_version'
    
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('form_template.id'), nullable=False)
    version_number = db.Column(db.String(20), nullable=False)  # v1.0, v1.1, v2.0
    metadata_json = db.Column(db.Text)  # Cấu trúc form: fields, sections, layout
    is_published = db.Column(db.Boolean, default=False)
    effective_from = db.Column(db.Date)  # Áp dụng từ ngày
    effective_to = db.Column(db.Date)  # Áp dụng đến ngày
    created_at = db.Column(db.DateTime, default=datetime.now)
    created_by = db.Column(db.Integer)
    
    template = db.relationship('FormTemplate', backref='versions')
    
    def __repr__(self):
        return f'<FormVersion {self.version_number} of Template {self.template_id}>'


class FormField(db.Model):
    """Định nghĩa trường dữ liệu trong biểu mẫu"""
    __tablename__ = 'form_field'
    
    id = db.Column(db.Integer, primary_key=True)
    version_id = db.Column(db.Integer, db.ForeignKey('form_version.id'), nullable=False)
    field_code = db.Column(db.String(50), nullable=False, index=True)  # VD: "luoi_dia_chinh_chi_tieu"
    field_name = db.Column(db.String(255), nullable=False)  # Tên hiển thị
    field_type = db.Column(db.String(20), nullable=False)  # text, number, date, select, table, file
    data_type = db.Column(db.String(20))  # string, integer, decimal, boolean, date
    is_required = db.Column(db.Boolean, default=False)
    is_readonly = db.Column(db.Boolean, default=False)
    is_calculated = db.Column(db.Boolean, default=False)
    calculation_formula = db.Column(db.Text)  # Công thức tính: VD: "field_a + field_b"
    default_value = db.Column(db.Text)
    options_json = db.Column(db.Text)  # Cho select, radio, checkbox
    validation_rules_json = db.Column(db.Text)  # Rules: min, max, regex, custom
    display_order = db.Column(db.Integer, default=0)
    section = db.Column(db.String(100))  # Nhóm/phần của form
    excel_cell_ref = db.Column(db.String(20))  # Tham chiếu ô Excel: "B5", "C10"
    help_text = db.Column(db.Text)
    
    version = db.relationship('FormVersion', backref='fields')
    
    def __repr__(self):
        return f'<FormField {self.field_code}>'


class ValidationRule(db.Model):
    """Quy tắc kiểm tra dữ liệu"""
    __tablename__ = 'validation_rule'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    rule_type = db.Column(db.String(50), nullable=False)  # required, range, regex, formula, cross_field
    scope = db.Column(db.String(50))  # field, form, template
    expression = db.Column(db.Text, nullable=False)  # Biểu thức kiểm tra
    error_message = db.Column(db.Text, nullable=False)
    severity = db.Column(db.String(20), default='error')  # error, warning, info
    is_blocking = db.Column(db.Boolean, default=True)  # Có chặn submit không
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    def __repr__(self):
        return f'<ValidationRule {self.code}>'


# ==================== BÁO CÁO INSTANCE ====================

class ReportInstance(db.Model):
    """Một báo cáo cụ thể của đơn vị trong kỳ"""
    __tablename__ = 'report_instance'
    
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('form_template.id'), nullable=False)
    version_id = db.Column(db.Integer, db.ForeignKey('form_version.id'), nullable=False)
    period_id = db.Column(db.Integer, db.ForeignKey('reporting_period.id'), nullable=False)
    user_id = db.Column(db.Integer, nullable=False)  # Người tạo/nhập
    org_unit = db.Column(db.String(100), nullable=False, index=True)  # Đơn vị báo cáo
    status = db.Column(db.String(20), default='draft', index=True)  # draft, submitted, locked
    submitted_at = db.Column(db.DateTime)
    locked_at = db.Column(db.DateTime)
    locked_by = db.Column(db.Integer)  # User ID của người khóa
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    
    template = db.relationship('FormTemplate', backref='instances')
    version = db.relationship('FormVersion', backref='instances')
    period = db.relationship('ReportingPeriod', backref='reports')
    
    def __repr__(self):
        return f'<ReportInstance {self.id}: {self.org_unit} - {self.status}>'


class ReportFieldValue(db.Model):
    """Giá trị từng trường trong báo cáo"""
    __tablename__ = 'report_field_value'
    
    id = db.Column(db.Integer, primary_key=True)
    instance_id = db.Column(db.Integer, db.ForeignKey('report_instance.id'), nullable=False, index=True)
    field_code = db.Column(db.String(50), nullable=False, index=True)
    value = db.Column(db.Text)
    value_type = db.Column(db.String(20))  # Để cast đúng kiểu khi đọc
    row_index = db.Column(db.Integer)  # Cho trường dạng bảng (nhiều dòng)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    
    instance = db.relationship('ReportInstance', backref='field_values')
    
    def __repr__(self):
        return f'<ReportFieldValue {self.field_code}={self.value}>'


# ==================== AUDIT TRAIL ====================

class ReportAuditLog(db.Model):
    """Nhật ký thay đổi báo cáo - BẮT BUỘC theo tài liệu"""
    __tablename__ = 'report_audit_log'
    
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(50), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    timestamp = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=False)
    user_name = db.Column(db.String(100))
    org_unit = db.Column(db.String(100))
    entity_type = db.Column(db.String(50), nullable=False)  # report_instance, field_value
    entity_id = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(50), nullable=False)  # create, update, delete, submit, lock
    field_code = db.Column(db.String(50))
    old_value = db.Column(db.Text)
    new_value = db.Column(db.Text)
    reason = db.Column(db.Text)  # Lý do thay đổi
    ip_address = db.Column(db.String(50))
    session_id = db.Column(db.String(100))
    
    def __repr__(self):
        return f'<AuditLog {self.event_id}: {self.action} by User {self.user_id}>'


# ==================== FILE ĐÍNH KÈM ====================

class ReportAttachment(db.Model):
    """File đính kèm báo cáo"""
    __tablename__ = 'report_attachment'
    
    id = db.Column(db.Integer, primary_key=True)
    instance_id = db.Column(db.Integer, db.ForeignKey('report_instance.id'), nullable=False)
    field_code = db.Column(db.String(50))  # Trường nào yêu cầu file
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer)
    mime_type = db.Column(db.String(100))
    uploaded_by = db.Column(db.Integer, nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.now)
    
    instance = db.relationship('ReportInstance', backref='attachments')
    
    def __repr__(self):
        return f'<ReportAttachment {self.filename}>'
