# -*- coding: utf-8 -*-
from flask import Blueprint, request, session, jsonify, redirect, url_for
import os
import requests
import re
import unicodedata
from datetime import datetime, timedelta
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
    if not has_keyword:
        return False

    has_reference_number = bool(re.search(r'\bso\s*\d{1,4}\b', normalized))
    has_number_year = bool(re.search(r'\b\d{1,4}\s*(/|-)\s*(19|20)\d{2}\b', normalized))
    has_named_number_year = bool(re.search(r'\b\d{1,4}\b.*\b(19|20)\d{2}\b', normalized))
    has_year_phrase = bool(re.search(r'\bnam\s*(19|20)\d{2}\b', normalized))
    has_bare_number = bool(re.search(r'\b\d{1,4}\b', normalized))
    return has_number_year or has_reference_number or (has_year_phrase and has_bare_number) or has_named_number_year


def _extract_legal_doc_type(query):
    normalized = _normalize_query_text(query)
    for keyword, label in sorted(LEGAL_DOC_TYPE_MAP.items(), key=lambda item: len(item[0]), reverse=True):
        if keyword in normalized:
            return label
    return ''


def _extract_legal_reference_number_year(query):
    normalized = _normalize_query_text(query)
    match = re.search(r'\b(\d{1,4})\s*(?:/|-|\s+nam\s+)(19|20)\d{2}\b', normalized)
    if match:
        number = match.group(1)
        year_match = re.search(r'(19|20)\d{2}', match.group(0))
        if year_match:
            return number, year_match.group(0)

    year_match = re.search(r'\b(19|20)\d{2}\b', normalized)
    number_match = re.search(r'\b(\d{1,4})\b', normalized)
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

    combined_text = f"{normalized_symbol} {normalized_title} {normalized_summary}"
    if normalized_query and normalized_query in combined_text:
        score += 3

    api_score = float(doc.get('score') or 0)
    score += min(api_score, 3)
    return score


def _select_best_legal_document(docs, query):
    if not docs:
        return None

    ranked = sorted(docs, key=lambda doc: _score_legal_document_match(doc, query), reverse=True)
    best = ranked[0]
    if _score_legal_document_match(best, query) < 8:
        return None
    return best


def _build_official_legal_url(doc):
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
        lines.append(f"Nguồn tra cứu: {source_url}")
    return '\n'.join(lines)


def _build_legal_reference_safety_answer(query):
    return (
        f"Chưa có kết quả xác minh từ nguồn tra cứu văn bản pháp luật chính thức đối với yêu cầu "
        f"\"{query.strip()}\".\n\n"
        f"Hệ thống không kết luận văn bản có tồn tại, không tồn tại hoặc đã có hiệu lực khi chưa tra cứu nguồn chính thức.\n\n"
        f"Đề nghị đối chiếu tại Cơ sở dữ liệu quốc gia về văn bản pháp luật, Cổng Thông tin điện tử Chính phủ hoặc Bộ Tư pháp."
    )


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
    articles = []
    try:
        url = "https://tuyenquang.gov.vn"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7',
        }

        response = requests.get(url, headers=headers, timeout=10)
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

    if not articles:
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
        title='Hỗ trợ thủ tục',
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
