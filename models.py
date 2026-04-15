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


# --- BÌNH DÂN HỌC VỤ MODELS ---

class BDHV_HocVien(db.Model):
    """Học viên Bình dân học vụ"""
    __tablename__ = 'bdhv_hocvien'
    id = db.Column(db.Integer, primary_key=True)
    stt = db.Column(db.Integer)
    ho_ten = db.Column(db.String(255))      # Cột B
    cccd = db.Column(db.String(20))          # Cột C - CCCD/Căn cước
    don_vi = db.Column(db.String(255))       # Cột D - Đơn vị
    ghi_chu = db.Column(db.String(255))     # Cột E
    diem_hoc = db.Column(db.Float, default=0)  # Cột F - Điểm học (%)
    diem_thi = db.Column(db.Float, default=0)   # Cột G - Điểm thi (%)
    ket_qua = db.Column(db.String(50))       # Cột H - Kết quả
    nguon = db.Column(db.String(20))        # 'DS HV' hoặc 'DKMoi'
    created_at = db.Column(db.DateTime, default=datetime.now)


class BDHV_DonVi(db.Model):
    """Danh sách đơn vị (xã/phường)"""
    __tablename__ = 'bdhv_donvi'
    id = db.Column(db.Integer, primary_key=True)
    ten_don_vi = db.Column(db.String(255), unique=True)
    created_at = db.Column(db.DateTime, default=datetime.now)


class BDHV_ThongKe(db.Model):
    """Thống kê theo đơn vị"""
    __tablename__ = 'bdhv_thongke'
    id = db.Column(db.Integer, primary_key=True)
    ten_don_vi = db.Column(db.String(255))
    tong_18 = db.Column(db.Integer, default=0)       # Tổng dân số 18+
    da_dang_ky = db.Column(db.Integer, default=0)    # Đã đăng ký
    da_hoan_thanh = db.Column(db.Integer, default=0)  # Đã hoàn thành
    diem_thi = db.Column(db.Integer, default=0)       # Số người thi
    ty_le = db.Column(db.Float, default=0)            # Tỷ lệ %
    created_at = db.Column(db.DateTime, default=datetime.now)


class BDHV_DangKyMoi(db.Model):
    """Đăng ký mới học viên"""
    __tablename__ = 'bdhv_dangky'
    id = db.Column(db.Integer, primary_key=True)
    stt = db.Column(db.Integer)
    ho_ten = db.Column(db.String(255))
    cccd = db.Column(db.String(20))
    don_vi = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.now)


class BDHV_ThiLai(db.Model):
    """Đăng ký thi lại"""
    __tablename__ = 'bdhv_thilai'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    ho_ten = db.Column(db.String(255))
    cccd = db.Column(db.String(20))
    don_vi = db.Column(db.String(255))
    ly_do = db.Column(db.Text)


class BDHV_PhucTra(db.Model):
    """Phúc tra kết quả"""
    __tablename__ = 'bdhv_phuctra'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    ho_ten = db.Column(db.String(255))
    cccd = db.Column(db.String(20))
    don_vi = db.Column(db.String(255))
    ly_do = db.Column(db.Text)
    file_url = db.Column(db.Text)


class BDHV_DauMoi(db.Model):
    """Danh sách đầu mối liên lạc"""
    __tablename__ = 'bdhv_daumoi'
    id = db.Column(db.Integer, primary_key=True)
    don_vi = db.Column(db.String(255))
    ten = db.Column(db.String(255))
    phone = db.Column(db.String(20))
    chuc_vu = db.Column(db.String(100))

