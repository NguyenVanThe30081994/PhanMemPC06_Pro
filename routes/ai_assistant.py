# -*- coding: utf-8 -*-
from flask import Blueprint, request, session, jsonify, redirect, url_for
import os
import requests
import re
import unicodedata
import time
import html
from datetime import datetime, timedelta
from urllib.parse import quote
from utils import render_auto_template as render_template
from models import AIAssistantConfig

ai_bp = Blueprint('ai_bp', __name__, url_prefix='/ai')


AI_PROVIDER_DEFAULTS = {
    'deepseek': 'deepseek-v4-flash',
    'gemini': 'gemini-2.5-flash',
    'openai': 'gpt-4.1-mini',
    'groq': 'llama-3.3-70b-versatile',
}

AI_PROVIDER_LABELS = {
    'deepseek': 'DeepSeek V4 Flash',
    'gemini': 'Gemini 2.5 Flash',
    'openai': 'GPT-4.1 mini',
    'groq': 'Llama 3.3 70B trên Groq',
}

SUGGESTED_TOPICS = [
    {'icon': 'fa-solid fa-id-card', 'title': 'Căn cước công dân', 'prompt': 'Làm căn cước công dân cần chuẩn bị gì?'},
    {'icon': 'fa-solid fa-house-user', 'title': 'Đăng ký thường trú', 'prompt': 'Hồ sơ đăng ký thường trú thường gồm những gì?'},
    {'icon': 'fa-solid fa-house-chimney', 'title': 'Đăng ký tạm trú', 'prompt': 'Đăng ký tạm trú cần giấy tờ gì?'},
    {'icon': 'fa-solid fa-passport', 'title': 'Hộ chiếu', 'prompt': 'Xin cấp hộ chiếu phổ thông nộp ở đâu?'},
    {'icon': 'fa-solid fa-shield-heart', 'title': 'BHYT hộ gia đình', 'prompt': 'Mua BHYT hộ gia đình cần chuẩn bị gì?'},
    {'icon': 'fa-solid fa-life-ring', 'title': 'Thông tin đời sống', 'prompt': 'Tôi muốn hỏi thông tin đời sống dân sinh và nơi liên hệ phù hợp.'},
]

WELCOME_MESSAGE = (
    "Trung tâm hỗ trợ thủ tục PC06.\n\n"
    "- Phạm vi tra cứu: thủ tục hành chính, giấy tờ thường gặp, nơi tiếp nhận và thời gian làm việc.\n"
    "- Kết quả có giá trị tham khảo; nội dung thay đổi theo thời điểm cần đối chiếu nguồn chính thức.\n"
    "- Nhập ngắn gọn nội dung cần tra cứu."
)

AI_SYSTEM_PROMPT = """Bạn là mô-đun hỗ trợ tra cứu của PC06 Tuyên Quang.

Mục tiêu:
- Trả lời bằng tiếng Việt rõ ràng, ngắn gọn, trung tính.
- Hỗ trợ tra cứu về thủ tục hành chính, dịch vụ công, nơi liên hệ, giấy tờ thường gặp và thông tin công vụ cơ bản.
- Ưu tiên câu trả lời ngắn gọn, đúng trọng tâm, có cấu trúc rõ ràng.

Nguyên tắc trả lời:
- Nếu có đủ dữ liệu, trả lời theo cấu trúc: Nội dung chính / Hồ sơ thường gặp / Nơi tiếp nhận hoặc lưu ý.
- Nếu thủ tục có thể thay đổi theo thời điểm hoặc địa phương, phải ghi rõ đây là thông tin tham khảo và yêu cầu đối chiếu tại cổng dịch vụ công hoặc cơ quan tiếp nhận.
- Không tự bịa đặt mức phí, thời hạn, căn cứ pháp lý hoặc địa chỉ cụ thể nếu không chắc chắn.
- Khi câu hỏi mơ hồ, yêu cầu người dùng bổ sung thông tin còn thiếu.
- Không dùng giọng hội thoại xã giao. Không dài dòng.
"""

TTHC_KNOWLEDGE = {
    "căn cước công dân": {
        "answer": "Hồ sơ căn cước công dân thường gồm giấy tờ tùy thân hiện có và thông tin cư trú để đối chiếu. Thành phần hồ sơ có thể thay đổi theo từng trường hợp như cấp mới, cấp đổi hoặc cấp lại. Cần đối chiếu trước tại cơ quan công an hoặc cổng dịch vụ công.",
        "keywords": ["cccd", "căn cước", "thẻ căn cước", "làm căn cước"]
    },
    "đăng ký thường trú": {
        "answer": "Hồ sơ đăng ký thường trú thường gồm tờ khai cư trú và giấy tờ chứng minh chỗ ở hợp pháp. Tùy trường hợp, cơ quan tiếp nhận có thể yêu cầu thêm giấy tờ nhân thân hoặc giấy tờ liên quan đến chủ hộ, chủ sở hữu chỗ ở. Cần đối chiếu trước tại công an địa phương hoặc cổng dịch vụ công.",
        "keywords": ["thường trú", "đăng ký thường trú", "hộ khẩu", "cư trú"]
    },
    "đăng ký tạm trú": {
        "answer": "Đăng ký tạm trú thường cần thông tin cá nhân, giấy tờ tùy thân và giấy tờ chứng minh nơi ở hợp pháp như hợp đồng thuê, xác nhận của chủ nhà hoặc giấy tờ tương đương. Cần chuẩn bị bản gốc hoặc bản chụp rõ ràng để đối chiếu khi cần.",
        "keywords": ["tạm trú", "đăng ký tạm trú", "khai báo tạm trú", "tạm vắng"]
    },
    "lý lịch tư pháp": {
        "answer": "Hồ sơ phiếu lý lịch tư pháp thường gồm tờ khai theo mẫu và giấy tờ tùy thân hợp lệ. Tùy nơi tiếp nhận, hồ sơ có thể nộp trực tiếp hoặc trực tuyến. Trường hợp cần gấp phải xác nhận trước thời gian xử lý thực tế với cơ quan tiếp nhận.",
        "keywords": ["lý lịch tư pháp", "phiếu lý lịch", "lý lịch"]
    },
    "hộ chiếu": {
        "answer": "Hồ sơ cấp hộ chiếu phổ thông thường gồm giấy tờ tùy thân và tờ khai theo mẫu. Với một số trường hợp đặc biệt như trẻ em hoặc cấp lại, cơ quan tiếp nhận có thể yêu cầu thêm giấy tờ liên quan. Cần kiểm tra trước nơi nộp và lịch tiếp nhận.",
        "keywords": ["hộ chiếu", "passport", "xuất nhập cảnh"]
    },
    "bhyt hộ gia đình": {
        "answer": "Hồ sơ tham gia BHYT hộ gia đình thường cần thông tin nhân khẩu trong hộ và giấy tờ nhân thân của người tham gia. Mức đóng và cách kê khai có thể thay đổi theo quy định hiện hành; cần xác nhận lại với cơ quan BHXH hoặc đại lý thu.",
        "keywords": ["bhyt", "bảo hiểm y tế", "bảo hiểm hộ gia đình", "bhxh"]
    },
    "giờ làm việc": {
        "answer": "Giờ làm việc của cơ quan nhà nước thường theo giờ hành chính từ thứ hai đến thứ sáu, nhưng lịch tiếp nhận hồ sơ có thể khác theo từng đơn vị. Cần đối chiếu trước thông báo chính thức của cơ quan.",
        "keywords": ["giờ làm việc", "mấy giờ làm việc", "thời gian làm việc"]
    },
}

CANNED_RESPONSES = {
    "xin chào": "Trung tâm hỗ trợ thủ tục sẵn sàng tiếp nhận yêu cầu tra cứu. Nhập nội dung cần xử lý.",
    "cảm ơn": "Đã ghi nhận. Có thể tiếp tục nhập nội dung cần tra cứu.",
    "help": "Có thể tra cứu căn cước công dân, cư trú, hộ chiếu, lý lịch tư pháp, BHYT, thời gian làm việc, nơi tiếp nhận hồ sơ và thông tin dân sinh cơ bản.",
}

LEGAL_REFERENCE_KEYWORDS = [
    'luat',
    'bo luat',
    'nghi dinh',
    'nghi quyet',
    'thong tu',
    'quyet dinh',
    'chi thi',
    'phap lenh',
    'cong van',
    'thong bao',
]

LEGAL_DOC_TYPE_MAP = {
    'nghi dinh': 'Nghị định',
    'nghi quyet': 'Nghị quyết',
    'thong tu': 'Thông tư',
    'quyet dinh': 'Quyết định',
    'chi thi': 'Chỉ thị',
    'luat': 'Luật',
    'bo luat': 'Bộ luật',
    'phap lenh': 'Pháp lệnh',
    'cong van': 'Công văn',
    'thong bao': 'Thông báo',
}

OFFICIAL_LEGAL_SEARCH_API = 'https://genai.aiservice.vn/congbaosearch/search'
OFFICIAL_LEGAL_PORTAL_URL = 'https://vanban.chinhphu.vn/he-thong-van-ban'
OFFICIAL_LEGAL_PORTAL_RECENT_URL = 'https://vanban.chinhphu.vn/he-thong-van-ban?classid=0&mode=1&maxresults=100'
LEGAL_LIBRARY_SEARCH_URL = 'https://thuvienphapluat.vn/page/tim-van-ban.aspx?area=0&keyword='
LUAT_VIETNAM_SEARCH_URL = 'https://luatvietnam.vn/van-ban/tim-van-ban.html'
OFFICIAL_PROCEDURE_PORTAL_URL = 'https://dichvucong.gov.vn'
OFFICIAL_PROCEDURE_TYPEAHEAD_URL = 'https://dichvucong.gov.vn/jsp/procedure-typehead.jsp'
GOV_NEWS_CACHE = {
    'fetched_at': 0.0,
    'articles': None,
}
GOV_NEWS_CACHE_TTL = 15 * 60
OFFICIAL_LEGAL_PORTAL_CACHE = {
    'fetched_at': 0.0,
    'documents': None,
}
OFFICIAL_LEGAL_PORTAL_CACHE_TTL = 10 * 60
OFFICIAL_PROCEDURE_CACHE_TTL = 15 * 60
OFFICIAL_PROCEDURE_SUGGESTION_CACHE = {}
OFFICIAL_PROCEDURE_DETAIL_CACHE = {}

PROCEDURE_QUERY_MARKERS = [
    'thu tuc',
    'thu tuc hanh chinh',
    'trinh tu',
    'ho so',
    'giay to',
    'thanh phan ho so',
    'cach thuc thuc hien',
    'nop o dau',
    'lam o dau',
    'thoi han giai quyet',
    'phi',
    'le phi',
]

PROCEDURE_SEARCH_HINTS = {
    'tam tru': ['Đăng ký tạm trú'],
    'thuong tru': ['Đăng ký thường trú'],
    'khai sinh': ['Đăng ký khai sinh'],
    'khai tu': ['Đăng ký khai tử'],
    'ly lich tu phap': ['Cấp Phiếu lý lịch tư pháp theo yêu cầu của cá nhân'],
    'phieu ly lich tu phap': ['Cấp Phiếu lý lịch tư pháp theo yêu cầu của cá nhân'],
    'ho chieu': ['Cấp hộ chiếu phổ thông ở trong nước'],
    'xuat nhap canh': ['Cấp hộ chiếu phổ thông ở trong nước'],
    'can cuoc': ['Cấp thẻ căn cước cho người từ đủ 14 tuổi trở lên'],
    'cccd': ['Cấp thẻ căn cước cho người từ đủ 14 tuổi trở lên'],
}


def _get_ai_config():
    try:
        return AIAssistantConfig.query.first()
    except Exception:
        return None


def _normalize_query_text(value):
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace('đ', 'd').replace('Đ', 'D')
    text = re.sub(r'\s+', ' ', text).strip().lower()
    return text


def _get_ttl_cached_value(cache_store, cache_key, ttl):
    entry = cache_store.get(cache_key)
    if not entry:
        return None
    if (time.monotonic() - float(entry.get('fetched_at') or 0.0)) >= ttl:
        cache_store.pop(cache_key, None)
        return None
    return entry.get('data')


def _set_ttl_cached_value(cache_store, cache_key, data):
    cache_store[cache_key] = {
        'fetched_at': time.monotonic(),
        'data': data,
    }


def _clean_html_text(fragment):
    text = html.unescape(str(fragment or ''))
    replacements = (
        (r'(?i)<br\s*/?>', '\n'),
        (r'(?i)</p>', '\n'),
        (r'(?i)</div>', '\n'),
        (r'(?i)</tr>', '\n'),
        (r'(?i)</td>', ' | '),
        (r'(?i)<li[^>]*>', '- '),
        (r'(?i)</li>', '\n'),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = text.replace('\xa0', ' ')
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n[ \t]+', '\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip(' |\n ')


def _truncate_text(text, limit=320):
    value = re.sub(r'\s+', ' ', str(text or '')).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip(' ,.;:') + '…'


def _format_vi_datetime(dt):
    weekdays = [
        'Thứ hai',
        'Thứ ba',
        'Thứ tư',
        'Thứ năm',
        'Thứ sáu',
        'Thứ bảy',
        'Chủ nhật',
    ]
    weekday_label = weekdays[dt.weekday()]
    return {
        'weekday': weekday_label,
        'date_text': f"{dt.day:02d}/{dt.month:02d}/{dt.year}",
        'full_date_text': f"{weekday_label}, ngày {dt.day:02d} tháng {dt.month:02d} năm {dt.year}",
        'time_text': f"{dt.hour:02d}:{dt.minute:02d}",
    }


def _is_time_query(query):
    normalized = _normalize_query_text(query)
    date_markers = [
        'hom nay',
        'hom qua',
        'ngay mai',
        'bay gio',
        'may gio',
        'gio hien tai',
        'ngay bao nhieu',
        'thu may',
        'thu may hom nay',
    ]
    return any(marker in normalized for marker in date_markers)


def _build_time_answer(query):
    normalized = _normalize_query_text(query)
    now = datetime.now()

    if 'hom qua' in normalized:
        target = now - timedelta(days=1)
        info = _format_vi_datetime(target)
        return f"Theo giờ hệ thống, hôm qua là {info['full_date_text']}."

    if 'ngay mai' in normalized:
        target = now + timedelta(days=1)
        info = _format_vi_datetime(target)
        return f"Theo giờ hệ thống, ngày mai là {info['full_date_text']}."

    info = _format_vi_datetime(now)
    if 'bay gio' in normalized or 'may gio' in normalized or 'gio hien tai' in normalized:
        return (
            f"Theo giờ hệ thống, bây giờ là {info['time_text']} ngày {info['date_text']} "
            f"({info['weekday']})."
        )

    return f"Theo giờ hệ thống, hôm nay là {info['full_date_text']}."


def _is_specific_legal_reference_query(query):
    normalized = _normalize_query_text(query)
    has_keyword = any(keyword in normalized for keyword in LEGAL_REFERENCE_KEYWORDS)
    has_van_ban_marker = 'van ban' in normalized

    has_reference_number = bool(re.search(r'\bso\s*\d{1,4}\b', normalized))
    has_number_year = bool(re.search(r'\b\d{1,4}\s*(/|-)\s*(19|20)\d{2}\b', normalized))
    has_named_number_year = bool(re.search(r'\b\d{1,4}\b.*\b(19|20)\d{2}\b', normalized))
    has_year_phrase = bool(re.search(r'\bnam\s*(19|20)\d{2}\b', normalized))
    has_bare_number = bool(re.search(r'\b\d{1,4}\b', normalized))
    has_doc_symbol = bool(re.search(r'\b\d{1,4}(?:/[a-z0-9\-]+){1,4}\b', normalized))
    has_issue_date = bool(re.search(r'\b\d{1,2}/\d{1,2}/(19|20)\d{2}\b', normalized))

    if has_keyword:
        return has_number_year or has_reference_number or (has_year_phrase and has_bare_number) or has_named_number_year or has_doc_symbol

    if has_van_ban_marker and (has_doc_symbol or has_issue_date or has_number_year or has_named_number_year):
        return True

    return False


def _extract_legal_doc_type(query):
    normalized = _normalize_query_text(query)
    for keyword, label in sorted(LEGAL_DOC_TYPE_MAP.items(), key=lambda item: len(item[0]), reverse=True):
        if keyword in normalized:
            return label
    return ''


def _extract_legal_reference_number_year(query):
    normalized = _normalize_query_text(query)
    symbol_candidates = _extract_doc_symbol_candidates(query)
    if symbol_candidates:
        first_symbol = symbol_candidates[0]
        number_match = re.match(r'^\s*(\d{1,4})\b', first_symbol)
        year_match = re.search(r'/(19|20)\d{2}\b', first_symbol)
        if number_match:
            return number_match.group(1), year_match.group(0).lstrip('/') if year_match else ''

    match = re.search(r'(?<![\d/])(\d{1,4})\s*(?:/|-|\s+nam\s+)(19|20)\d{2}\b', normalized)
    if match:
        number = match.group(1)
        year_match = re.search(r'(19|20)\d{2}', match.group(0))
        if year_match:
            return number, year_match.group(0)

    normalized_without_dates = re.sub(r'\b\d{1,2}/\d{1,2}/(19|20)\d{2}\b', ' ', normalized)
    year_match = re.search(r'\b(19|20)\d{2}\b', normalized)
    number_match = re.search(r'\b(\d{1,4})\b', normalized_without_dates)
    if number_match and year_match:
        return number_match.group(1), year_match.group(0)
    return '', ''


def _build_legal_search_payload(query):
    doc_type = _extract_legal_doc_type(query)
    payload = {
        'filters': {
            'filters_mode': 'or',
        },
        'page': 1,
        'page_size': 5,
        'query': query.strip(),
    }
    if doc_type:
        payload['filters']['ten_loai_van_ban'] = [doc_type]
    return payload


def _extract_issue_year(query):
    text = str(query or '')
    match = re.search(r'\b(19|20)\d{2}\b', text)
    return match.group(0) if match else '0'


def _extract_doc_symbol_candidates(query):
    text = str(query or '')
    candidates = []

    for match in re.finditer(r'\b\d{1,4}(?:/[A-Za-z0-9Đđ\-]+){1,5}\b', text):
        symbol = re.sub(r'\s+', '', match.group(0).strip(' .,;:()[]{}'))
        if re.fullmatch(r'\d{1,2}/\d{1,2}/(19|20)\d{2}', symbol):
            continue
        if symbol and symbol not in candidates:
            candidates.append(symbol)

    return candidates[:5]


def _extract_issue_date(query):
    match = re.search(r'\b(\d{1,2}/\d{1,2}/(19|20)\d{2})\b', str(query or ''))
    if not match:
        return ''
    try:
        return datetime.strptime(match.group(1), '%d/%m/%Y').strftime('%d/%m/%Y')
    except ValueError:
        parts = match.group(1).split('/')
        if len(parts) == 3:
            return f"{int(parts[0]):02d}/{int(parts[1]):02d}/{parts[2]}"
    return match.group(1)


def _extract_portal_hidden_fields(html_text):
    field_names = (
        '__VIEWSTATE',
        '__VIEWSTATEGENERATOR',
        '__EVENTVALIDATION',
        'ctrl_191017_163$hidSiteId',
        'ctrl_191017_163$hidIsSearch',
        'ctrl_191017_163$hiIsTrangTTG',
    )
    payload = {}
    for field_name in field_names:
        pattern = rf'name="{re.escape(field_name)}"[^>]*value="([^"]*)"'
        match = re.search(pattern, html_text)
        if match:
            payload[field_name] = html.unescape(match.group(1))
    return payload


def _extract_portal_documents(html_text):
    table_match = re.search(
        r'<table class="table search-result".*?id="ctrl_191017_163_grvDocument".*?>(.*?)</table>',
        html_text,
        re.IGNORECASE | re.DOTALL,
    )
    if not table_match:
        return []

    rows_html = table_match.group(1)
    row_matches = re.findall(r'<tr>(.*?)</tr>', rows_html, re.IGNORECASE | re.DOTALL)
    documents = []

    for row_html in row_matches:
        if 'scope="col"' in row_html:
            continue

        doc_match = re.search(
            r"href='/?\?pageid=27160&docid=(\d+)&classid=(\d+)'.*?"
            r'<span class="code">(.*?)</span>.*?'
            r'<span class="issue-v2">(.*?)</span>.*?'
            r'<span class="substract">(.*?)</span>',
            row_html,
            re.IGNORECASE | re.DOTALL,
        )
        if not doc_match:
            continue

        attachment_match = re.search(
            r'<div class="bl-doc-file"><a href="([^"]+)"',
            row_html,
            re.IGNORECASE | re.DOTALL,
        )
        document = {
            'id_van_ban': doc_match.group(1).strip(),
            'classid': doc_match.group(2).strip(),
            'so_ky_hieu': html.unescape(re.sub(r'<[^>]+>', '', doc_match.group(3))).strip(),
            'ngay_ban_hanh': doc_match.group(4).strip(),
            'tieu_de': html.unescape(re.sub(r'<[^>]+>', ' ', doc_match.group(5))).strip(),
            'trich_yeu': html.unescape(re.sub(r'<[^>]+>', ' ', doc_match.group(5))).strip(),
            'portal_url': f"https://vanban.chinhphu.vn/?pageid=27160&docid={doc_match.group(1).strip()}&classid={doc_match.group(2).strip()}",
            'source': 'vanban.chinhphu.vn',
        }
        if attachment_match:
            document['attachment_url'] = attachment_match.group(1).strip()
        documents.append(document)

    return documents


def _fetch_official_portal_recent_documents(limit=100):
    now = time.monotonic()
    cached_documents = OFFICIAL_LEGAL_PORTAL_CACHE.get('documents') or []
    cached_at = float(OFFICIAL_LEGAL_PORTAL_CACHE.get('fetched_at') or 0.0)
    if cached_documents and (now - cached_at) < OFFICIAL_LEGAL_PORTAL_CACHE_TTL:
        return cached_documents[:limit]

    response = requests.get(
        OFFICIAL_LEGAL_PORTAL_RECENT_URL,
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'vi-VN,vi;q=0.9',
        },
        timeout=15,
    )
    response.raise_for_status()
    documents = _extract_portal_documents(response.text)
    if documents:
        OFFICIAL_LEGAL_PORTAL_CACHE['documents'] = documents
        OFFICIAL_LEGAL_PORTAL_CACHE['fetched_at'] = now
    return documents[:limit]


def _search_official_portal_documents(query, limit=10):
    search_candidates = _extract_doc_symbol_candidates(query)
    search_candidates.append(query.strip())
    year_value = _extract_issue_year(query)

    session = requests.Session()
    base_response = session.get(
        OFFICIAL_LEGAL_PORTAL_RECENT_URL,
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'vi-VN,vi;q=0.9',
        },
        timeout=15,
    )
    base_response.raise_for_status()
    hidden_fields = _extract_portal_hidden_fields(base_response.text)
    if not hidden_fields:
        return []

    results = []
    seen_ids = set()
    for candidate in search_candidates:
        candidate = (candidate or '').strip()
        if not candidate:
            continue

        form_data = {
            '__EVENTTARGET': '',
            '__EVENTARGUMENT': '',
            '__VIEWSTATE': hidden_fields.get('__VIEWSTATE', ''),
            '__VIEWSTATEGENERATOR': hidden_fields.get('__VIEWSTATEGENERATOR', ''),
            '__EVENTVALIDATION': hidden_fields.get('__EVENTVALIDATION', ''),
            'ctrl_191017_163$drdDocCategory': '0',
            'ctrl_191017_163$drdDocOrg': '0',
            'ctrl_191017_163$drdDocYear': year_value,
            'ctrl_191017_163$txtSearchKeyword': candidate,
            'ctrl_191017_163$drdRecordPerPage': str(limit),
            'ctrl_191017_163$btnSearch': 'Tìm kiếm',
            'ctrl_191017_163$hidSiteId': hidden_fields.get('ctrl_191017_163$hidSiteId', '4'),
            'ctrl_191017_163$hidIsSearch': hidden_fields.get('ctrl_191017_163$hidIsSearch', '0'),
            'ctrl_191017_163$hiIsTrangTTG': hidden_fields.get('ctrl_191017_163$hiIsTrangTTG', 'thutuongpage'),
        }

        response = session.post(
            OFFICIAL_LEGAL_PORTAL_RECENT_URL,
            data=form_data,
            headers={
                'User-Agent': 'Mozilla/5.0',
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': OFFICIAL_LEGAL_PORTAL_RECENT_URL,
            },
            timeout=15,
        )
        response.raise_for_status()

        for item in _extract_portal_documents(response.text):
            doc_id = item.get('id_van_ban')
            if doc_id and doc_id not in seen_ids:
                seen_ids.add(doc_id)
                results.append(item)

    return results


def _fetch_official_legal_documents(query):
    payload = _build_legal_search_payload(query)
    response = requests.post(
        f'{OFFICIAL_LEGAL_SEARCH_API}/van-ban',
        json=payload,
        headers={
            'accept': 'application/json',
            'Content-Type': 'application/json',
        },
        timeout=15,
    )
    response.raise_for_status()
    body = response.json()
    return body.get('data') or []


def _slugify_vietnamese(value):
    text = _normalize_query_text(value)
    text = re.sub(r'[^0-9a-z]+', '-', text)
    return text.strip('-')


def _score_legal_document_match(doc, query):
    if not isinstance(doc, dict):
        return -1

    normalized_query = _normalize_query_text(query)
    normalized_symbol = _normalize_query_text(doc.get('so_ky_hieu', ''))
    normalized_title = _normalize_query_text(doc.get('tieu_de', ''))
    normalized_summary = _normalize_query_text(doc.get('trich_yeu', ''))
    doc_type = _extract_legal_doc_type(query)
    query_number, query_year = _extract_legal_reference_number_year(query)
    query_issue_date = _normalize_query_text(_extract_issue_date(query))
    normalized_issued_at = _normalize_query_text(doc.get('ngay_ban_hanh', ''))

    score = 0
    if doc_type and _normalize_query_text(doc.get('loai_van_ban', '')) == _normalize_query_text(doc_type):
        score += 5

    if query_number and query_number in normalized_symbol:
        score += 5
    elif query_number and re.search(rf'\b{re.escape(query_number)}\b', normalized_title):
        score += 2

    if query_year and query_year in normalized_symbol:
        score += 5
    elif query_year and query_year in normalized_title:
        score += 2

    if query_issue_date and query_issue_date in normalized_issued_at:
        score += 6

    for symbol_candidate in _extract_doc_symbol_candidates(query):
        normalized_candidate = _normalize_query_text(symbol_candidate)
        if normalized_candidate and normalized_candidate == normalized_symbol:
            score += 8
            break
        if normalized_candidate and normalized_candidate in normalized_symbol:
            score += 5

    combined_text = f"{normalized_symbol} {normalized_title} {normalized_summary}"
    if normalized_query and normalized_query in combined_text:
        score += 3

    api_score = float(doc.get('score') or 0)
    score += min(api_score, 3)
    return score


def _select_best_legal_document(docs, query):
    if not docs:
        return None

    symbol_candidates = {
        _normalize_query_text(symbol)
        for symbol in _extract_doc_symbol_candidates(query)
        if symbol
    }
    if symbol_candidates:
        exact_symbol_matches = [
            doc for doc in docs
            if _normalize_query_text(doc.get('so_ky_hieu', '')) in symbol_candidates
        ]
        if exact_symbol_matches:
            query_issue_date = _normalize_query_text(_extract_issue_date(query))
            if query_issue_date:
                dated_matches = [
                    doc for doc in exact_symbol_matches
                    if _normalize_query_text(doc.get('ngay_ban_hanh', '')) == query_issue_date
                ]
                if dated_matches:
                    exact_symbol_matches = dated_matches
            ranked_exact_matches = sorted(
                exact_symbol_matches,
                key=lambda doc: _score_legal_document_match(doc, query),
                reverse=True,
            )
            return ranked_exact_matches[0]

    ranked = sorted(docs, key=lambda doc: _score_legal_document_match(doc, query), reverse=True)
    best = ranked[0]
    if _score_legal_document_match(best, query) < 8:
        return None
    return best


def _build_official_legal_url(doc):
    portal_url = (doc.get('portal_url') or '').strip()
    if portal_url:
        return portal_url
    title = doc.get('tieu_de') or doc.get('so_ky_hieu') or 'van-ban'
    slug = _slugify_vietnamese(title)
    doc_id = doc.get('id_van_ban')
    if doc_id:
        return f"https://congbao.chinhphu.vn/van-ban/{slug}-{doc_id}.htm"
    attachments = doc.get('danh_sach_tep_van_ban') or []
    if attachments:
        return attachments[0].get('duong_dan', '')
    return ''


def _format_legal_date(date_str):
    if not date_str:
        return ''
    try:
        if re.fullmatch(r'\d{2}/\d{2}/\d{4}', str(date_str).strip()):
            return str(date_str).strip()
        dt = datetime.fromisoformat(str(date_str).replace('Z', '+00:00'))
        return dt.strftime('%d/%m/%Y')
    except Exception:
        return str(date_str)


def _humanize_vietnamese_label(value):
    text = str(value or '').strip()
    if not text:
        return ''
    if text.isupper():
        return text.lower().capitalize()
    return text


def _build_legal_library_search_url(query, doc=None):
    keyword = ''
    if isinstance(doc, dict):
        keyword = (doc.get('so_ky_hieu') or '').strip()
    if not keyword:
        keyword = query.strip()
    return LEGAL_LIBRARY_SEARCH_URL + quote(keyword)


def _build_luat_vietnam_reference_url():
    return LUAT_VIETNAM_SEARCH_URL


def _build_external_legal_reference_lines(query, doc=None):
    return [
        f"Nguồn tham khảo thêm: [Thư viện Pháp luật]({_build_legal_library_search_url(query, doc)}), [LuatVietnam]({_build_luat_vietnam_reference_url()})",
    ]


def _build_official_legal_answer(query, doc):
    symbol = doc.get('so_ky_hieu') or 'Không rõ số ký hiệu'
    title = doc.get('tieu_de') or doc.get('trich_yeu') or 'Chưa có tiêu đề'
    summary = doc.get('trich_yeu') or title
    doc_type = doc.get('loai_van_ban') or 'Văn bản'
    issued_at = _format_legal_date(doc.get('ngay_ban_hanh'))
    effective_at = _format_legal_date(doc.get('ngay_co_hieu_luc'))
    signer = (doc.get('nguoi_ky') or '').title()
    agencies = ', '.join(_humanize_vietnamese_label(item) for item in (doc.get('ten_co_quan') or []) if item)
    source_url = _build_official_legal_url(doc)

    lines = [
        f"Có. Theo kết quả tra cứu từ nguồn chính thức, có văn bản phù hợp với câu hỏi của bạn.",
        f"- {doc_type}: {symbol}",
        f"- Trích yếu: {summary}",
    ]
    if issued_at:
        lines.append(f"- Ngày ban hành: {issued_at}")
    if effective_at:
        lines.append(f"- Ngày có hiệu lực: {effective_at}")
    if agencies:
        lines.append(f"- Cơ quan ban hành: {agencies}")
    if signer:
        lines.append(f"- Người ký: {signer}")

    normalized_query = _normalize_query_text(query)
    if 'thay doi gi' in normalized_query or 'sua doi gi' in normalized_query or 'noi dung gi' in normalized_query:
        lines.append(
            f"- Nội dung cho thấy đây là văn bản {title[0].lower() + title[1:] if len(title) > 1 else title.lower()}."
        )

    lines.append("Đây là thông tin xác minh ban đầu từ nguồn công báo/chính phủ; nếu cần phân tích chi tiết từng điểm sửa đổi, cần đọc toàn văn bản gốc.")
    if source_url:
        lines.append(f"Nguồn tra cứu: [Cổng văn bản Chính phủ]({source_url})")
    attachment_url = (doc.get('attachment_url') or '').strip()
    if attachment_url:
        lines.append(f"Tệp đính kèm: [Tải file gốc]({attachment_url})")
    lines.extend(_build_external_legal_reference_lines(query, doc))
    return '\n'.join(lines)


def _build_legal_reference_safety_answer(query):
    return (
        f"Chưa có kết quả xác minh từ nguồn tra cứu văn bản pháp luật chính thức đối với yêu cầu "
        f"\"{query.strip()}\".\n\n"
        f"Hệ thống không kết luận văn bản có tồn tại, không tồn tại hoặc đã có hiệu lực khi chưa tra cứu nguồn chính thức.\n\n"
        f"Đề nghị đối chiếu tại [Cổng văn bản Chính phủ]({OFFICIAL_LEGAL_PORTAL_URL}), "
        f"[Thư viện Pháp luật]({_build_legal_library_search_url(query)}) hoặc "
        f"[LuatVietnam]({_build_luat_vietnam_reference_url()})."
    )


def _is_procedure_query(query):
    normalized = _normalize_query_text(query)
    if any(marker in normalized for marker in PROCEDURE_QUERY_MARKERS):
        return True

    for topic, data in TTHC_KNOWLEDGE.items():
        if _normalize_query_text(topic) in normalized:
            return True
        if any(_normalize_query_text(keyword) in normalized for keyword in data.get('keywords') or []):
            return True

    return False


def _strip_procedure_query_noise(query):
    cleaned = str(query or '').strip()
    cleaned = re.sub(r'[?？！]+', '', cleaned)
    patterns = [
        r'\b(cần chuẩn bị gì|cần giấy tờ gì|cần hồ sơ gì|hồ sơ gồm những gì|hồ sơ gồm gì|thành phần hồ sơ gồm gì).*$',
        r'\b(nộp ở đâu|làm ở đâu|liên hệ ở đâu|cơ quan nào giải quyết).*$',
        r'\b(thời hạn bao lâu|giải quyết bao lâu|mất bao lâu|bao lâu có kết quả).*$',
        r'\b(trình tự thực hiện|trình tự|thủ tục như thế nào|thủ tục ra sao).*$',
        r'\b(phí bao nhiêu|lệ phí bao nhiêu|mức phí|mức lệ phí).*$',
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'^(xin hỏi|cho hỏi|tôi muốn hỏi|tôi cần hỏi|tra cứu)\s+', '', cleaned, flags=re.IGNORECASE)
    return cleaned.strip(' .,:;-')


def _extract_procedure_search_candidates(query):
    normalized = _normalize_query_text(query)
    candidates = []
    seen = set()

    def add_candidate(value):
        label = str(value or '').strip()
        if len(label) < 3:
            return
        normalized_label = _normalize_query_text(label)
        if normalized_label in seen:
            return
        seen.add(normalized_label)
        candidates.append(label)

    for hint, titles in PROCEDURE_SEARCH_HINTS.items():
        if hint in normalized:
            for title in titles:
                add_candidate(title)

    add_candidate(_strip_procedure_query_noise(query))
    add_candidate(query.strip())
    return candidates[:6]


def _build_official_procedure_search_url(query):
    keyword = re.sub(r'[&/\\#,+()$~%\'":*?<>{}^]', ' ', query).strip()
    return (
        f"{OFFICIAL_PROCEDURE_PORTAL_URL}/p/home/dvc-ket-qua-thu-tuc.html"
        f"?originKey={quote(query.strip())}&tukhoa={quote(keyword)}&tinh_thanh="
    )


def _build_official_procedure_detail_url(item):
    ma_thu_tuc = (item.get('ma_thu_tuc') or '').strip()
    if not ma_thu_tuc:
        return ''

    if str(item.get('isnganhdoc') or '') == '1':
        page_name = 'dvc-chi-tiet-thu-tuc-nganh-doc.html'
    elif str(item.get('isdungchung') or '') == '1':
        page_name = 'dvc-chi-tiet-thu-tuc-dung-chung.html'
    else:
        page_name = 'dvc-chi-tiet-thu-tuc-hanh-chinh.html'

    return f"{OFFICIAL_PROCEDURE_PORTAL_URL}/p/home/{page_name}?ma_thu_tuc={quote(ma_thu_tuc)}"


def _score_official_procedure_item(item, query):
    title = _normalize_query_text(item.get('ten_thu_tuc', ''))
    normalized_query = _normalize_query_text(query)
    score = 0

    if not title:
        return score

    if title == normalized_query:
        score += 20
    elif title in normalized_query:
        score += 14
    elif normalized_query in title:
        score += 8

    title_tokens = {token for token in title.split() if len(token) > 2}
    query_tokens = {token for token in normalized_query.split() if len(token) > 2}
    score += len(title_tokens & query_tokens)

    for hint, titles in PROCEDURE_SEARCH_HINTS.items():
        if hint in normalized_query and any(title == _normalize_query_text(item_title) for item_title in titles):
            score += 10

    return score


def _search_official_procedure_suggestions(search_text):
    candidate = str(search_text or '').strip()
    if not candidate:
        return []

    cache_key = _normalize_query_text(candidate)
    cached = _get_ttl_cached_value(OFFICIAL_PROCEDURE_SUGGESTION_CACHE, cache_key, OFFICIAL_PROCEDURE_CACHE_TTL)
    if cached is not None:
        return cached

    response = requests.get(
        OFFICIAL_PROCEDURE_TYPEAHEAD_URL,
        params={'keyword': f'al:"{candidate}"~5'},
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json,text/plain,*/*',
            'Accept-Language': 'vi-VN,vi;q=0.9',
        },
        timeout=15,
    )
    response.raise_for_status()
    suggestions = response.json() if response.text.strip().startswith('[') else []
    if not isinstance(suggestions, list):
        suggestions = []
    _set_ttl_cached_value(OFFICIAL_PROCEDURE_SUGGESTION_CACHE, cache_key, suggestions)
    return suggestions


def _extract_procedure_heading_sections(html_text):
    matches = list(re.finditer(r'<h2 class="main-title-sub">(.*?)</h2>', html_text, re.IGNORECASE | re.DOTALL))
    sections = {}
    for index, match in enumerate(matches):
        title = _clean_html_text(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(html_text)
        sections[title] = html_text[start:end]
    return sections


def _extract_procedure_methods(section_html):
    table_match = re.search(r'<table class="table-result-tthc table-result".*?<tbody>(.*?)</tbody>', section_html, re.IGNORECASE | re.DOTALL)
    if not table_match:
        return []

    methods = []
    for row_html in re.findall(r'<tr>(.*?)</tr>', table_match.group(1), re.IGNORECASE | re.DOTALL):
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.IGNORECASE | re.DOTALL)
        if len(cells) < 4:
            continue
        methods.append({
            'method': _clean_html_text(cells[0]),
            'duration': _clean_html_text(cells[1]),
            'fee': re.sub(r'\s*Xem chi tiết', '', _clean_html_text(cells[2]), flags=re.IGNORECASE).replace('\n', '; ').strip(' ;'),
            'description': _clean_html_text(cells[3]),
        })
    return methods


def _extract_procedure_documents(section_html):
    documents = []
    forms = []

    for row_html in re.findall(r'<tr>(.*?)</tr>', section_html, re.IGNORECASE | re.DOTALL):
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.IGNORECASE | re.DOTALL)
        if len(cells) < 3:
            continue

        document_name = re.sub(r'^-\s*', '', _clean_html_text(cells[0]))
        if _normalize_query_text(document_name).startswith('luu y'):
            continue
        form_match = re.search(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', cells[1], re.IGNORECASE | re.DOTALL)
        form_url = ''
        form_label = ''
        if form_match:
            form_url = html.unescape(form_match.group(1)).strip()
            form_label = _clean_html_text(form_match.group(2))
            if form_url.endswith('ma='):
                form_url = ''
        quantity = _clean_html_text(cells[2])

        if document_name:
            documents.append({
                'name': document_name,
                'quantity': quantity,
            })
        if form_url:
            forms.append({
                'label': form_label or 'Biểu mẫu',
                'url': form_url,
            })

    unique_forms = []
    seen_urls = set()
    for item in forms:
        if item['url'] in seen_urls:
            continue
        seen_urls.add(item['url'])
        unique_forms.append(item)

    return documents, unique_forms


def _extract_procedure_steps(section_html):
    text = _clean_html_text(section_html)
    steps = []
    for part in re.split(r'(?=Bước\s*\d+:)', text):
        cleaned = part.strip()
        if cleaned:
            steps.append(_truncate_text(cleaned, 260))
    return steps


def _fetch_official_procedure_detail(item):
    detail_url = _build_official_procedure_detail_url(item)
    if not detail_url:
        return None

    cache_key = detail_url
    cached = _get_ttl_cached_value(OFFICIAL_PROCEDURE_DETAIL_CACHE, cache_key, OFFICIAL_PROCEDURE_CACHE_TTL)
    if cached is not None:
        return cached

    response = requests.get(
        detail_url,
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'vi-VN,vi;q=0.9',
        },
        timeout=15,
    )
    response.raise_for_status()
    html_text = response.text

    title_matches = re.findall(r'<h1 class="main-title -none"[^>]*>(.*?)</h1>', html_text, re.IGNORECASE | re.DOTALL)
    title = ''
    for title_html in title_matches:
        candidate = _clean_html_text(title_html)
        if candidate:
            title = candidate
    sections = _extract_procedure_heading_sections(html_text)
    methods = _extract_procedure_methods(sections.get('Cách thức thực hiện', ''))
    documents, forms = _extract_procedure_documents(sections.get('Thành phần hồ sơ', ''))
    steps = _extract_procedure_steps(sections.get('Trình tự thực hiện', ''))
    agency_section = sections.get('Cơ quan thực hiện', '')
    agency_match = re.search(r'<div class="article">(.*?)</div>', agency_section, re.IGNORECASE | re.DOTALL)
    agency = _clean_html_text(agency_match.group(1) if agency_match else agency_section)
    requirements_section = sections.get('Yêu cầu, điều kiện thực hiện', '')
    requirements_match = re.search(r'<div class="article">(.*?)</div>', requirements_section, re.IGNORECASE | re.DOTALL)
    requirements = _clean_html_text(requirements_match.group(1) if requirements_match else requirements_section)
    online_match = re.search(r'redirectlocal="([^"]+)"', html_text, re.IGNORECASE)
    online_url = html.unescape(online_match.group(1)).strip() if online_match else ''

    detail = {
        'title': title or item.get('ten_thu_tuc') or '',
        'detail_url': detail_url,
        'search_url': _build_official_procedure_search_url(item.get('ten_thu_tuc') or item.get('ma_thu_tuc') or ''),
        'online_url': online_url,
        'methods': methods,
        'documents': documents,
        'forms': forms,
        'steps': steps,
        'agency': agency,
        'requirements': requirements,
        'publisher': item.get('co_quan_cong_bo') or '',
        'ma_thu_tuc': item.get('ma_thu_tuc') or '',
    }
    _set_ttl_cached_value(OFFICIAL_PROCEDURE_DETAIL_CACHE, cache_key, detail)
    return detail


def _lookup_official_procedure(query):
    ranked = []
    seen_ids = set()
    for candidate in _extract_procedure_search_candidates(query):
        for item in _search_official_procedure_suggestions(candidate):
            ma_thu_tuc = str(item.get('ma_thu_tuc') or '').strip()
            if not ma_thu_tuc or ma_thu_tuc in seen_ids:
                continue
            seen_ids.add(ma_thu_tuc)
            ranked.append((item, _score_official_procedure_item(item, query)))

    if not ranked:
        return None

    ranked.sort(key=lambda entry: entry[1], reverse=True)
    best_item, best_score = ranked[0]
    if best_score < 5:
        return None
    return _fetch_official_procedure_detail(best_item)


def _build_official_procedure_answer(query, procedure):
    lines = [
        "Có. Hệ thống đã đối chiếu được thủ tục phù hợp từ Cổng Dịch vụ công quốc gia.",
        f"- Thủ tục: {procedure.get('title') or 'Chưa xác định'}",
    ]

    if procedure.get('agency'):
        lines.append(f"- Cơ quan thực hiện: {_truncate_text(procedure['agency'], 220)}")
    if procedure.get('publisher'):
        lines.append(f"- Cơ quan công bố: {_truncate_text(procedure['publisher'], 220)}")

    if procedure.get('steps'):
        lines.append("- Trình tự chính:")
        for step in procedure['steps'][:3]:
            lines.append(f"- {step}")

    if procedure.get('methods'):
        lines.append("- Cách thức thực hiện:")
        for method in procedure['methods'][:2]:
            method_line = f"  {method.get('method') or 'Không rõ hình thức'}"
            if method.get('duration'):
                method_line += f" | Thời hạn: {method['duration']}"
            if method.get('fee'):
                method_line += f" | Phí/lệ phí: {method['fee']}"
            lines.append('- ' + method_line.strip())

    if procedure.get('documents'):
        lines.append("- Hồ sơ chính:")
        for document in procedure['documents'][:3]:
            doc_line = f"  {_truncate_text(document.get('name') or 'Không rõ giấy tờ', 240)}"
            if document.get('quantity'):
                doc_line += f" ({document['quantity']})"
            lines.append('- ' + doc_line.strip())

    requirements = (procedure.get('requirements') or '').strip()
    if requirements and _normalize_query_text(requirements) not in {'khong', 'không'}:
        lines.append(f"- Yêu cầu/điều kiện: {_truncate_text(requirements, 320)}")

    if procedure.get('detail_url'):
        lines.append(f"Nguồn tra cứu: [Chi tiết thủ tục]({procedure['detail_url']})")
    if procedure.get('online_url'):
        lines.append(f"Nộp trực tuyến: [Mở cổng nộp hồ sơ]({procedure['online_url']})")
    if procedure.get('forms'):
        form_links = ', '.join(
            f"[{form.get('label') or 'Biểu mẫu'}]({form.get('url')})"
            for form in procedure['forms'][:3]
            if form.get('url')
        )
        if form_links:
            lines.append(f"Biểu mẫu: {form_links}")
    lines.append(f"Tra cứu thêm: [Kết quả tìm kiếm trên Cổng DVCQG]({_build_official_procedure_search_url(query)})")
    return '\n'.join(lines)


def _get_system_prompt(query=None, config=None):
    cfg = config or _get_ai_config()
    now_info = _format_vi_datetime(datetime.now())
    if cfg and cfg.is_active and (cfg.system_prompt or '').strip():
        base_prompt = cfg.system_prompt.strip()
    else:
        base_prompt = AI_SYSTEM_PROMPT

    additions = [
        (
            f"Thời gian hệ thống hiện tại: {now_info['full_date_text']}, {now_info['time_text']}. "
            f"Nếu người dùng hỏi về hôm nay, hôm qua, ngày mai hoặc giờ hiện tại, phải bám đúng mốc này."
        )
    ]

    if query and _is_specific_legal_reference_query(query):
        additions.append(
            "Đây là câu hỏi về văn bản pháp luật cụ thể. Nếu chưa có kết quả tra cứu từ nguồn chính thức được cung cấp trong ngữ cảnh, "
            "tuyệt đối không được kết luận văn bản có tồn tại hay không tồn tại, không được suy đoán năm ban hành hay hiệu lực. "
            "Phải nói rõ là chưa xác minh được từ nguồn chính thức."
        )

    if query and _is_procedure_query(query):
        additions.append(
            "Đây là câu hỏi về thủ tục hành chính. Nếu chưa có dữ liệu chính thức từ Cổng Dịch vụ công quốc gia hoặc cơ quan có thẩm quyền, "
            "không được tự bịa thành phần hồ sơ, thời hạn, lệ phí hoặc nơi nộp; phải nói rõ là chưa xác minh được từ nguồn chính thức."
        )

    return f"{base_prompt.strip()}\n\nQuy tắc thời gian và an toàn bổ sung:\n- " + "\n- ".join(additions)


def _get_provider_sequence():
    preferred = _get_provider_runtime()['provider']
    ordered = [preferred] + [name for name in AI_PROVIDER_DEFAULTS if name != preferred]
    return [name for name in ordered if name in AI_PROVIDER_DEFAULTS]


def _get_provider_runtime():
    config = _get_ai_config()

    preferred = ((config.provider if config and config.is_active else None) or os.getenv('AI_ASSISTANT_PROVIDER') or 'deepseek').strip().lower()
    if preferred not in AI_PROVIDER_DEFAULTS:
        preferred = 'deepseek'

    model = ((config.model_name if config and config.is_active else None) or os.getenv('AI_ASSISTANT_MODEL') or AI_PROVIDER_DEFAULTS[preferred]).strip()
    api_key = _get_provider_api_key(preferred, config=config)
    configured = bool(api_key)
    return {
        'provider': preferred,
        'model': model,
        'label': AI_PROVIDER_LABELS.get(preferred, model),
        'configured': configured,
    }


def _get_provider_api_key(provider, config=None):
    cfg = config or _get_ai_config()

    if cfg and cfg.is_active and (cfg.provider or '').strip().lower() == provider and (cfg.api_key or '').strip():
        return cfg.api_key.strip()

    env_keys = {
        'deepseek': 'DEEPSEEK_API_KEY',
        'gemini': 'GEMINI_API_KEY',
        'openai': 'OPENAI_API_KEY',
        'groq': 'GROQ_API_KEY',
    }
    return (os.getenv(env_keys.get(provider, ''), '') or '').strip()


def _extract_openai_text(payload):
    choices = payload.get('choices') or []
    if not choices:
        return None
    message = choices[0].get('message') or {}
    return (message.get('content') or '').strip() or None


def _extract_gemini_text(payload):
    candidates = payload.get('candidates') or []
    if not candidates:
        return None

    content = candidates[0].get('content') or {}
    parts = content.get('parts') or []
    text_parts = [part.get('text', '') for part in parts if part.get('text')]
    answer = '\n'.join(text_parts).strip()
    return answer or None


def _extract_error_detail(response):
    try:
        payload = response.json()
    except Exception:
        payload = None

    if isinstance(payload, dict):
        error = payload.get('error')
        if isinstance(error, dict):
            return (
                error.get('message')
                or error.get('code')
                or str(error)
            )
        if isinstance(error, str):
            return error
        message = payload.get('message')
        if isinstance(message, str) and message.strip():
            return message.strip()

    body = (response.text or '').strip()
    if body:
        return body[:240]
    return 'Không có mô tả lỗi chi tiết'


def _provider_success(answer, provider, model_name):
    return {
        'ok': True,
        'answer': answer,
        'provider': provider,
        'model': model_name,
    }


def _provider_error(provider, model_name, message, status_code=None):
    return {
        'ok': False,
        'provider': provider,
        'model': model_name,
        'status_code': status_code,
        'error': message,
    }


def _build_provider_failure_message(provider_error):
    provider = (provider_error or {}).get('provider', 'provider')
    model_name = (provider_error or {}).get('model', '')
    error_text = (provider_error or {}).get('error', 'Không rõ nguyên nhân')
    pieces = [
        f"Dịch vụ {provider} hiện không phản hồi với mô hình {model_name}.",
        f"Chi tiết: {error_text}.",
        "Kiểm tra lại API key, quota và kết nối outbound từ máy chủ tới API."
    ]
    return ' '.join(pieces)


def call_deepseek_api(prompt, model=None):
    api_key = _get_provider_api_key('deepseek')
    model_name = model or AI_PROVIDER_DEFAULTS['deepseek']
    if not api_key:
        return _provider_error('deepseek', model_name, 'Chưa tìm thấy API key DeepSeek')

    system_prompt = _get_system_prompt(query=prompt)
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }
    payload = {
        'model': model_name,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0.35,
        'max_tokens': 700,
    }

    try:
        response = requests.post(
            'https://api.deepseek.com/chat/completions',
            headers=headers,
            json=payload,
            timeout=30
        )
        if response.status_code == 200:
            answer = _extract_openai_text(response.json())
            if answer:
                return _provider_success(answer, 'deepseek', model_name)
            return _provider_error('deepseek', model_name, 'API trả về 200 nhưng không có nội dung trả lời', 200)
        return _provider_error('deepseek', model_name, _extract_error_detail(response), response.status_code)
    except Exception as exc:
        print(f"DeepSeek API error: {exc}")
        return _provider_error('deepseek', model_name, str(exc))

    return _provider_error('deepseek', model_name, 'Không xác định được lỗi')


def call_gemini_api(prompt, model=None):
    api_key = _get_provider_api_key('gemini')
    model_name = model or AI_PROVIDER_DEFAULTS['gemini']
    if not api_key:
        return _provider_error('gemini', model_name, 'Chưa tìm thấy API key Gemini')

    system_prompt = _get_system_prompt(query=prompt)
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}'
    payload = {
        'system_instruction': {
            'parts': [{'text': system_prompt}]
        },
        'contents': [
            {
                'role': 'user',
                'parts': [{'text': prompt}]
            }
        ],
        'generationConfig': {
            'temperature': 0.35,
            'maxOutputTokens': 700,
        }
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        if response.status_code == 200:
            answer = _extract_gemini_text(response.json())
            if answer:
                return _provider_success(answer, 'gemini', model_name)
            return _provider_error('gemini', model_name, 'API trả về 200 nhưng không có nội dung trả lời', 200)
        return _provider_error('gemini', model_name, _extract_error_detail(response), response.status_code)
    except Exception as exc:
        print(f"Gemini API error: {exc}")
        return _provider_error('gemini', model_name, str(exc))

    return _provider_error('gemini', model_name, 'Không xác định được lỗi')


def call_openai_api(prompt, model=None):
    api_key = _get_provider_api_key('openai')
    model_name = model or AI_PROVIDER_DEFAULTS['openai']
    if not api_key:
        return _provider_error('openai', model_name, 'Chưa tìm thấy API key OpenAI')

    system_prompt = _get_system_prompt(query=prompt)
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }
    payload = {
        'model': model_name,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0.35,
        'max_tokens': 700,
    }

    try:
        response = requests.post(
            'https://api.openai.com/v1/chat/completions',
            headers=headers,
            json=payload,
            timeout=30
        )
        if response.status_code == 200:
            answer = _extract_openai_text(response.json())
            if answer:
                return _provider_success(answer, 'openai', model_name)
            return _provider_error('openai', model_name, 'API trả về 200 nhưng không có nội dung trả lời', 200)
        return _provider_error('openai', model_name, _extract_error_detail(response), response.status_code)
    except Exception as exc:
        print(f"OpenAI API error: {exc}")
        return _provider_error('openai', model_name, str(exc))

    return _provider_error('openai', model_name, 'Không xác định được lỗi')


def call_groq_api(prompt, model=None):
    api_key = _get_provider_api_key('groq')
    model_name = model or AI_PROVIDER_DEFAULTS['groq']
    if not api_key:
        return _provider_error('groq', model_name, 'Chưa tìm thấy API key Groq')

    system_prompt = _get_system_prompt(query=prompt)
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    payload = {
        'model': model_name,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': prompt}
        ],
        'max_tokens': 700,
        'temperature': 0.35
    }

    try:
        response = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers=headers,
            json=payload,
            timeout=30
        )
        if response.status_code == 200:
            answer = _extract_openai_text(response.json())
            if answer:
                return _provider_success(answer, 'groq', model_name)
            return _provider_error('groq', model_name, 'API trả về 200 nhưng không có nội dung trả lời', 200)
        return _provider_error('groq', model_name, _extract_error_detail(response), response.status_code)
    except Exception as exc:
        print(f"Groq API error: {exc}")
        return _provider_error('groq', model_name, str(exc))

    return _provider_error('groq', model_name, 'Không xác định được lỗi')


def call_ai_provider(prompt):
    runtime = _get_provider_runtime()
    provider_sequence = _get_provider_sequence()
    provider_callers = {
        'deepseek': call_deepseek_api,
        'gemini': call_gemini_api,
        'openai': call_openai_api,
        'groq': call_groq_api,
    }
    errors = []

    for provider in provider_sequence:
        model_name = runtime['model'] if provider == runtime['provider'] else AI_PROVIDER_DEFAULTS[provider]
        result = provider_callers[provider](prompt, model=model_name)
        if result and result.get('ok'):
            return result, errors
        if result:
            errors.append(result)

    return None, errors


def find_answer_from_kb(query):
    query_lower = query.lower()

    for key, response in CANNED_RESPONSES.items():
        if key in query_lower:
            return response

    for topic, data in TTHC_KNOWLEDGE.items():
        if topic in query_lower:
            return data['answer']
        for keyword in data['keywords']:
            if keyword in query_lower:
                return data['answer']

    return None


def fetch_gov_news(limit=10):
    now = time.monotonic()
    cached_articles = GOV_NEWS_CACHE.get('articles') or []
    cached_at = float(GOV_NEWS_CACHE.get('fetched_at') or 0.0)

    if cached_articles and (now - cached_at) < GOV_NEWS_CACHE_TTL:
        return cached_articles[:limit]

    articles = []
    try:
        url = "https://tuyenquang.gov.vn"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7',
        }

        response = requests.get(url, headers=headers, timeout=4)
        if response.status_code == 200:
            try:
                html = response.content.decode('utf-8')
            except Exception:
                try:
                    html = response.content.decode('iso-8859-1')
                except Exception:
                    html = response.text

            link_pattern = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]+)</a>', re.IGNORECASE)

            for match in link_pattern.finditer(html):
                href = match.group(1)
                title = re.sub(r'<[^>]+>', '', match.group(2)).strip()
                title = (
                    title.replace('&nbsp;', ' ')
                    .replace('&amp;', '&')
                    .replace('&lt;', '<')
                    .replace('&gt;', '>')
                    .replace('&quot;', '"')
                )

                if not title or len(title) < 15 or len(title) > 200:
                    continue

                full_url = href if href.startswith('http') else url + href
                articles.append({
                    'title': title,
                    'link': full_url,
                    'source': 'tuyenquang.gov.vn',
                    'date': ''
                })
                if len(articles) >= limit:
                    break
    except Exception as exc:
        print(f"Error fetching news: {exc}")

    if articles:
        GOV_NEWS_CACHE['articles'] = articles
        GOV_NEWS_CACHE['fetched_at'] = now
        return articles[:limit]

    if cached_articles:
        return cached_articles[:limit]

    articles = [
        {'title': 'Cập nhật thông tin điều hành và tin tức mới trên Cổng thông tin điện tử tỉnh Tuyên Quang', 'link': 'https://tuyenquang.gov.vn', 'source': 'tuyenquang.gov.vn', 'date': ''},
        {'title': 'Hướng dẫn tra cứu thủ tục hành chính và thông tin công dân trên các cổng chính thức', 'link': 'https://tuyenquang.gov.vn', 'source': 'tuyenquang.gov.vn', 'date': ''},
        {'title': 'Thông báo, lịch tiếp công dân và các bản tin phục vụ người dân địa phương', 'link': 'https://tuyenquang.gov.vn', 'source': 'tuyenquang.gov.vn', 'date': ''},
    ]

    return articles


@ai_bp.route('/')
def index():
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    news = fetch_gov_news(10)
    runtime = _get_provider_runtime()

    return render_template(
        'ai_assistant.html',
        title='Trợ lý AI',
        news=news,
        suggested_topics=SUGGESTED_TOPICS,
        assistant_runtime=runtime,
        assistant_welcome=WELCOME_MESSAGE,
    )


@ai_bp.route('/chat', methods=['POST'])
def chat():
    if not session.get('uid'):
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    query = (data.get('message') or '').strip()
    if not query:
        return jsonify({'error': 'Vui lòng nhập câu hỏi'}), 400

    if _is_time_query(query):
        return jsonify({
            'success': True,
            'answer': _build_time_answer(query),
            'type': 'system_time'
        })

    if _is_specific_legal_reference_query(query):
        try:
            portal_docs = _fetch_official_portal_recent_documents(limit=100)
            best_portal_doc = _select_best_legal_document(portal_docs, query)
            if not best_portal_doc:
                portal_docs = _search_official_portal_documents(query, limit=50)
                best_portal_doc = _select_best_legal_document(portal_docs, query)

            if best_portal_doc:
                return jsonify({
                    'success': True,
                    'answer': _build_official_legal_answer(query, best_portal_doc),
                    'type': 'legal_verified',
                    'source': 'official_legal_portal'
                })
        except Exception as exc:
            print(f"Official legal portal lookup error: {exc}")

        try:
            legal_docs = _fetch_official_legal_documents(query)
            best_doc = _select_best_legal_document(legal_docs, query)
            if best_doc:
                return jsonify({
                    'success': True,
                    'answer': _build_official_legal_answer(query, best_doc),
                    'type': 'legal_verified',
                    'source': 'official_legal_search'
                })
        except Exception as exc:
            print(f"Official legal lookup error: {exc}")

        return jsonify({
            'success': True,
            'answer': _build_legal_reference_safety_answer(query),
            'type': 'legal_safe_guard'
        })

    if _is_procedure_query(query):
        try:
            best_procedure = _lookup_official_procedure(query)
            if best_procedure:
                return jsonify({
                    'success': True,
                    'answer': _build_official_procedure_answer(query, best_procedure),
                    'type': 'procedure_verified',
                    'source': 'national_public_service_portal'
                })
        except Exception as exc:
            print(f"Official procedure lookup error: {exc}")

    runtime = _get_provider_runtime()
    ai_result, provider_errors = call_ai_provider(query)
    if ai_result:
        return jsonify({
            'success': True,
            'answer': ai_result['answer'],
            'type': 'ai',
            'provider': ai_result['provider'],
            'model': ai_result['model'],
        })

    answer = find_answer_from_kb(query)
    if answer:
        if runtime['configured'] and provider_errors:
            answer = (
                f"{answer}\n\n"
                f"Lưu ý: dịch vụ AI ngoài đang lỗi, hệ thống đang dùng câu trả lời mẫu nội bộ. "
                f"{_build_provider_failure_message(provider_errors[0])}"
            )
        return jsonify({
            'success': True,
            'answer': answer,
            'type': 'kb'
        })

    if runtime['configured'] and provider_errors:
        return jsonify({
            'success': False,
            'answer': _build_provider_failure_message(provider_errors[0]),
            'type': 'provider_error'
        })

    suggestions = [topic['title'] for topic in SUGGESTED_TOPICS[:5]]
    return jsonify({
        'success': False,
        'answer': (
            "Chưa đủ dữ liệu để kết luận nội dung này. "
            "Bổ sung rõ thủ tục, giấy tờ, nơi nộp hồ sơ hoặc tình huống thực tế để tiếp tục tra cứu."
        ),
        'type': 'no_match',
        'suggestions': suggestions
    })


@ai_bp.route('/news')
def news():
    if not session.get('uid'):
        return jsonify({'error': 'Unauthorized'}), 401

    limit = request.args.get('limit', 10, type=int)
    articles = fetch_gov_news(limit)
    return jsonify({
        'success': True,
        'articles': articles
    })
