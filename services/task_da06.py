# -*- coding: utf-8 -*-
"""
Báo cáo Đề án 06 (DA06) hằng tháng: nhận diện nhiệm vụ DA06, phân loại người báo
cáo (Sở/ngành, Tổ công tác cấp xã, Trung tâm PVHCC), dựng biểu mẫu và màn quản lý
theo nhóm đơn vị.

Tách từ routes/tasks.py (Pha 2). routes/tasks.py vẫn re-export toàn bộ tên cũ.
"""

from werkzeug.utils import secure_filename

from services.task_modes import COMPLETED_STATUS, IN_PROGRESS_STATUS, _normalize_status
from services.task_runtime_sync import _parse_assignment_payload
from services.task_units import _task_unit_identity
from utils import remove_accents

DA06_TASK_MARKERS = ("bao cao de an 06 thang", "bao cao de an06 thang", "bao cao da06 thang")
DA06_TCT_ROLE_MARKERS = ("to cong tac cap xa",)
DA06_TTPVHCC_USERNAME = "ttpvhcctq"
DA06_SO_NGANH_RULES = [
    {"unit_markers": ("bao hiem xa hoi", "bhxh"), "label": "Lĩnh vực Bảo hiểm xã hội", "dvc_titles": ["Giải quyết hưởng trợ cấp thất nghiệp", "Đăng ký tham gia đóng bảo hiểm xã hội tự nguyện", "Đăng ký đóng, cấp thẻ bảo hiểm y tế", "Giải quyết hưởng bảo hiểm xã hội một lần", "Giải quyết hưởng chế độ ốm đau, thai sản, trợ cấp dưỡng sức phục hồi sức khỏe"]},
    {"unit_markers": ("thue",), "label": "Lĩnh vực Thuế", "dvc_titles": ["Đăng ký thuế lần đầu, đăng ký thay đổi thông tin đăng ký thuế đối với người nộp thuế là hộ gia đình, cá nhân", "Thanh toán nghĩa vụ tài chính trong thực hiện thủ tục hành chính về đất đai đối với hộ gia đình, cá nhân", "Thanh toán nghĩa vụ tài chính trong thực hiện thủ tục hành chính về đất đai đối với doanh nghiệp", "Nộp thuế, lệ phí trước bạ đối với doanh nghiệp", "Liên thông các thủ tục Đăng ký thành lập hợp tác xã/liên hiệp hợp tác xã và đăng ký thuế", "Nhóm thủ tục Đăng ký thành lập hộ kinh doanh và Đăng ký thuế", "Thanh toán trực tuyến nghĩa vụ tài chính nộp thuế, lệ phí trước bạ đối với hợp tác xã, doanh nghiệp trong thực hiện thủ tục hành chính về đất đai"]},
    {"unit_markers": ("tu phap",), "label": "Lĩnh vực Tư pháp", "dvc_titles": ["Đăng ký khai sinh", "Đăng ký khai tử", "Đăng ký kết hôn", "Liên thông đăng ký khai sinh đăng ký thường trú - cấp thẻ bảo hiểm y tế cho trẻ dưới 6 tuổi", "Liên thông đăng ký khai tử - Xóa đăng ký thường trú - Trợ cấp mai táng phí", "Nhóm thủ tục cấp Giấy xác nhận tình trạng hôn nhân và Đăng ký kết hôn", "Nhóm thủ tục thay đổi, cải chính, bổ sung thông tin hộ tịch - Điều chỉnh thông tin về cư trú trong Cơ sở dữ liệu về cư trú - Cấp lại thẻ Căn cước công dân / Đổi thẻ Căn cước công dân"]},
    {"unit_markers": ("giao duc", "dao tao"), "label": "Lĩnh vực Giáo dục và Đào tạo", "dvc_titles": ["Đăng kí dự thi tốt nghiệp THPT quốc gia và xét tuyển đại học, cao đẳng", "Công nhận bằng tốt nghiệp trung học cơ sở, bằng tốt nghiệp trung học phổ thông, giấy chứng nhận hoàn thành chương trình giáo dục phổ thông do cơ sở giáo dục nước ngoài cấp để sử dụng tại Việt Nam"]},
    {"unit_markers": ("nong nghiep", "moi truong", "tai nguyen"), "label": "Lĩnh vực Nông nghiệp và Môi trường", "dvc_titles": ["Đăng ký biến động đối với trường hợp đổi tên hoặc thay đổi thông tin về người sử dụng đất", "Đăng ký biến động quyền sử dụng đất, quyền sở hữu tài sản gắn liền với đất trong các trường hợp chuyển đổi, chuyển nhượng, cho thuê, cho thuê lại, thừa kế, tặng cho, góp vốn bằng quyền sử dụng đất"]},
    {"unit_markers": ("cong thuong", "dien luc"), "label": "Lĩnh vực Công Thương", "dvc_titles": ["Cấp điện mới từ lưới điện hạ áp (220/380V)", "Mở rộng việc kết nối, chia sẻ dữ liệu dân cư của Cơ sở dữ liệu quốc gia về dân cư để thực hiện các dịch vụ cung cấp điện còn lại", "Thay đổi chủ thể hợp đồng mua bán điện", "Kết nối, chia sẻ dữ liệu doanh nghiệp của Cơ sở dữ liệu quốc gia về đăng ký doanh nghiệp để thực hiện các dịch vụ cung cấp điện cho doanh nghiệp"]},
    {"unit_markers": ("noi vu",), "label": "Lĩnh vực Nội vụ", "dvc_titles": ["Thăm viếng mộ liệt sĩ"]},
    {"unit_markers": ("toa an",), "label": "Lĩnh vực Tòa án", "dvc_titles": ["Thu, nộp tạm ứng án phí, lệ phí tòa án"]},
    {"unit_markers": ("y te",), "label": "Lĩnh vực Y tế", "dvc_titles": []},
]


def _is_da06_month_task(task):
    text = remove_accents(f"{getattr(task, 'title', '')} {getattr(task, 'content', '')}").strip().lower()
    return any(marker in text for marker in DA06_TASK_MARKERS)

def _normalized_text(value):
    return remove_accents(value or "").strip().lower()

def _da06_user_profile(user):
    username = (getattr(user, "username", None) or "").strip().lower()
    role_name = _normalized_text(getattr(getattr(user, "role", None), "name", None) or "")
    unit_name = _normalized_text(getattr(user, "unit_area_display", None) or getattr(user, "unit_area", None) or "")
    if username == DA06_TTPVHCC_USERNAME:
        return {"kind": "tthcc", "label": "Trung tâm Phục vụ hành chính công"}
    if any(marker in role_name for marker in DA06_TCT_ROLE_MARKERS):
        return {"kind": "tct_xa", "label": "Tổ công tác cấp xã"}
    for rule in DA06_SO_NGANH_RULES:
        if any(marker in unit_name for marker in rule["unit_markers"]):
            return {"kind": "so_nganh", "label": rule["label"], "rule": rule}
    return {"kind": "so_nganh", "label": "Sở, ban, ngành", "rule": None}

def _da06_tct_sections(payload):
    attachments = payload.get("attachments", {}) if isinstance(payload.get("attachments"), dict) else {}
    return [
        {"key": "tuyen_truyen_total", "label": "Tổng số lượt tuyên truyền", "type": "number", "value": payload.get("tuyen_truyen_total", "")},
        {"key": "tuyen_truyen_forms", "label": "Hình thức tuyên truyền", "type": "textarea", "value": payload.get("tuyen_truyen_forms", "")},
        {"key": "current_tasks", "label": "Các nhiệm vụ hiện hành", "type": "textarea", "value": payload.get("current_tasks", "")},
        {"key": "van_ban_y_kien_count", "label": "Số văn bản tham gia ý kiến", "type": "number", "value": payload.get("van_ban_y_kien_count", "")},
        {"key": "van_ban_chi_dao", "label": "Các văn bản chỉ đạo triển khai thực hiện", "type": "textarea", "value": payload.get("van_ban_chi_dao", "")},
        {"key": "tuyen_truyen_attachment", "label": "Tài liệu minh chứng tuyên truyền", "type": "file", "value": attachments.get("tuyen_truyen_attachment", "")},
        {"key": "van_ban_y_kien_attachment", "label": "Tài liệu minh chứng văn bản tham gia ý kiến", "type": "file", "value": attachments.get("van_ban_y_kien_attachment", "")},
        {"key": "van_ban_chi_dao_attachment", "label": "Tài liệu minh chứng văn bản chỉ đạo", "type": "file", "value": attachments.get("van_ban_chi_dao_attachment", "")},
    ]

def _da06_so_nganh_dvc_rows(rule, payload):
    existing = payload.get("dvc_items", {}) if isinstance(payload.get("dvc_items"), dict) else {}
    rows = []
    for title in (rule or {}).get("dvc_titles", []):
        item_payload = existing.get(title, {}) if isinstance(existing.get(title), dict) else {}
        item_key = secure_filename(remove_accents(title).replace(" ", "_")) or f"dvc_{len(rows) + 1}"
        rows.append(
            {
                "title": title,
                "item_key": item_key,
                "fields": [
                    {"key": "total", "label": "Tổng số hồ sơ", "value": item_payload.get("total", "")},
                    {"key": "online", "label": "Trực tuyến", "value": item_payload.get("online", "")},
                    {"key": "rate", "label": "Tỷ lệ (%)", "value": item_payload.get("rate", "")},
                    {"key": "data_source", "label": "Nguồn dữ liệu kết nối, chia sẻ", "value": item_payload.get("data_source", "")},
                    {"key": "benefit", "label": "Người dân được hưởng lợi", "value": item_payload.get("benefit", "")},
                    {"key": "issues", "label": "Tồn tại", "value": item_payload.get("issues", "")},
                    {"key": "solution", "label": "Giải pháp", "value": item_payload.get("solution", "")},
                ],
            }
        )
    return rows

def _build_da06_task_form(task, user_assign, current_user):
    if not task or not user_assign or not current_user or not _is_da06_month_task(task):
        return None
    payload = _parse_assignment_payload(user_assign)
    profile = _da06_user_profile(current_user)
    form = {
        "kind": profile["kind"],
        "label": profile["label"],
        "narrative_value": payload.get("narrative_report", ""),
        "dvc_rows": [],
        "tct_fields": [],
        "tthcc_attachment": ((payload.get("attachments") or {}) if isinstance(payload.get("attachments"), dict) else {}).get("phu_luc_2_attachment", ""),
        "updated_at": payload.get("updated_at", ""),
    }
    if profile["kind"] == "tct_xa":
        form["tct_fields"] = _da06_tct_sections(payload)
    elif profile["kind"] == "tthcc":
        form["tthcc_note"] = payload.get("tthcc_note", "")
    else:
        rule = profile.get("rule")
        form["dvc_rows"] = _da06_so_nganh_dvc_rows(rule, payload)
    return form

def _has_da06_value(value):
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_has_da06_value(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_da06_value(item) for item in value)
    return True

def _build_da06_management_view(assigns):
    group_map = {}
    for assignment, user in assigns or []:
        if not user:
            continue

        profile = _da06_user_profile(user)
        unit_identity = _task_unit_identity(user)
        unit_key = unit_identity["unit_key"] or unit_identity["unit_name"].lower()
        group_key = profile["kind"]
        group = group_map.setdefault(
            group_key,
            {
                "key": group_key,
                "label": profile["label"],
                "units": {},
                "total_units": 0,
                "reported_units": 0,
            },
        )

        payload = _parse_assignment_payload(assignment)
        attachments = payload.get("attachments", {}) if isinstance(payload.get("attachments"), dict) else {}
        unit = group["units"].setdefault(
            unit_key,
            {
                "unit_name": unit_identity["unit_name"],
                "status": "Chưa tiếp nhận",
                "has_report": False,
                "updated_at": None,
                "summary_lines": [],
            },
        )

        normalized_status = _normalize_status(getattr(assignment, "status", ""))
        if normalized_status == COMPLETED_STATUS:
            unit["status"] = COMPLETED_STATUS
        elif normalized_status == IN_PROGRESS_STATUS and unit["status"] != COMPLETED_STATUS:
            unit["status"] = IN_PROGRESS_STATUS

        report_lines = []
        has_report = False
        if profile["kind"] == "tct_xa":
            has_report = any(
                _has_da06_value(payload.get(key))
                for key in [
                    "tuyen_truyen_total",
                    "tuyen_truyen_forms",
                    "current_tasks",
                    "van_ban_y_kien_count",
                    "van_ban_chi_dao",
                ]
            ) or bool(attachments)
            attachment_count = sum(1 for key in ["tuyen_truyen_attachment", "van_ban_y_kien_attachment", "van_ban_chi_dao_attachment"] if attachments.get(key))
            report_lines = [
                f"Tuyên truyền: {payload.get('tuyen_truyen_total') or '0'} lượt",
                f"Văn bản tham gia ý kiến: {payload.get('van_ban_y_kien_count') or '0'}",
                f"Minh chứng: {attachment_count}/3 tệp",
            ]
        elif profile["kind"] == "tthcc":
            note_ready = _has_da06_value(payload.get("tthcc_note"))
            appendix_ready = bool(attachments.get("phu_luc_2_attachment"))
            has_report = note_ready or appendix_ready
            report_lines = [
                f"Ghi chú tổng hợp: {'Đã cập nhật' if note_ready else 'Chưa cập nhật'}",
                f"Phụ lục 2: {'Đã tải lên' if appendix_ready else 'Chưa tải lên'}",
            ]
        else:
            dvc_items = payload.get("dvc_items", {}) if isinstance(payload.get("dvc_items"), dict) else {}
            dvc_total = len((profile.get("rule") or {}).get("dvc_titles", []))
            dvc_ready = 0
            for item in dvc_items.values():
                if isinstance(item, dict) and any(_has_da06_value(value) for value in item.values()):
                    dvc_ready += 1
            narrative_ready = _has_da06_value(payload.get("narrative_report"))
            has_report = narrative_ready or dvc_ready > 0
            report_lines = [
                f"Báo cáo lời: {'Đã cập nhật' if narrative_ready else 'Chưa cập nhật'}",
                f"DVC: {dvc_ready}/{dvc_total}" if dvc_total else "DVC: Không áp dụng",
            ]

        if has_report:
            unit["has_report"] = True
        updated_at = getattr(assignment, "updated_at", None)
        if updated_at and (unit["updated_at"] is None or updated_at > unit["updated_at"]):
            unit["updated_at"] = updated_at
            unit["summary_lines"] = report_lines

    groups = []
    for group in group_map.values():
        units = sorted(group["units"].values(), key=lambda item: item["unit_name"].lower())
        group["units"] = units
        group["total_units"] = len(units)
        group["reported_units"] = sum(1 for item in units if item["has_report"])
        groups.append(group)

    groups.sort(key=lambda item: item["label"].lower())
    return groups
