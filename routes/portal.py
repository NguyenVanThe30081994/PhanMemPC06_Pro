# -*- coding: utf-8 -*-
from flask import Blueprint, request, session, redirect, url_for, flash, current_app
import os, pandas as pd, io, json, re, unicodedata
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from html import unescape
from models import db, NewsDoc, DocumentLib, Contact, CategoryItem, AppRole
from category_helpers import (
    canonicalize_category_value as shared_canonicalize_category_value,
    category_resolver as shared_category_resolver,
    decorate_records_with_category as shared_decorate_records_with_category,
    ensure_category_item_alias,
    get_bound_group,
    get_category_group,
    get_category_items,
    get_module_field_items,
    module_category_options as shared_module_category_options,
    resolve_category_display as shared_resolve_category_display,
    slugify_code,
    stable_form_category_options as shared_stable_form_category_options,
    sync_record_categories as shared_sync_record_categories,
)
from utils import log_action, push_global_notif, render_auto_template as render_template
import requests
try:
    from security_utils.file_validator import validate_file_upload
except ImportError:
    def validate_file_upload(f):
        return True, "OK", f.filename

portal_bp = Blueprint('portal_bp', __name__)

LEGAL_DOCS_SOURCE_URL = 'https://vanban.chinhphu.vn/he-thong-van-ban?classid=1&mode=1'
LEGAL_DOCS_DEFAULT_FIELD_ID = '2'
LEGAL_DOCS_CACHE_TTL = timedelta(minutes=30)
_LEGAL_DOCS_CACHE = {
    'fields': {'expires_at': None, 'items': []},
    'docs': {},
}

BCA_DOCS_SOURCE_URL = 'https://vanban.bocongan.gov.vn/'
BCA_DOCS_API_BASE = 'https://api-portal.bocongan.gov.vn/backend-portal'
BCA_DOCS_DEFAULT_GROUP = 'LAW'
BCA_DOCS_DEFAULT_ORG_ID = '11'
_BCA_DOCS_CACHE = {
    'doc_groups': {'expires_at': None, 'items': []},
    'document_types': {'expires_at': None, 'items': []},
    'effective_status': {'expires_at': None, 'items': []},
    'documents': {},
}

CONTACT_IMPORT_HEADER_ALIASES = {
    'name': {'ho ten', 'ten', 'ten lien he', 'ho va ten'},
    'role': {'chuc vu', 'vai tro', 'chuc danh', 'position', 'role'},
    'phone': {'so dien thoai', 'sdt', 'so dt', 'dien thoai'},
    'unit_name': {'don vi', 'ten don vi', 'co quan', 'phong ban', 'don vi cong tac', 'unit'}
}


def _normalize_import_label(value):
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace('đ', 'd').replace('Đ', 'D')
    text = re.sub(r'[^0-9a-zA-Z]+', ' ', text).strip().lower()
    return re.sub(r'\s+', ' ', text)


def _clean_import_text(value):
    if value is None:
        return ''
    text = str(value).strip()
    if text.lower() == 'nan':
        return ''
    return text


def _normalize_import_phone(value):
    raw = _clean_import_text(value)
    if not raw:
        return ''

    digits = re.sub(r'\D+', '', raw)
    if not digits:
        return ''
    if digits.startswith('84') and len(digits) == 11:
        return f"0{digits[2:]}"
    if len(digits) == 9:
        return f"0{digits}"
    return digits


def _find_import_column(columns, field_name):
    aliases = CONTACT_IMPORT_HEADER_ALIASES[field_name]
    for col in columns:
        if _normalize_import_label(col) in aliases:
            return col
    return None


def _get_current_user_unit():
    return session.get('unit_area') or session.get('unit') or 'N/A'


def _module_category_options(module_code, field_code, *fallback_names):
    return shared_module_category_options(module_code, field_code, *fallback_names)


def _category_resolver(category_options):
    return shared_category_resolver(category_options)


def _resolve_category_display(value, category_options, fallback_label='Chưa phân lĩnh vực', allow_unknown_label=True):
    return shared_resolve_category_display(
        value,
        category_options,
        fallback_label=fallback_label,
        allow_unknown_label=allow_unknown_label,
    )


def _canonicalize_category_value(value, category_options, prefer_stable=False):
    return shared_canonicalize_category_value(value, category_options, prefer_stable=prefer_stable)


def _sync_record_categories(records, category_options, attr_name='category', prefer_stable=False):
    return shared_sync_record_categories(records, category_options, attr_name=attr_name, prefer_stable=prefer_stable)


def _stable_form_category_options(category_options):
    return shared_stable_form_category_options(category_options)


def _category_match_values(value, category_options):
    raw_value = (value or '').strip()
    if not raw_value:
        return set()
    resolved = _resolve_category_display(raw_value, category_options, fallback_label='')
    values = {raw_value}
    option = resolved.get('option')
    if option:
        values.update({
            option.get('stable_value') or '',
            option.get('value') or '',
            option.get('code') or '',
            option.get('name') or '',
        })
    return {item.strip() for item in values if item and str(item).strip()}


def _decorate_records_with_category(records, category_options, fallback_label='Chưa phân lĩnh vực', allow_unknown_label=True):
    return shared_decorate_records_with_category(
        records,
        category_options,
        fallback_label=fallback_label,
        allow_unknown_label=allow_unknown_label,
    )


def _category_filter_counts(items, category_options):
    counts = {item['slug']: 0 for item in category_options if item.get('slug')}
    uncategorized_total = 0
    for item in items:
        filter_value = item.get('category_filter') or '__uncategorized__'
        if filter_value in counts:
            counts[filter_value] += 1
        else:
            uncategorized_total += 1
    filters = []
    for option in category_options:
        filters.append({
            'name': option['name'],
            'filter_value': option['slug'] or '__uncategorized__',
            'count': counts.get(option['slug'], 0),
        })
    if uncategorized_total:
        filters.append({
            'name': 'Chưa phân lĩnh vực',
            'filter_value': '__uncategorized__',
            'count': uncategorized_total,
        })
    return filters


def _parse_iso_datetime(value):
    raw_value = (value or '').strip()
    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(raw_value.replace('Z', '+00:00'))
    except ValueError:
        return None


def _format_display_date(value):
    parsed = _parse_iso_datetime(value)
    return parsed.strftime('%d/%m/%Y') if parsed else ''


def _extract_legal_hidden_inputs(html):
    return dict(re.findall(r'<input[^>]+type="hidden"[^>]+name="([^"]+)"[^>]+value="([^"]*)"', html, re.I))


def _parse_legal_field_options(html):
    match = re.search(
        r'<select name="ctrl_191017_163\$drdDocCategory"[^>]*>(.*?)</select>',
        html,
        re.S | re.I,
    )
    if not match:
        return []
    options = []
    for value, label in re.findall(r'<option[^>]+value="([^"]*)"[^>]*>(.*?)</option>', match.group(1), re.S | re.I):
        clean_label = re.sub(r'\s+', ' ', unescape(label or '')).strip()
        clean_value = (value or '').strip()
        if not clean_value or clean_value == '0' or not clean_label:
            continue
        options.append({
            'id': clean_value,
            'name': clean_label,
            'slug': slugify_code(clean_label),
        })
    return options


def _parse_legal_documents(html):
    match = re.search(
        r'<table[^>]+id="ctrl_191017_163_grvDocument"[^>]*>(.*?)</table>',
        html,
        re.S | re.I,
    )
    if not match:
        return []
    rows = re.findall(r'<tr>(.*?)</tr>', match.group(1), re.S | re.I)
    documents = []
    for row_html in rows[1:]:
        code_match = re.search(r'<span class="code">(.*?)</span>', row_html, re.S | re.I)
        date_match = re.search(r'<span class="issued-date">(.*?)</span>', row_html, re.S | re.I)
        title_match = re.search(r'<span class="substract">(.*?)</span>', row_html, re.S | re.I)
        link_match = re.search(r"<a href='([^']*docid[^']*)'>", row_html, re.S | re.I)
        if not (code_match and title_match and link_match):
            continue
        href = link_match.group(1).strip()
        documents.append({
            'code': re.sub(r'\s+', ' ', unescape(code_match.group(1))).strip(),
            'issued_at': re.sub(r'\s+', ' ', unescape(date_match.group(1) if date_match else '')).strip(),
            'title': re.sub(r'\s+', ' ', unescape(title_match.group(1))).strip(),
            'url': requests.compat.urljoin('https://vanban.chinhphu.vn/', href),
        })
    return documents


def _legal_field_options(force_refresh=False):
    now = datetime.now()
    cache_entry = _LEGAL_DOCS_CACHE['fields']
    if not force_refresh and cache_entry['expires_at'] and cache_entry['expires_at'] > now and cache_entry['items']:
        return cache_entry['items']
    response = requests.get(LEGAL_DOCS_SOURCE_URL, timeout=20)
    response.raise_for_status()
    items = _parse_legal_field_options(response.text)
    _LEGAL_DOCS_CACHE['fields'] = {
        'expires_at': now + LEGAL_DOCS_CACHE_TTL,
        'items': items,
    }
    return items


def _legal_documents_by_field(field_id, limit=6, force_refresh=False):
    field_key = str(field_id or '').strip() or LEGAL_DOCS_DEFAULT_FIELD_ID
    now = datetime.now()
    cache_entry = _LEGAL_DOCS_CACHE['docs'].get(field_key)
    if not force_refresh and cache_entry and cache_entry['expires_at'] > now:
        return cache_entry['items'][:limit]

    session_client = requests.Session()
    initial = session_client.get(LEGAL_DOCS_SOURCE_URL, timeout=20)
    initial.raise_for_status()
    hidden_inputs = _extract_legal_hidden_inputs(initial.text)
    payload = {key: value for key, value in hidden_inputs.items() if key.startswith('__')}
    payload.update({
        'ctrl_191017_163$drdDocCategory': field_key,
        'ctrl_191017_163$drdDocOrg': '0',
        'ctrl_191017_163$txtSearchKeyword': '',
        'ctrl_191017_163$btnSearch': 'Tìm kiếm',
    })
    response = session_client.post(LEGAL_DOCS_SOURCE_URL, data=payload, timeout=20)
    response.raise_for_status()
    items = _parse_legal_documents(response.text)
    _LEGAL_DOCS_CACHE['docs'][field_key] = {
        'expires_at': now + LEGAL_DOCS_CACHE_TTL,
        'items': items,
    }
    return items[:limit]


def _bca_api_get(path, params=None):
    response = requests.get(
        f"{BCA_DOCS_API_BASE}{path}",
        params=params or {},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json() or {}
    return payload.get('data')


def _bca_cached_options(cache_key, path, params=None, force_refresh=False):
    now = datetime.now()
    cache_entry = _BCA_DOCS_CACHE[cache_key]
    if not force_refresh and cache_entry['expires_at'] and cache_entry['expires_at'] > now and cache_entry['items']:
        return cache_entry['items']
    items = _bca_api_get(path, params=params) or []
    _BCA_DOCS_CACHE[cache_key] = {
        'expires_at': now + LEGAL_DOCS_CACHE_TTL,
        'items': items,
    }
    return items


def _bca_document_groups(force_refresh=False):
    return _bca_cached_options('doc_groups', '/document/doc-group', force_refresh=force_refresh)


def _bca_document_types(force_refresh=False):
    return _bca_cached_options('document_types', '/document-type', force_refresh=force_refresh)


def _bca_effective_statuses(force_refresh=False):
    return _bca_cached_options('effective_status', '/effective-status', force_refresh=force_refresh)


def _bca_document_source_url(slug, doc_group):
    if not slug:
        return BCA_DOCS_SOURCE_URL
    path = 'van-ban-chi-dao-dieu-hanh' if doc_group == 'DIRECTIVE' else 'co-so-du-lieu-van-ban'
    return f"{BCA_DOCS_SOURCE_URL.rstrip('/')}/{path}/{slug}?tab=attributes"


def _bca_documents(doc_group='LAW', org_id=BCA_DOCS_DEFAULT_ORG_ID, type_id='', effective_id='', limit=6, force_refresh=False):
    group_value = (doc_group or BCA_DOCS_DEFAULT_GROUP).strip().upper() or BCA_DOCS_DEFAULT_GROUP
    org_value = (org_id or BCA_DOCS_DEFAULT_ORG_ID).strip() or BCA_DOCS_DEFAULT_ORG_ID
    type_value = (type_id or '').strip()
    effective_value = (effective_id or '').strip()
    cache_key = '|'.join([group_value, org_value, type_value, effective_value, str(limit)])
    now = datetime.now()
    cache_entry = _BCA_DOCS_CACHE['documents'].get(cache_key)
    if not force_refresh and cache_entry and cache_entry['expires_at'] > now:
        return cache_entry['items'][:limit]

    params = {
        'page': 0,
        'size': max(limit, 6),
        'docGroup': group_value,
        'orgId': org_value,
    }
    if type_value:
        params['typeId'] = type_value
    if effective_value:
        params['effectiveId'] = effective_value

    data = _bca_api_get('/document', params=params) or {}
    documents = []
    for item in data.get('content') or []:
        attached_files = item.get('attachedFiles') or []
        primary_attachment = attached_files[0] if attached_files else {}
        documents.append({
            'id': item.get('id'),
            'code': (item.get('documentCode') or '').strip(),
            'title': re.sub(r'\s+', ' ', item.get('title') or '').strip(),
            'issued_at': _format_display_date(item.get('issueDate')),
            'effective_at': _format_display_date(item.get('effectiveDate')),
            'document_type': (item.get('documentType') or '').strip(),
            'issuing_agency': (item.get('issuingAgency') or '').strip(),
            'doc_group': group_value,
            'file_url': primary_attachment.get('url') or '',
            'file_name': (primary_attachment.get('filename') or '').strip(),
            'source_url': _bca_document_source_url(item.get('slug'), group_value),
        })

    _BCA_DOCS_CACHE['documents'][cache_key] = {
        'expires_at': now + LEGAL_DOCS_CACHE_TTL,
        'items': documents,
    }
    return documents[:limit]


def _resolve_selected_option(options, selected_id, fallback_id='', allow_empty=False):
    normalized_selected = str(selected_id or '').strip()
    normalized_fallback = str(fallback_id or '').strip()
    available_ids = {str(item.get('id') or '').strip() for item in options}
    if allow_empty and not normalized_selected:
        chosen_id = ''
    elif normalized_selected and normalized_selected in available_ids:
        chosen_id = normalized_selected
    elif normalized_fallback and normalized_fallback in available_ids:
        chosen_id = normalized_fallback
    else:
        chosen_id = '' if allow_empty else (str(options[0].get('id') or '').strip() if options else '')
    chosen_label = ''
    for item in options:
        if str(item.get('id') or '').strip() == chosen_id:
            chosen_label = (item.get('name') or '').strip()
            break
    return chosen_id, chosen_label


def _load_contacts_from_excel(file_storage, has_header=True):
    read_kwargs = {'dtype': str, 'sheet_name': 0}
    read_kwargs['header'] = 0 if has_header else None
    df = pd.read_excel(io.BytesIO(file_storage.read()), **read_kwargs).fillna('')

    if df.empty:
        raise ValueError('File Excel không có dữ liệu.')

    if has_header:
        name_col = _find_import_column(df.columns, 'name')
        role_col = _find_import_column(df.columns, 'role')
        phone_col = _find_import_column(df.columns, 'phone')
        unit_col = _find_import_column(df.columns, 'unit_name')
        if not name_col or not phone_col:
            raise ValueError('Khi có tiêu đề, file phải nhận diện được ít nhất 2 cột: "Họ tên" và "Số điện thoại". Nếu có, hệ thống sẽ đọc thêm "Chức vụ" và "Đơn vị".')
    else:
        if len(df.columns) < 2:
            raise ValueError('Khi không có tiêu đề, file phải có ít nhất 2 cột: cột A là Họ tên, cột B là Số điện thoại.')
        name_col = df.columns[0]
        if len(df.columns) >= 4:
            role_col = df.columns[1]
            phone_col = df.columns[2]
            unit_col = df.columns[3]
        else:
            role_col = None
            phone_col = df.columns[1]
            unit_col = df.columns[2] if len(df.columns) >= 3 else None

    contacts = []
    skipped_empty = 0
    invalid_rows = []

    for idx, row in df.iterrows():
        name = _clean_import_text(row.get(name_col, ''))
        role = _clean_import_text(row.get(role_col, '')) if role_col is not None else ''
        phone = _normalize_import_phone(row.get(phone_col, ''))
        unit_name = _clean_import_text(row.get(unit_col, '')) if unit_col is not None else ''
        excel_row = idx + (2 if has_header else 1)

        if not name and not role and not phone and not unit_name:
            skipped_empty += 1
            continue

        if not name or not phone:
            invalid_rows.append(excel_row)
            continue

        contacts.append({
            'idx': len(contacts),
            'excel_row': int(excel_row),
            'name': name,
            'role': role,
            'phone': phone,
            'unit_name': unit_name
        })

    if not contacts:
        raise ValueError('Không tìm thấy dòng hợp lệ nào. Mỗi dòng phải có đủ Họ tên và Số điện thoại.')

    return {
        'rows': contacts,
        'total_rows': int(len(df.index)),
        'valid_rows': len(contacts),
        'skipped_empty': skipped_empty,
        'invalid_rows': invalid_rows
    }

@portal_bp.route('/news', methods=['GET', 'POST'])
def news():
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))
    
    role = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
    perms = json.loads(role.perms) if role and role.perms else {}
    is_news_lead = perms.get('p_news_lead') or session.get('is_admin')

    if request.method == 'POST' and is_news_lead:
        f = request.files.get('file')
        fn = ""
        if f and f.filename:
            # Validate file
            is_valid, message, safe_fn = validate_file_upload(f)
            if not is_valid:
                flash(f'Lỗi upload file: {message}', 'danger')
                return redirect(url_for('portal_bp.news'))
            fn = safe_fn
            f.save(os.path.join(current_app.root_path, 'uploads', fn))
        news_category_items = _module_category_options('news', 'category', 'Lĩnh vực', 'Đội nghiệp vụ')
        category_value = _canonicalize_category_value(
            request.form.get('category', ''),
            news_category_items,
            prefer_stable=True,
        )
        category_display = _resolve_category_display(category_value, news_category_items, fallback_label='').get('display_name') or request.form.get('category', '')
        db.session.add(NewsDoc(
            title=request.form['title'],
            category=category_value,
            content=request.form['content'],
            filename=fn
        ))
        db.session.commit()
        log_action(session['uid'], session['fullname'], "Đăng tin mới", "Bảng tin", request.form['title'])
        push_global_notif(f"Bảng tin: {category_display}", f"{request.form['title']}", "/news", exclude_uid=session['uid'])
        flash('Đã đăng tin mới!', 'success')
        return redirect(url_for('portal_bp.news'))
    now_str = datetime.now().strftime('Ngày %d tháng %m, %Y')

    news_category_items = _module_category_options('news', 'category', 'Lĩnh vực', 'Đội nghiệp vụ')
    if not news_category_items:
        news_category_items = _module_category_options('tasks', 'domain', 'Đội nghiệp vụ')
    news_records = NewsDoc.query.order_by(NewsDoc.uploaded_at.desc()).all()
    news_records = _sync_record_categories(news_records, news_category_items, prefer_stable=True)
    decorated_news = _decorate_records_with_category(news_records, news_category_items, allow_unknown_label=False)
    news_filters = _category_filter_counts(decorated_news, news_category_items)

    return render_template('news.html',
                          news_list=news_records,
                          news_cards=decorated_news,
                          category_filters=news_filters,
                          category_options=_stable_form_category_options(news_category_items),
                          cats=news_category_items,
                          pro_units=news_category_items,
                          now_str=now_str)

@portal_bp.route('/notifications')
def notifications():
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))
    from models import Notification
    notifs = Notification.query.filter_by(user_id=session['uid']).order_by(Notification.created_at.desc()).limit(20).all()
    # Mark as read when viewing the page
    Notification.query.filter_by(user_id=session['uid']).update({'is_read': 1})
    db.session.commit()
    return render_template('notifications.html', notifs=notifs)

@portal_bp.route('/library', methods=['GET', 'POST'])
def library():
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))
    
    role = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
    perms = json.loads(role.perms) if role and role.perms else {}
    is_lib_lead = perms.get('p_lib_lead') or session.get('is_admin')

    if request.method == 'POST' and is_lib_lead:
        f = request.files.get('file')
        if f and f.filename:
            # Validate file
            is_valid, message, safe_fn = validate_file_upload(f)
            if not is_valid:
                flash(f'Lỗi upload file: {message}', 'danger')
                return redirect(url_for('portal_bp.library'))
            fn = safe_fn
            f.save(os.path.join(current_app.root_path, 'library_files', fn))
            library_category_items = _module_category_options('library', 'category', 'Lĩnh vực', 'Loại tài liệu')
            category_value = _canonicalize_category_value(
                request.form.get('category', ''),
                library_category_items,
                prefer_stable=True,
            )
            db.session.add(DocumentLib(title=request.form['title'], category=category_value, filename=fn))
            db.session.commit()
            log_action(session['uid'], session['fullname'], "Tải lên tài liệu", "Thư viện", request.form['title'])
            push_global_notif("Thư viện", f"Tài liệu mới: {request.form['title']}", "/library", exclude_uid=session['uid'])
            flash('Đã tải lên tài liệu!', 'success')
        return redirect(url_for('portal_bp.library'))
    
    library_category_items = _module_category_options('library', 'category', 'Lĩnh vực', 'Loại tài liệu')
    docs = DocumentLib.query.order_by(DocumentLib.uploaded_at.desc()).all()
    docs = _sync_record_categories(docs, library_category_items, prefer_stable=True)
    decorated_docs = _decorate_records_with_category(docs, library_category_items, allow_unknown_label=False)
    library_filters = _category_filter_counts(decorated_docs, library_category_items)
    library_form_category_options = _stable_form_category_options(library_category_items)

    legal_field_options = []
    legal_docs = []
    legal_error = ''
    selected_legal_field = (request.args.get('legal_field') or '').strip()
    try:
        legal_field_options = _legal_field_options()
        available_ids = {item['id'] for item in legal_field_options}
        if not selected_legal_field or selected_legal_field not in available_ids:
            selected_legal_field = LEGAL_DOCS_DEFAULT_FIELD_ID if LEGAL_DOCS_DEFAULT_FIELD_ID in available_ids else (legal_field_options[0]['id'] if legal_field_options else '')
        if selected_legal_field:
            legal_docs = _legal_documents_by_field(selected_legal_field, limit=6)
    except Exception:
        legal_error = 'Không thể tải dữ liệu văn bản quy phạm pháp luật từ nguồn ngoài ở thời điểm này.'

    selected_legal_field_name = ''
    for item in legal_field_options:
        if item['id'] == selected_legal_field:
            selected_legal_field_name = item['name']
            break

    bca_doc_groups = []
    bca_document_types = []
    bca_effective_statuses = []
    bca_docs = []
    bca_error = ''
    selected_bca_doc_group = (request.args.get('bca_doc_group') or '').strip().upper()
    selected_bca_type_id = (request.args.get('bca_type_id') or '').strip()
    selected_bca_effective_id = (request.args.get('bca_effective_id') or '').strip()
    selected_bca_doc_group_name = ''
    selected_bca_type_name = ''
    selected_bca_effective_name = ''
    try:
        bca_doc_groups = _bca_document_groups()
        bca_document_types = _bca_document_types()
        bca_effective_statuses = _bca_effective_statuses()
        selected_bca_doc_group, selected_bca_doc_group_name = _resolve_selected_option(
            bca_doc_groups,
            selected_bca_doc_group,
            fallback_id=BCA_DOCS_DEFAULT_GROUP,
        )
        selected_bca_type_id, selected_bca_type_name = _resolve_selected_option(
            bca_document_types,
            selected_bca_type_id,
            fallback_id='',
            allow_empty=True,
        )
        selected_bca_effective_id, selected_bca_effective_name = _resolve_selected_option(
            bca_effective_statuses,
            selected_bca_effective_id,
            fallback_id='',
            allow_empty=True,
        )
        bca_docs = _bca_documents(
            doc_group=selected_bca_doc_group,
            type_id=selected_bca_type_id,
            effective_id=selected_bca_effective_id,
            limit=6,
        )
    except Exception:
        bca_error = 'Không thể tải hệ thống văn bản Bộ Công an ở thời điểm này.'

    return render_template(
        'library.html',
        docs=docs,
        doc_cards=decorated_docs,
        library_filters=library_filters,
        category_options=library_form_category_options,
        cats=library_category_items,
        categories=library_category_items,
        items=docs,
        legal_field_options=legal_field_options,
        selected_legal_field=selected_legal_field,
        selected_legal_field_name=selected_legal_field_name,
        legal_docs=legal_docs,
        legal_error=legal_error,
        legal_source_url=LEGAL_DOCS_SOURCE_URL,
        bca_doc_groups=bca_doc_groups,
        bca_document_types=bca_document_types,
        bca_effective_statuses=bca_effective_statuses,
        bca_docs=bca_docs,
        bca_error=bca_error,
        bca_source_url=BCA_DOCS_SOURCE_URL,
        selected_bca_doc_group=selected_bca_doc_group,
        selected_bca_doc_group_name=selected_bca_doc_group_name,
        selected_bca_type_id=selected_bca_type_id,
        selected_bca_type_name=selected_bca_type_name,
        selected_bca_effective_id=selected_bca_effective_id,
        selected_bca_effective_name=selected_bca_effective_name,
    )

@portal_bp.route('/contacts')
def contacts():
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))
    # Permissions
    role_obj = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
    perms = json.loads(role_obj.perms) if role_obj and role_obj.perms else {}
    is_admin = session.get('is_admin')
    is_contact_lead = perms.get('p_contact_lead') or is_admin
    user_unit = session.get('unit_area')
    contact_groups_items = _module_category_options('contacts', 'contact_group', 'Nhóm danh bạ')
    contact_roles_items = _module_category_options('contacts', 'role', 'Chức vụ')
    linhvuc_items = _module_category_options('contacts', 'category', 'Lĩnh vực')
    unit_items = _module_category_options('contacts', 'unit_name', 'Đơn vị')

    group_filter = request.args.get('group')
    canonical_group_filter = _canonicalize_category_value(group_filter or '', contact_groups_items, prefer_stable=True) if group_filter else ''
    scoped_query = Contact.query

    if not is_contact_lead:
        user_unit_matches = list(_category_match_values(user_unit, unit_items)) or [user_unit]
        scoped_query = scoped_query.filter(Contact.unit_name.in_(user_unit_matches))

    scoped_contacts = scoped_query.order_by(Contact.name.asc()).all()
    scoped_contacts = _sync_record_categories(scoped_contacts, contact_groups_items, attr_name='contact_group', prefer_stable=True)
    scoped_contacts = _sync_record_categories(scoped_contacts, contact_roles_items, attr_name='role', prefer_stable=True)
    scoped_contacts = _sync_record_categories(scoped_contacts, unit_items, attr_name='unit_name', prefer_stable=True)

    decorated_contacts = []
    for contact in scoped_contacts:
        group_info = _resolve_category_display(contact.contact_group, contact_groups_items, fallback_label='Chưa phân nhóm')
        role_info = _resolve_category_display(contact.role, contact_roles_items, fallback_label='Chưa cập nhật')
        unit_info = _resolve_category_display(contact.unit_name, unit_items, fallback_label='-')
        setattr(contact, 'contact_group_display', group_info['display_name'])
        setattr(contact, 'contact_group_filter', group_info['filter_value'])
        setattr(contact, 'role_display', role_info['display_name'])
        setattr(contact, 'unit_name_display', unit_info['display_name'])
        decorated_contacts.append({
            'category_filter': group_info['filter_value'],
        })

    contact_group_filters = _category_filter_counts(decorated_contacts, contact_groups_items, 'Chưa phân nhóm')
    current_group_info = _resolve_category_display(canonical_group_filter or group_filter or '', contact_groups_items, fallback_label='')
    current_group_filter = current_group_info['filter_value'] if canonical_group_filter else ''
    current_group_display = current_group_info['display_name'] if canonical_group_filter else ''
    contacts = [
        contact for contact in scoped_contacts
        if not current_group_filter or getattr(contact, 'contact_group_filter', '') == current_group_filter
    ]

    return render_template('contacts.html', 
                          contacts=contacts,
                          groups=contact_groups_items,
                          categories=contact_groups_items,
                          roles=_stable_form_category_options(contact_roles_items), 
                          linhvuc_items=linhvuc_items,
                          unit_items=_stable_form_category_options(unit_items),
                          contact_group_filters=contact_group_filters,
                          total_contact_count=len(scoped_contacts),
                          current_group=current_group_filter,
                          current_group_display=current_group_display)

@portal_bp.route('/contacts/edit/<int:cid>', methods=['POST'])
def contact_edit(cid):
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))
    
    role_obj = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
    perms = json.loads(role_obj.perms) if role_obj and role_obj.perms else {}
    is_contact_lead = perms.get('p_contact_lead') or session.get('is_admin')
    user_unit = session.get('unit_area')

    c = Contact.query.get_or_404(cid)
    unit_items = _module_category_options('contacts', 'unit_name', 'Đơn vị')
    user_unit_matches = _category_match_values(user_unit, unit_items)

    if not is_contact_lead and (c.unit_name or '') not in user_unit_matches:
        flash('Bạn không có quyền sửa liên lạc của đơn vị khác!', 'danger')
        return redirect(url_for('portal_bp.contacts'))
    role_items = _module_category_options('contacts', 'role', 'Chức vụ')
    contact_group_items = _module_category_options('contacts', 'contact_group', 'Nhóm danh bạ')
    c.name = request.form.get('name')
    c.phone = request.form.get('phone')
    c.role = _canonicalize_category_value(request.form.get('role'), role_items, prefer_stable=True)
    c.unit_name = _canonicalize_category_value(request.form.get('unit_name'), unit_items, prefer_stable=True)
    c.contact_group = _canonicalize_category_value(request.form.get('contact_group'), contact_group_items, prefer_stable=True)
    try:
        db.session.commit()
        flash('Đã cập nhật thông tin liên lạc!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi cập nhật: {e}', 'danger')
    return redirect(url_for('portal_bp.contacts'))

@portal_bp.route('/contacts/delete/<int:cid>', methods=['POST'])
def contact_delete(cid):
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))
    
    role_obj = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
    perms = json.loads(role_obj.perms) if role_obj and role_obj.perms else {}
    is_contact_lead = perms.get('p_contact_lead') or perms.get('p_contact_exec') or session.get('is_admin')
    user_unit = _get_current_user_unit()

    c = Contact.query.get_or_404(cid)
    unit_items = _module_category_options('contacts', 'unit_name', 'Đơn vị')
    user_unit_matches = _category_match_values(user_unit, unit_items)
    if not is_contact_lead and (c.unit_name or '') not in user_unit_matches:
        flash('Bạn không có quyền xóa liên lạc của đơn vị khác!', 'danger')
        return redirect(url_for('portal_bp.contacts'))
    try:
        db.session.delete(c)
        db.session.commit()
        flash('Đã xóa liên lạc khỏi danh bạ!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi xóa: {e}', 'danger')
    return redirect(url_for('portal_bp.contacts'))


@portal_bp.route('/contacts/delete-bulk', methods=['POST'])
def contact_delete_bulk():
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))

    role_obj = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
    perms = json.loads(role_obj.perms) if role_obj and role_obj.perms else {}
    is_contact_lead = perms.get('p_contact_lead') or perms.get('p_contact_exec') or session.get('is_admin')

    if not is_contact_lead:
        flash('Bạn không có quyền xóa danh bạ hàng loạt!', 'danger')
        return redirect(url_for('portal_bp.contacts'))

    selected_ids_raw = request.form.get('selected_ids', '[]')
    try:
        selected_ids = json.loads(selected_ids_raw)
    except Exception:
        selected_ids = []

    selected_ids = [int(cid) for cid in selected_ids if str(cid).isdigit()]
    if not selected_ids:
        flash('Bạn chưa chọn liên hệ nào để xóa.', 'warning')
        return redirect(url_for('portal_bp.contacts'))

    contacts = Contact.query.filter(Contact.id.in_(selected_ids)).all()
    if not contacts:
        flash('Không tìm thấy liên hệ hợp lệ để xóa.', 'warning')
        return redirect(url_for('portal_bp.contacts'))

    deleted_count = 0
    try:
        deleted_names = [c.name for c in contacts[:10]]
        for contact in contacts:
            db.session.delete(contact)
            deleted_count += 1
        db.session.commit()
        log_action(
            session['uid'],
            session['fullname'],
            "Xóa danh bạ hàng loạt",
            "Danh bạ",
            f"So luong: {deleted_count}; Mẫu: {', '.join(deleted_names)}"
        )
        flash(f'Đã xóa {deleted_count} liên hệ đã chọn.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi xóa hàng loạt: {e}', 'danger')
    return redirect(url_for('portal_bp.contacts'))

@portal_bp.route('/contacts/add', methods=['POST'])
def contact_add():
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))
    
    role_obj = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
    perms = json.loads(role_obj.perms) if role_obj and role_obj.perms else {}
    is_contact_lead = perms.get('p_contact_lead') or perms.get('p_contact_exec') or session.get('is_admin')
    user_unit = _get_current_user_unit()

    name = request.form.get('name')
    phone = request.form.get('phone')
    role_items = _module_category_options('contacts', 'role', 'Chức vụ')
    group_items = _module_category_options('contacts', 'contact_group', 'Nhóm danh bạ')
    unit_items = _module_category_options('contacts', 'unit_name', 'Đơn vị')
    role = _canonicalize_category_value(request.form.get('role'), role_items, prefer_stable=True)
    unit = _canonicalize_category_value(request.form.get('unit_name') or user_unit or '', unit_items, prefer_stable=True)
    
    if not is_contact_lead:
        unit = _canonicalize_category_value(user_unit, unit_items, prefer_stable=True) or user_unit
    group = request.form.get('contact_group')
    new_group_name = request.form.get('new_group_name')

    if group == 'NEW':
        new_group_name = (new_group_name or '').strip()
        if not new_group_name:
            flash('Bạn cần nhập tên nhóm danh bạ mới.', 'danger')
            return redirect(url_for('portal_bp.contacts'))

        group_bucket = get_bound_group('contacts', 'contact_group') or get_category_group('Nhóm danh bạ')
        existing = None
        if group_bucket:
            existing = CategoryItem.query.filter_by(group_id=group_bucket.id, name=new_group_name).first()
        else:
            existing = CategoryItem.query.filter_by(name=new_group_name).first()

        if not existing:
            new_g = CategoryItem(
                group_id=group_bucket.id if group_bucket else None,
                code=slugify_code(new_group_name),
                name=new_group_name,
                is_active=True
            )
            db.session.add(new_g)
            db.session.flush()
            group = f"category_item:{new_g.id}"
        else:
            group = f"category_item:{existing.id}"
    else:
        group = _canonicalize_category_value(group, group_items, prefer_stable=True)

    db.session.add(Contact(
        name=name,
        phone=phone,
        role=role,
        unit_name=unit,
        contact_group=group
    ))
    db.session.commit()
    log_action(session['uid'], session['fullname'], "Thêm liên lạc thủ công", "Danh bạ", name)
    flash(f'Đã thêm liên lạc {name} thành công!', 'success')
    return redirect(url_for('portal_bp.contacts'))

# Preview route - returns Excel data as JSON for preview
@portal_bp.route('/contacts/preview-import', methods=['POST'])
def contact_preview_import():
    """Preview Excel file and return data as JSON"""
    if not session.get('uid'): return {'error': 'Unauthorized'}, 401
    
    role_obj = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
    perms = json.loads(role_obj.perms) if role_obj and role_obj.perms else {}
    is_admin = session.get('is_admin')
    can_import_contacts = perms.get('p_contact_lead') or perms.get('p_contact_exec') or is_admin
    if not can_import_contacts:
        return {'error': 'Permission denied'}, 403
    
    f = request.files.get('import_excel')
    has_header = request.form.get('has_header', '1') == '1'
    if not f or not f.filename.lower().endswith(('.xlsx', '.xls')):
        return {'error': 'Invalid file'}, 400
    
    try:
        parsed = _load_contacts_from_excel(f, has_header=has_header)
        return {
            'success': True,
            'data': parsed['rows'][:50],
            'total': parsed['total_rows'],
            'valid_rows': parsed['valid_rows'],
            'skipped_empty': parsed['skipped_empty'],
            'invalid_rows': parsed['invalid_rows'][:20]
        }
    except Exception as e:
        return {'error': str(e)}, 500


@portal_bp.route('/contacts/import', methods=['POST'])
def contact_import():
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))

    role_obj = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
    perms = json.loads(role_obj.perms) if role_obj and role_obj.perms else {}
    is_admin = session.get('is_admin')
    can_import_contacts = perms.get('p_contact_lead') or perms.get('p_contact_exec') or is_admin

    if not can_import_contacts:
        flash('Chỉ PC06 mới có quyền nhập danh bạ hàng loạt!', 'danger')
        return redirect(url_for('portal_bp.contacts'))
    
    f = request.files.get('import_excel')
    global_group = (request.form.get('global_group') or '').strip()
    global_role = (request.form.get('global_role') or '').strip()
    has_header = request.form.get('has_header', '1') == '1'
    group_items = _module_category_options('contacts', 'contact_group', 'Nhóm danh bạ')
    role_items = _module_category_options('contacts', 'role', 'Chức vụ')
    unit_items = _module_category_options('contacts', 'unit_name', 'Đơn vị')
    global_group = _canonicalize_category_value(global_group, group_items, prefer_stable=True)
    global_role = _canonicalize_category_value(global_role, role_items, prefer_stable=True)

    if not global_group:
        flash('Bạn cần chọn nhóm danh bạ trước khi nhập.', 'danger')
        return redirect(url_for('portal_bp.contacts'))

    if f and f.filename.lower().endswith(('.xlsx', '.xls')):
        try:
            parsed = _load_contacts_from_excel(f, has_header=has_header)
            imported = 0
            user_unit = _get_current_user_unit()
            missing_role_rows = []

            for row in parsed['rows']:
                resolved_role = _canonicalize_category_value(
                    row.get('role') or global_role or '',
                    role_items,
                    prefer_stable=True,
                )
                if not resolved_role:
                    missing_role_rows.append(row['excel_row'])
                    continue
                db.session.add(Contact(
                    contact_group=global_group,
                    unit_name=_canonicalize_category_value(
                        row.get('unit_name') or user_unit or '',
                        unit_items,
                        prefer_stable=True,
                    ),
                    name=row['name'],
                    phone=row['phone'],
                    role=resolved_role
                ))
                imported += 1

            if imported == 0 and missing_role_rows:
                raise ValueError('Không có dòng nào được nhập vì thiếu chức vụ. Hãy thêm cột "Chức vụ" trong file hoặc chọn "Chức vụ mặc định".')
            db.session.commit()
            log_action(session['uid'], session['fullname'], "Import danh bạ hàng loạt", "Danh bạ", f"File: {f.filename}, {imported} liên hệ")

            warning_parts = []
            if parsed['skipped_empty']:
                warning_parts.append(f"bỏ qua {parsed['skipped_empty']} dòng trống")
            if parsed['invalid_rows']:
                warning_parts.append(f"bỏ qua các dòng thiếu dữ liệu: {', '.join(map(str, parsed['invalid_rows'][:10]))}")
            if missing_role_rows:
                warning_parts.append(f"bỏ qua các dòng thiếu chức vụ: {', '.join(map(str, missing_role_rows[:10]))}")

            flash_message = f'Đã nhập {imported} liên lạc thành công!'
            if warning_parts:
                flash_message = f"{flash_message} Đồng thời {'. '.join(warning_parts)}."
            flash(flash_message, 'success')
        except Exception as e: 
            db.session.rollback()
            flash(f'Lỗi import: {e}', 'danger')
    else:
        flash('Vui lòng chọn file Excel hợp lệ (.xlsx hoặc .xls).', 'danger')
    return redirect(url_for('portal_bp.contacts'))
