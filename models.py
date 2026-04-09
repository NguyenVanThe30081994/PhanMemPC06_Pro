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


class CategoryGroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)
    linked_modules = db.Column(db.Text) # Comma-separated or JSON list of topbar labels


class CategoryItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('category_group.id'))
    name = db.Column(db.String(255))
    group = db.relationship('CategoryGroup', backref='items')


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, index=True)
    password_hash = db.Column(db.String(128))
    fullname = db.Column(db.String(100))
    role_id = db.Column(db.Integer, db.ForeignKey('app_role.id'))
    unit_area = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    must_change_password = db.Column(db.Boolean, default=True)
    role = db.relationship('AppRole', backref='users')
    def set_password(self, p): self.password_hash = generate_password_hash(p)
    def check_password(self, p): return check_password_hash(self.password_hash, p)


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.String(100)) 
    title = db.Column(db.String(255))
    content = db.Column(db.Text)
    deadline = db.Column(db.Date)
    file_path = db.Column(db.String(255))
    author_id = db.Column(db.Integer)
    author_name = db.Column(db.String(100))
    priority = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.now)
    assignments = db.relationship('TaskAssignment', backref='task', cascade='all, delete-orphan')


class TaskAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    status = db.Column(db.String(50), default='Chưa bắt đầu')
    result_file = db.Column(db.String(255))
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


class ReportConfig(db.Model):
    id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(255))
    description = db.Column(db.Text)
    domain = db.Column(db.String(100)) 
    file_blob = db.Column(db.LargeBinary)
    config_json = db.Column(db.Text)
    header_start = db.Column(db.Integer, default=1)
    header_rows = db.Column(db.Integer, default=1)
    is_daily = db.Column(db.Boolean, default=False)
    author_name = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.now)


class ReportData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.String(50))
    user_id = db.Column(db.Integer)
    data_json = db.Column(db.Text)
    report_date = db.Column(db.Date)


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


class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer)
    sender_name = db.Column(db.String(100))
    scope = db.Column(db.String(20))
    target_id = db.Column(db.String(50))
    message = db.Column(db.Text)
    file_path = db.Column(db.String(255))
    real_filename = db.Column(db.String(255))
    file_type = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.now)


class SystemLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    fullname = db.Column(db.String(100))
    module = db.Column(db.String(100))
    action = db.Column(db.String(255))
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)


# --- REPORT V2 MODELS ---

class ReportTemplateV2(db.Model):
    __tablename__ = 'report_template_v2'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    created_by = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.now)
    is_active = db.Column(db.Boolean, default=True)
    is_daily = db.Column(db.Boolean, default=False)


class ReportVersionV2(db.Model):
    __tablename__ = 'report_version_v2'

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('report_template_v2.id'))
    version_tag = db.Column(db.String(20))  # e.g. "v1.0", "2024-Q1"
    metadata_json = db.Column(db.Text)  # Storing the parsed Excel structure
    excel_file_blob = db.Column(db.LargeBinary)  # Original template
    created_at = db.Column(db.DateTime, default=datetime.now)
    is_published = db.Column(db.Boolean, default=False)

    template = db.relationship('ReportTemplateV2', backref='versions')


class ReportSubmissionV2(db.Model):
    __tablename__ = 'report_submission_v2'

    id = db.Column(db.Integer, primary_key=True)
    version_id = db.Column(db.Integer, db.ForeignKey('report_version_v2.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    org_unit = db.Column(db.String(100))
    period_name = db.Column(db.String(100))  # e.g. "Tuần 14-2024"
    status = db.Column(db.String(20), default='draft')  # draft, submitted, rejected, approved
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    version = db.relationship('ReportVersionV2', backref='submissions')
    user = db.relationship('User', backref='submissions_v2')
    values = db.relationship('ReportValueV2', backref='submission', cascade='all, delete-orphan')


class ReportValueV2(db.Model):
    __tablename__ = 'report_value_v2'

    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('report_submission_v2.id'))
    cell_key = db.Column(db.String(50))  # e.g. "B5" or Named Range
    value = db.Column(db.Text)


class ReportAuditV2(db.Model):
    __tablename__ = 'report_audit_v2'

    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('report_submission_v2.id'))
    user_id = db.Column(db.Integer)
    cell_key = db.Column(db.String(50))
    old_value = db.Column(db.Text)
    new_value = db.Column(db.Text)
    changed_at = db.Column(db.DateTime, default=datetime.now)

# --- SHORT URL / QR GENERATOR MODELS ---

class ShortLink(db.Model):
    __tablename__ = 'short_link'

    id = db.Column(db.Integer, primary_key=True)
    short_code = db.Column(db.String(50), unique=True, index=True)
    original_url = db.Column(db.Text, nullable=False)
    custom_name = db.Column(db.String(100))
    info = db.Column(db.Text)
    clicks = db.Column(db.Integer, default=0)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    user = db.relationship('User', backref='short_links')


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
