# -*- coding: utf-8 -*-
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint
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


class Unit(db.Model):
    """Đơn vị hành chính/đơn vị công tác (phân cấp cha-con).

    Thay thế dần chuỗi unit_key/unit_area trên User. Có quan hệ cây để
    thực hiện data-scope: user thuộc đơn vị con nhìn thấy dữ liệu của
    đơn vị mình + toàn bộ nhánh con.
    """
    __tablename__ = 'unit'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), unique=True, index=True)
    name = db.Column(db.String(255), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('unit.id'), index=True)
    level = db.Column(db.String(30), default='commune')  # province | district | commune
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)

    parent = db.relationship('Unit', remote_side=[id], backref='children')


class UserRole(db.Model):
    """Vai trò phụ của user (ngoài vai trò chính User.role_id).

    Cho phép 1 người mang nhiều vai trò; quyền hiệu lực = hợp của
    vai trò chính + tất cả vai trò phụ. unit_id để gán vai trò phụ theo
    đơn vị (vd: vừa Cán bộ CAT vừa kiêm Cán bộ CAX ở 1 xã).
    """
    __tablename__ = 'user_role'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'role_id', 'unit_id', name='uq_user_role_unit'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    role_id = db.Column(db.Integer, db.ForeignKey('app_role.id'), nullable=False, index=True)
    unit_id = db.Column(db.Integer, db.ForeignKey('unit.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    user = db.relationship('User', backref='user_roles')
    role = db.relationship('AppRole', backref='user_role_links')
    unit = db.relationship('Unit', backref='user_role_links')


class Delegation(db.Model):
    """Ủy quyền tạm thời: người có quyền xử lý ủy quyền cho người khác.

    module_code = None nghĩa là ủy quyền toàn bộ (mọi module).
    Khi còn hiệu lực (is_active + trong khoảng from_date..to_date),
    người được ủy quyền được xử lý như người ủy quyền.
    """
    __tablename__ = 'delegation'

    id = db.Column(db.Integer, primary_key=True)
    delegator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    delegatee_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    module_code = db.Column(db.String(50), index=True)  # None = toàn bộ
    from_date = db.Column(db.Date, nullable=False)
    to_date = db.Column(db.Date, nullable=False)
    note = db.Column(db.String(500))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    delegator = db.relationship('User', foreign_keys=[delegator_id], backref='delegations_given')
    delegatee = db.relationship('User', foreign_keys=[delegatee_id], backref='delegations_received')


class PermissionLog(db.Model):
    """Nhật ký riêng cho các thay đổi phân quyền (cấp/thu hồi vai trò, sửa quyền, ủy quyền)."""
    __tablename__ = 'permission_log'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, index=True)
    username = db.Column(db.String(100))
    action = db.Column(db.String(50))  # add_role | edit_role_perms | assign_role | revoke_role | add_extra_role | remove_extra_role | delegate | revoke_delegation | set_unit
    target_type = db.Column(db.String(30))  # role | user | delegation | unit
    target_name = db.Column(db.String(255))
    details = db.Column(db.Text)
    ip = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, index=True)
    password_hash = db.Column(db.String(255))
    fullname = db.Column(db.String(100))
    email = db.Column(db.String(200), nullable=True)
    role_id = db.Column(db.Integer, db.ForeignKey('app_role.id'))
    unit_area = db.Column(db.String(100))
    unit_key = db.Column(db.String(100), index=True)
    unit_id = db.Column(db.Integer, db.ForeignKey('unit.id'), nullable=True, index=True)
    is_active = db.Column(db.Boolean, default=True)
    phone = db.Column(db.String(20))  # SĐT Zalo format E.164 (+84...)
    must_change_password = db.Column(db.Boolean, default=True)
    session_version = db.Column(db.Integer, default=0)
    role = db.relationship('AppRole', backref='users')
    unit = db.relationship('Unit', backref='users')
    def set_password(self, p): self.password_hash = generate_password_hash(p, method='pbkdf2:sha256')
    def check_password(self, p): return check_password_hash(self.password_hash, p)


class LoginSecurityState(db.Model):
    __tablename__ = 'login_security_state'
    __table_args__ = (
        UniqueConstraint('scope_type', 'scope_key', name='uq_login_security_scope'),
    )

    id = db.Column(db.Integer, primary_key=True)
    scope_type = db.Column(db.String(20), nullable=False, index=True)
    scope_key = db.Column(db.String(255), nullable=False, index=True)
    failed_attempts = db.Column(db.Integer, default=0)
    lock_count = db.Column(db.Integer, default=0)
    first_failed_at = db.Column(db.DateTime)
    last_failed_at = db.Column(db.DateTime)
    locked_until = db.Column(db.DateTime)
    last_success_at = db.Column(db.DateTime)
    last_success_ip = db.Column(db.String(64))
    last_failed_secret_hash = db.Column(db.String(64))


class UserTrustedDevice(db.Model):
    __tablename__ = 'user_trusted_device'
    __table_args__ = (
        UniqueConstraint('user_id', 'device_key', name='uq_user_trusted_device'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    device_key = db.Column(db.String(64), nullable=False, index=True)
    device_label = db.Column(db.String(255))
    first_seen_ip = db.Column(db.String(64))
    last_seen_ip = db.Column(db.String(64))
    last_user_agent = db.Column(db.String(255))
    first_seen_at = db.Column(db.DateTime, default=datetime.now)
    last_seen_at = db.Column(db.DateTime, default=datetime.now)

    user = db.relationship('User', backref='trusted_devices')


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
    manager_scope_json = db.Column(db.Text)
    task_mode = db.Column(db.String(20), default='FILE')
    form_provider = db.Column(db.String(20), default='internal')
    google_form_url = db.Column(db.String(500))
    google_form_id = db.Column(db.String(255))
    google_form_match_mode = db.Column(db.String(50))
    google_form_match_field = db.Column(db.String(255))
    google_form_builder_json = db.Column(db.Text)
    google_form_runtime_json = db.Column(db.Text)
    google_form_sync_state_json = db.Column(db.Text)
    report_schema_json = db.Column(db.Text)
    outline_table_schema_json = db.Column(db.Text)
    report_period_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)
    assignments = db.relationship('TaskAssignment', backref='task', cascade='all, delete-orphan')
    task_items = db.relationship('TaskItem', backref='task', cascade='all, delete-orphan', foreign_keys='TaskItem.task_id')
    participants = db.relationship('TaskParticipant', backref='task', cascade='all, delete-orphan', foreign_keys='TaskParticipant.task_id')
    submissions = db.relationship('TaskSubmission', backref='task', cascade='all, delete-orphan', foreign_keys='TaskSubmission.task_id')
    form_fields = db.relationship('TaskFormField', backref='task', cascade='all, delete-orphan', foreign_keys='TaskFormField.task_id')
    child_tasks = db.relationship('Task', backref=db.backref('parent_task', remote_side=[id]))


class TaskImportDraft(db.Model):
    __tablename__ = 'task_import_draft'

    id = db.Column(db.Integer, primary_key=True)
    source_type = db.Column(db.String(50), index=True)
    source_name = db.Column(db.String(255))
    source_ref = db.Column(db.String(500))
    workflow_blueprint_json = db.Column(db.Text)
    working_config_json = db.Column(db.Text)
    status = db.Column(db.String(30), default='draft', index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    published_task_id = db.Column(db.Integer, db.ForeignKey('task.id'), index=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    published_at = db.Column(db.DateTime)

    creator = db.relationship('User', backref='task_import_drafts')
    published_task = db.relationship('Task', backref='import_drafts', foreign_keys=[published_task_id])


class TaskItem(db.Model):
    __tablename__ = 'task_item'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=False, index=True)
    parent_item_id = db.Column(db.Integer, db.ForeignKey('task_item.id'), index=True)
    source_task_id = db.Column(db.Integer, db.ForeignKey('task.id'), index=True)
    item_code = db.Column(db.String(50))
    title = db.Column(db.String(255))
    content = db.Column(db.Text)
    guide_text = db.Column(db.Text)
    is_required = db.Column(db.Boolean, default=True)
    output_type = db.Column(db.String(30), default='OUTLINE')
    report_kind = db.Column(db.String(30), default='narrative')
    attachment_required = db.Column(db.Boolean, default=False)
    linked_item_id = db.Column(db.Integer, db.ForeignKey('task_item.id'), index=True)
    allow_aggregate = db.Column(db.Boolean, default=False)
    report_sources_json = db.Column(db.Text)
    table_cells_json = db.Column(db.Text)
    synthesis_content = db.Column(db.Text)
    synthesis_updated_at = db.Column(db.DateTime)
    status = db.Column(db.String(50), default='Chưa tiếp nhận')
    deadline = db.Column(db.Date)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    source_task = db.relationship('Task', foreign_keys=[source_task_id], backref='task_item_rows')
    parent_item = db.relationship('TaskItem', remote_side=[id], foreign_keys=[parent_item_id], backref='child_items')
    linked_item = db.relationship('TaskItem', remote_side=[id], foreign_keys=[linked_item_id], backref='linked_items')


class TaskAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'))
    task_item_id = db.Column(db.Integer, db.ForeignKey('task_item.id'), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    assignee_type = db.Column(db.String(20), default='user')
    unit_id = db.Column(db.Integer)
    role_id = db.Column(db.Integer, db.ForeignKey('app_role.id'), index=True)
    title_snapshot = db.Column(db.String(500))
    status = db.Column(db.String(50), default='Chưa tiếp nhận')
    is_required = db.Column(db.Boolean, default=True)
    result_file = db.Column(db.String(255))
    report_payload_json = db.Column(db.Text)
    assigned_at = db.Column(db.DateTime, default=datetime.now)
    submitted_at = db.Column(db.DateTime)
    returned_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    last_submission_id = db.Column(db.Integer, db.ForeignKey('task_submission.id'), index=True)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    user = db.relationship('User', backref='task_assignments')
    role = db.relationship('AppRole', backref='task_assignments')
    task_item = db.relationship('TaskItem', foreign_keys=[task_item_id], backref='assignments')
    last_submission = db.relationship('TaskSubmission', foreign_keys=[last_submission_id], post_update=True)


class TaskParticipant(db.Model):
    __tablename__ = 'task_participant'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=False, index=True)
    task_item_id = db.Column(db.Integer, db.ForeignKey('task_item.id'), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    role_id = db.Column(db.Integer, db.ForeignKey('app_role.id'), index=True)
    participant_type = db.Column(db.String(30), default='executor', index=True)
    source_type = db.Column(db.String(30), default='direct')
    source_ref = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    user = db.relationship('User', backref='task_participants')
    role = db.relationship('AppRole', backref='task_participants')
    task_item = db.relationship('TaskItem', foreign_keys=[task_item_id])


class TaskSubmission(db.Model):
    __tablename__ = 'task_submission'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=False, index=True)
    task_item_id = db.Column(db.Integer, db.ForeignKey('task_item.id'), index=True)
    participant_id = db.Column(db.Integer, db.ForeignKey('task_participant.id'), index=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('task_assignment.id'), index=True)
    submitted_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    submission_type = db.Column(db.String(30), default='narrative')
    status = db.Column(db.String(30), default='draft')
    narrative_content = db.Column(db.Text)
    numeric_value = db.Column(db.Float)
    payload_json = db.Column(db.Text)
    attachment_name = db.Column(db.String(255))
    attachment_path = db.Column(db.String(500))
    external_submission_id = db.Column(db.String(255), index=True)
    external_source = db.Column(db.String(30))
    cycle_key = db.Column(db.String(50), index=True)
    cycle_label = db.Column(db.String(100))
    synced_at = db.Column(db.DateTime)
    submitted_at = db.Column(db.DateTime)
    returned_at = db.Column(db.DateTime)
    approved_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    participant = db.relationship('TaskParticipant', backref='submissions')
    assignment = db.relationship('TaskAssignment', foreign_keys=[assignment_id], backref='submission_records')
    submitter = db.relationship('User', backref='task_submissions')
    task_item = db.relationship(
        'TaskItem',
        foreign_keys=[task_item_id],
        primaryjoin='TaskSubmission.task_item_id == TaskItem.id',
    )


class TaskSubmissionFile(db.Model):
    __tablename__ = 'task_submission_file'

    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('task_submission.id'), nullable=False, index=True)
    original_name = db.Column(db.String(255))
    stored_name = db.Column(db.String(255))
    stored_path = db.Column(db.String(500))
    file_ext = db.Column(db.String(20))
    mime_type = db.Column(db.String(100))
    file_size = db.Column(db.Integer)
    is_signed = db.Column(db.Boolean, default=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.now)

    submission = db.relationship('TaskSubmission', backref='files')


class TaskFormField(db.Model):
    __tablename__ = 'task_form_field'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=False, index=True)
    task_item_id = db.Column(db.Integer, db.ForeignKey('task_item.id'), index=True)
    field_key = db.Column(db.String(100), nullable=False)
    field_label = db.Column(db.String(255), nullable=False)
    field_type = db.Column(db.String(50), default='text')
    field_options_json = db.Column(db.Text)
    sort_order = db.Column(db.Integer, default=0)
    is_required = db.Column(db.Boolean, default=False)

    task_item = db.relationship('TaskItem', backref='form_fields')


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
    created_by = db.Column(db.Integer, index=True)  # User.id — người tạo (object-level control)
    uploaded_at = db.Column(db.DateTime, default=datetime.now)


class NotificationDoc(db.Model):
    """
    Bản tin / tài liệu thông báo gộp từ Bảng tin (NewsDoc) và Thư viện (DocumentLib).
    Hỗ trợ gắn tệp Word/Excel/PDF/video để xem trực tiếp.
    """
    __tablename__ = 'notification_doc'

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), default='notice')  # notice: bản tin | document: tài liệu
    title = db.Column(db.String(255))
    category = db.Column(db.String(100))
    content = db.Column(db.Text)
    description = db.Column(db.Text)
    target_scope = db.Column(db.String(50), default='Toàn tỉnh')
    filename = db.Column(db.String(255))
    file_ext = db.Column(db.String(20))
    video_url = db.Column(db.String(500))
    has_attachment = db.Column(db.Boolean, default=False)
    posted_by = db.Column(db.String(100))
    created_by = db.Column(db.Integer, index=True)  # User.id — người tạo (object-level control)
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



class CustomSatellitePoint(db.Model):
    __tablename__ = 'custom_satellite_point'

    id = db.Column(db.Integer, primary_key=True)
    route_id = db.Column(db.String(100), nullable=False)
    key = db.Column(db.String(255), unique=True, index=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(50))
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    parent_key = db.Column(db.String(255), nullable=False)
