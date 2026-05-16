# -*- coding: utf-8 -*-
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

class AppRole(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)
    perms = db.Column(db.Text)


class MasterData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(100), index=True) 
    name = db.Column(db.String(255))


class NewsCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)


class LibraryField(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)


class ContactGroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)


class ProfessionalUnit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)


class ContactRole(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)


# ==================== UNIFIED CATEGORY SYSTEM ====================

class Category(db.Model):
    """
    Danh mục tập trung cho toàn hệ thống.
    Thay thế MasterData, LibraryField, ContactGroup, ProfessionalUnit, ContactRole.
    """
    __tablename__ = 'category'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True)  # Mã định danh (VD: CA_XA_TRUONG)
    name = db.Column(db.String(255))             # Tên hiển thị
    type = db.Column(db.String(50))               # Loại: position, unit, district, rank, duty
    parent_id = db.Column(db.Integer, db.ForeignKey('category.id'))  # Cha (phân cấp)
    order = db.Column(db.Integer, default=0)      # Thứ tự
    is_active = db.Column(db.Boolean, default=True)
    description = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    # Hierarchy
    parent = db.relationship('Category', remote_side=[id], backref='children')


class CategoryGroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), unique=True, index=True)
    name = db.Column(db.String(100), unique=True)
    linked_modules = db.Column(db.Text) # Legacy compatibility field
    description = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)


class CategoryItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('category_group.id'))
    code = db.Column(db.String(100), index=True)
    name = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    group = db.relationship('CategoryGroup', backref='items')


class CategoryItemAlias(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('category_item.id'), nullable=False, index=True)
    alias_name = db.Column(db.String(255), nullable=False)
    alias_slug = db.Column(db.String(255), index=True)

    item = db.relationship('CategoryItem', backref='aliases')


class ModuleRegistry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, index=True)
    name = db.Column(db.String(100), unique=True)
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)


class CategoryGroupModule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('category_group.id'), nullable=False, index=True)
    module_id = db.Column(db.Integer, db.ForeignKey('module_registry.id'), nullable=False, index=True)

    group = db.relationship('CategoryGroup', backref='module_links')
    module = db.relationship('ModuleRegistry', backref='group_links')


class ModuleFieldBinding(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey('module_registry.id'), nullable=False, index=True)
    field_code = db.Column(db.String(100), nullable=False, index=True)
    field_label = db.Column(db.String(255))
    group_id = db.Column(db.Integer, db.ForeignKey('category_group.id'), nullable=False, index=True)
    is_required = db.Column(db.Boolean, default=False)
    allow_multiple_groups = db.Column(db.Boolean, default=False)

    module = db.relationship('ModuleRegistry', backref='field_bindings')
    group = db.relationship('CategoryGroup', backref='field_bindings')


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, index=True)
    password_hash = db.Column(db.String(128))
    fullname = db.Column(db.String(100))
    role_id = db.Column(db.Integer, db.ForeignKey('app_role.id'))
    unit_area = db.Column(db.String(100))
    unit_key = db.Column(db.String(100), index=True)
    is_active = db.Column(db.Boolean, default=True)
    phone = db.Column(db.String(20))  # SĐT Zalo format E.164 (+84...)
    must_change_password = db.Column(db.Boolean, default=True)
    role = db.relationship('AppRole', backref='users')
    def set_password(self, p): self.password_hash = generate_password_hash(p, method='pbkdf2:sha256')
    def check_password(self, p): return check_password_hash(self.password_hash, p)


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(100))
    domain = db.Column(db.String(100)) 
    title = db.Column(db.String(255))
    content = db.Column(db.Text)
    deadline = db.Column(db.Date)
    file_path = db.Column(db.String(255))
    author_id = db.Column(db.Integer)
    author_name = db.Column(db.String(100))
    priority = db.Column(db.String(50))
    task_type = db.Column(db.String(100))
    initial_status = db.Column(db.String(50), default='Chưa tiếp nhận')
    parent_task_id = db.Column(db.Integer, db.ForeignKey('task.id'))
    assign_type = db.Column(db.String(20), default='unit')
    assignment_scope_json = db.Column(db.Text)
    viewer_scope_json = db.Column(db.Text)
    report_schema_json = db.Column(db.Text)
    linked_report_templates_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)
    assignments = db.relationship('TaskAssignment', backref='task', cascade='all, delete-orphan')
    child_tasks = db.relationship('Task', backref=db.backref('parent_task', remote_side=[id]))


class TaskAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    status = db.Column(db.String(50), default='Chưa tiếp nhận')
    result_file = db.Column(db.String(255))
    report_payload_json = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    user = db.relationship('User', backref='task_assignments')


class TaskComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer)
    user_id = db.Column(db.Integer)
    user_name = db.Column(db.String(100))
    content = db.Column(db.Text)
    assignee_id = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)


class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    contact_group = db.Column(db.String(100))
    unit_name = db.Column(db.String(100))
    name = db.Column(db.String(100))
    phone = db.Column(db.String(50))
    role = db.Column(db.String(100))


class NewsDoc(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255))
    category = db.Column(db.String(100))
    content = db.Column(db.Text)
    target_scope = db.Column(db.String(50), default='Toàn tỉnh')
    filename = db.Column(db.String(255))
    uploaded_at = db.Column(db.DateTime, default=datetime.now)


class DocumentLib(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255))
    category = db.Column(db.String(100))
    filename = db.Column(db.String(255))
    uploaded_at = db.Column(db.DateTime, default=datetime.now)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    title = db.Column(db.String(255))
    msg = db.Column(db.Text)
    link = db.Column(db.String(255))
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)




class SystemLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    fullname = db.Column(db.String(100))
    module = db.Column(db.String(100))
    action = db.Column(db.String(255))
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)


class ShortLink(db.Model):
    __tablename__ = 'short_link'

    id = db.Column(db.Integer, primary_key=True)
    short_code = db.Column(db.String(50), unique=True, index=True)
    original_url = db.Column(db.Text, nullable=False)
    custom_name = db.Column(db.String(100))
    info = db.Column(db.Text)
    category = db.Column(db.String(100))
    domain = db.Column(db.String(100))
    clicks = db.Column(db.Integer, default=0)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    user = db.relationship('User', backref='short_links')


# ==================== REPORTING SYSTEM (NEW) ====================

class ReportUnit(db.Model):
    __tablename__ = 'report_unit'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), unique=True, index=True)
    name = db.Column(db.String(255), nullable=False, index=True)
    source = db.Column(db.String(50), default='user')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)


class ReportType(db.Model):
    __tablename__ = 'report_type'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, index=True)
    name = db.Column(db.String(100), nullable=False)
    frequency = db.Column(db.String(50), default='periodic')
    description = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)


class ReportTemplate(db.Model):
    __tablename__ = 'report_template'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), unique=True, index=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    report_type_id = db.Column(db.Integer, index=True)
    professional_unit = db.Column(db.String(255), index=True)
    assignment_scope_json = db.Column(db.Text)
    directive_filename = db.Column(db.String(255))
    directive_path = db.Column(db.String(500))
    periodic_cycle_type = db.Column(db.String(30))
    periodic_due_day = db.Column(db.Integer)
    periodic_due_month = db.Column(db.Integer)
    status = db.Column(db.String(50), default='draft')
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)


class ReportTemplateVersion(db.Model):
    __tablename__ = 'report_template_version'
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('report_template.id'), nullable=False, index=True)
    version_no = db.Column(db.Integer, default=1)
    source_filename = db.Column(db.String(255))
    source_path = db.Column(db.String(500))
    metadata_json = db.Column(db.Text)
    notes = db.Column(db.Text)
    is_current = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)


class ReportTemplateSheet(db.Model):
    __tablename__ = 'report_template_sheet'
    id = db.Column(db.Integer, primary_key=True)
    version_id = db.Column(db.Integer, db.ForeignKey('report_template_version.id'), nullable=False, index=True)
    sheet_name = db.Column(db.String(255), nullable=False)
    order_index = db.Column(db.Integer, default=0)
    header_start_row = db.Column(db.Integer, default=1)
    header_end_row = db.Column(db.Integer, default=1)
    header_rows = db.Column(db.Integer, default=1)
    data_start_row = db.Column(db.Integer, default=2)
    data_end_row = db.Column(db.Integer, default=0)
    unit_key_column = db.Column(db.String(20))
    can_input = db.Column(db.Boolean, default=True)
    visible_in_preview = db.Column(db.Boolean, default=True)
    summary_json = db.Column(db.Text)


class ReportTemplateField(db.Model):
    __tablename__ = 'report_template_field'
    id = db.Column(db.Integer, primary_key=True)
    version_id = db.Column(db.Integer, db.ForeignKey('report_template_version.id'), nullable=False, index=True)
    sheet_name = db.Column(db.String(255), nullable=False)
    field_code = db.Column(db.String(120), nullable=False, index=True)
    field_name = db.Column(db.String(255))
    display_name = db.Column(db.String(255))
    column_index = db.Column(db.Integer, nullable=False)
    column_letter = db.Column(db.String(20), nullable=False)
    data_type = db.Column(db.String(50), default='text')
    input_mode = db.Column(db.String(50), default='text')
    is_required = db.Column(db.Boolean, default=False)
    is_visible = db.Column(db.Boolean, default=True)
    is_editable = db.Column(db.Boolean, default=True)
    default_value = db.Column(db.Text)
    validation_rule = db.Column(db.Text)
    dictionary_source = db.Column(db.String(255))
    formula_expression = db.Column(db.Text)
    aggregation_type = db.Column(db.String(50))
    display_order = db.Column(db.Integer, default=0)
    path_code = db.Column(db.Text)


class ReportCycle(db.Model):
    __tablename__ = 'report_cycle'
    id = db.Column(db.Integer, primary_key=True)
    template_version_id = db.Column(db.Integer, db.ForeignKey('report_template_version.id'), nullable=False, index=True)
    report_type_id = db.Column(db.Integer, db.ForeignKey('report_type.id'), nullable=False, index=True)
    legacy_period_id = db.Column(db.Integer, index=True)
    name = db.Column(db.String(255), nullable=False)
    open_at = db.Column(db.DateTime)
    close_at = db.Column(db.DateTime)
    due_at = db.Column(db.DateTime)
    auto_lock_at = db.Column(db.DateTime)
    status = db.Column(db.String(50), default='open')
    scope_json = db.Column(db.Text)
    is_locked = db.Column(db.Boolean, default=False)
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)


class ReportInstance(db.Model):
    __tablename__ = 'report_instance'
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, index=True)
    version_id = db.Column(db.Integer, index=True)
    period_id = db.Column(db.Integer, index=True)
    user_id = db.Column(db.Integer, index=True)
    org_unit = db.Column(db.String(100))
    cycle_id = db.Column(db.Integer, db.ForeignKey('report_cycle.id'), nullable=False, index=True)
    report_unit_id = db.Column(db.Integer, db.ForeignKey('report_unit.id'), index=True)
    assigned_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    status = db.Column(db.String(50), default='draft')
    opened_at = db.Column(db.DateTime, default=datetime.now)
    submitted_at = db.Column(db.DateTime)
    reviewed_at = db.Column(db.DateTime)
    locked_at = db.Column(db.DateTime)
    locked_by = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    note = db.Column(db.Text)


class ReportSubmission(db.Model):
    __tablename__ = 'report_submission'
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, index=True)
    template_version_id = db.Column(db.Integer, index=True)
    period_id = db.Column(db.Integer, index=True)
    report_period = db.Column(db.String(50))
    reporting_unit = db.Column(db.String(255))
    submitted_by = db.Column(db.Integer, index=True)
    instance_id = db.Column(db.Integer, db.ForeignKey('report_instance.id'), nullable=False, index=True)
    version_no = db.Column(db.Integer, default=1)
    status = db.Column(db.String(50), default='draft')
    original_filename = db.Column(db.String(255))
    original_file_path = db.Column(db.String(500))
    processed_file_path = db.Column(db.String(500))
    error_file_path = db.Column(db.String(500))
    total_rows = db.Column(db.Integer)
    valid_rows = db.Column(db.Integer)
    invalid_rows = db.Column(db.Integer)
    warning_count = db.Column(db.Integer)
    metadata_json = db.Column(db.Text)
    note = db.Column(db.Text)
    file_path = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    submitted_at = db.Column(db.DateTime)


class ReportingPeriod(db.Model):
    __tablename__ = 'reporting_period'
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, index=True)
    code = db.Column(db.String(50), unique=True, index=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    period_type = db.Column(db.String(20), nullable=False)
    is_adhoc = db.Column(db.Boolean, default=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    deadline = db.Column(db.DateTime)
    is_locked = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    created_by = db.Column(db.Integer)


class ReportSubmissionValue(db.Model):
    __tablename__ = 'report_submission_value'
    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('report_submission.id'), nullable=False, index=True)
    sheet_name = db.Column(db.String(255), nullable=False)
    field_code = db.Column(db.String(120), nullable=False, index=True)
    cell_address = db.Column(db.String(20))
    value_text = db.Column(db.Text)
    value_number = db.Column(db.Float)
    value_json = db.Column(db.Text)


class ReportSubmissionCell(db.Model):
    __tablename__ = 'report_submission_cell'
    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('report_submission.id'), nullable=False, index=True)
    sheet_name = db.Column(db.String(255), nullable=False)
    cell_address = db.Column(db.String(20), nullable=False, index=True)
    raw_value = db.Column(db.Text)
    is_formula = db.Column(db.Boolean, default=False)
    formula_text = db.Column(db.Text)


class ReportAuditLog(db.Model):
    __tablename__ = 'report_audit_log'
    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    action = db.Column(db.String(100), nullable=False)
    module = db.Column(db.String(100), default='report')
    object_type = db.Column(db.String(100))
    object_id = db.Column(db.Integer)
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)


class ReportValidationLog(db.Model):
    __tablename__ = 'report_validation_log'
    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('report_submission.id'), index=True)
    sheet_name = db.Column(db.String(255))
    field_code = db.Column(db.String(120))
    cell_address = db.Column(db.String(20))
    severity = db.Column(db.String(20), default='warning')
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)


class ReportExportJob(db.Model):
    __tablename__ = 'report_export_job'
    id = db.Column(db.Integer, primary_key=True)
    cycle_id = db.Column(db.Integer, db.ForeignKey('report_cycle.id'), index=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('report_submission.id'), index=True)
    status = db.Column(db.String(50), default='queued')
    output_path = db.Column(db.String(500))
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)
    finished_at = db.Column(db.DateTime)


# --- RANKING SYSTEM MODELS (V13) ---

class RankingUnit(db.Model):
    __tablename__ = 'ranking_unit'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False)
    group_name = db.Column(db.String(100)) # e.g. "Đội 1"

class RankingIndicator(db.Model):
    __tablename__ = 'ranking_indicator'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    coef = db.Column(db.Integer, default=1) # 1 or 2
    higher_is_better = db.Column(db.Boolean, default=True) # True for stats, False for "quá hạn"
    category = db.Column(db.String(50)) # "Trọng điểm", "Thường xuyên", "Phát sinh"
    sheet_name = db.Column(db.String(100)) # To link with Excel if needed

class RankingEntry(db.Model):
    __tablename__ = 'ranking_entry'
    id = db.Column(db.Integer, primary_key=True)
    unit_id = db.Column(db.Integer, db.ForeignKey('ranking_unit.id'))
    indicator_id = db.Column(db.Integer, db.ForeignKey('ranking_indicator.id'))
    raw_value = db.Column(db.Float, default=0.0)
    
    unit = db.relationship('RankingUnit', backref='entries')
    indicator = db.relationship('RankingIndicator', backref='entries')


class AIAssistantConfig(db.Model):
    """Cấu hình provider/model/key cho trợ lý AI."""
    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(30), default='deepseek', nullable=False)
    model_name = db.Column(db.String(100), default='deepseek-v4-flash', nullable=False)
    api_key = db.Column(db.Text)
    system_prompt = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    created_at = db.Column(db.DateTime, default=datetime.now)
