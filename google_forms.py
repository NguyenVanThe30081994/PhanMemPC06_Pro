# -*- coding: utf-8 -*-
import copy
import json
import re
import uuid
from datetime import datetime


GOOGLE_FORMS_READ_SCOPES = (
    "https://www.googleapis.com/auth/forms.body.readonly",
    "https://www.googleapis.com/auth/forms.responses.readonly",
)

GOOGLE_FORMS_MANAGE_SCOPES = (
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/forms.responses.readonly",
)

GOOGLE_FORMS_ITEM_KINDS = {
    "text",
    "textarea",
    "radio",
    "checkbox",
    "dropdown",
    "scale",
    "date",
    "time",
    "rating",
    "grid_radio",
    "grid_checkbox",
    "section",
    "page_break",
}

GOOGLE_FORMS_RATING_ICON_TYPES = {"STAR", "HEART", "THUMB_UP"}


class GoogleFormsError(RuntimeError):
    pass


class GoogleFormsConfigError(GoogleFormsError):
    pass


class GoogleFormsSyncError(GoogleFormsError):
    pass


class GoogleFormsValidationError(GoogleFormsError):
    pass


def extract_google_form_id(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"[A-Za-z0-9_-]{20,}", text):
        return text
    match = re.search(r"/forms/d/([A-Za-z0-9_-]+)", text)
    if match:
        return match.group(1)
    match = re.search(r"[?&]formId=([A-Za-z0-9_-]+)", text)
    if match:
        return match.group(1)
    return ""


def google_forms_enabled(config):
    return bool(config.get("GOOGLE_FORMS_ENABLED"))


def build_google_credentials(config, scopes=None):
    if not google_forms_enabled(config):
        raise GoogleFormsConfigError("Tích hợp Google Form chưa được bật trên máy chủ.")

    scopes = tuple(scopes or GOOGLE_FORMS_READ_SCOPES)
    raw_json = str(config.get("GOOGLE_FORMS_CREDENTIALS_JSON") or "").strip()
    credentials_file = str(config.get("GOOGLE_FORMS_CREDENTIALS_FILE") or "").strip()
    impersonated_user = str(config.get("GOOGLE_FORMS_IMPERSONATED_USER") or "").strip()

    if not raw_json and not credentials_file:
        raise GoogleFormsConfigError("Thiếu cấu hình credentials cho Google Form.")

    try:
        from google.oauth2 import service_account
    except Exception as exc:
        raise GoogleFormsConfigError(f"Không thể nạp thư viện Google Auth: {exc}") from exc

    try:
        if raw_json:
            info = json.loads(raw_json)
            credentials = service_account.Credentials.from_service_account_info(info, scopes=scopes)
        else:
            credentials = service_account.Credentials.from_service_account_file(credentials_file, scopes=scopes)
    except Exception as exc:
        raise GoogleFormsConfigError(f"Credentials Google Form không hợp lệ: {exc}") from exc

    if impersonated_user:
        credentials = credentials.with_subject(impersonated_user)
    return credentials


def build_google_forms_service(config, scopes=None):
    try:
        from googleapiclient.discovery import build
    except Exception as exc:
        raise GoogleFormsConfigError(f"Không thể nạp Google API client: {exc}") from exc

    credentials = build_google_credentials(config, scopes=scopes)
    return build("forms", "v1", credentials=credentials, cache_discovery=False)


def fetch_google_form_definition(service, form_id):
    try:
        return service.forms().get(formId=form_id).execute()
    except Exception as exc:
        raise GoogleFormsSyncError(f"Không thể đọc cấu trúc Google Form: {exc}") from exc


def fetch_google_form_responses(service, form_id, page_size=200):
    responses = []
    page_token = None
    try:
        while True:
            request = service.forms().responses().list(
                formId=form_id,
                pageSize=page_size,
                pageToken=page_token,
            )
            payload = request.execute() or {}
            responses.extend(payload.get("responses", []) or [])
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
    except Exception as exc:
        raise GoogleFormsSyncError(f"Không thể đồng bộ phản hồi Google Form: {exc}") from exc
    return responses


def _default_publish_settings():
    return {
        "isPublished": False,
        "isAcceptingResponses": False,
        "responderAccess": "anyone_with_link",
    }


def _default_matching():
    return {
        "mode": "unit",
        "match_field": "",
    }


def _safe_uuid(prefix="pc06"):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _coerce_bool(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _clean_str(value):
    return str(value or "").strip()


def _clean_list(values):
    cleaned = []
    for value in values or []:
        item = _clean_str(value)
        if item:
            cleaned.append(item)
    return cleaned


def _normalize_rating_icon_type(value):
    candidate = _clean_str(value).upper()
    return candidate if candidate in GOOGLE_FORMS_RATING_ICON_TYPES else "STAR"


def normalize_google_form_builder_schema(raw_schema, fallback_title="", fallback_description=""):
    payload = raw_schema if isinstance(raw_schema, dict) else {}
    form_info = payload.get("form_info") if isinstance(payload.get("form_info"), dict) else {}
    publish_settings = payload.get("publish_settings") if isinstance(payload.get("publish_settings"), dict) else {}
    matching = payload.get("matching") if isinstance(payload.get("matching"), dict) else {}

    title = _clean_str(form_info.get("title") or fallback_title)
    description = _clean_str(form_info.get("description") or fallback_description)
    if not title:
        raise GoogleFormsValidationError("Tiêu đề biểu mẫu Google không được để trống.")

    normalized = {
        "form_info": {
            "title": title,
            "description": description,
        },
        "items": [],
        "publish_settings": {
            "isPublished": _coerce_bool(publish_settings.get("isPublished"), False),
            "isAcceptingResponses": _coerce_bool(publish_settings.get("isAcceptingResponses"), False),
            "responderAccess": _clean_str(publish_settings.get("responderAccess") or "anyone_with_link") or "anyone_with_link",
        },
        "matching": {
            "mode": _clean_str(matching.get("mode") or "unit").lower() or "unit",
            "match_field": _clean_str(matching.get("match_field")),
        },
    }

    items = payload.get("items") or []
    if not isinstance(items, list):
        raise GoogleFormsValidationError("Danh sách câu hỏi Google Form không hợp lệ.")

    for index, raw_item in enumerate(items):
        if not isinstance(raw_item, dict):
            continue
        kind = _clean_str(raw_item.get("kind")).lower()
        if kind not in GOOGLE_FORMS_ITEM_KINDS:
            raise GoogleFormsValidationError(f"Câu hỏi #{index + 1} có loại không được hỗ trợ.")

        item = {
            "kind": kind,
            "title": _clean_str(raw_item.get("title")),
            "description": _clean_str(raw_item.get("description")),
            "required": _coerce_bool(raw_item.get("required"), False),
            "options": _clean_list(raw_item.get("options")),
            "rows": _clean_list(raw_item.get("rows")),
            "columns": _clean_list(raw_item.get("columns")),
            "settings": raw_item.get("settings") if isinstance(raw_item.get("settings"), dict) else {},
            "pc06_item_id": _clean_str(raw_item.get("pc06_item_id") or _safe_uuid("gf")),
            "unsupported": _coerce_bool(raw_item.get("unsupported"), False),
        }

        if kind not in {"section", "page_break"} and not item["title"]:
            raise GoogleFormsValidationError(f"Câu hỏi #{index + 1} chưa có tiêu đề.")
        if kind in {"radio", "checkbox", "dropdown"} and not item["options"]:
            raise GoogleFormsValidationError(f"Câu hỏi \"{item['title'] or index + 1}\" cần ít nhất một lựa chọn.")
        if kind == "scale":
            low = item["settings"].get("low")
            high = item["settings"].get("high")
            try:
                low = int(low)
                high = int(high)
            except Exception as exc:
                raise GoogleFormsValidationError(f"Câu hỏi thang điểm \"{item['title']}\" có cấu hình không hợp lệ.") from exc
            if high <= low:
                raise GoogleFormsValidationError(f"Câu hỏi thang điểm \"{item['title']}\" phải có high > low.")
            item["settings"] = {
                "low": low,
                "high": high,
                "low_label": _clean_str(item["settings"].get("low_label")),
                "high_label": _clean_str(item["settings"].get("high_label")),
            }
        elif kind == "date":
            item["settings"] = {
                "include_year": _coerce_bool(item["settings"].get("include_year"), True),
                "include_time": _coerce_bool(item["settings"].get("include_time"), False),
            }
        elif kind == "time":
            item["settings"] = {
                "duration": _coerce_bool(item["settings"].get("duration"), False),
            }
        elif kind == "rating":
            level = item["settings"].get("rating_scale_level") or item["settings"].get("level") or 5
            try:
                level = int(level)
            except Exception as exc:
                raise GoogleFormsValidationError(f"Câu hỏi đánh giá \"{item['title']}\" có mức không hợp lệ.") from exc
            if level < 2:
                raise GoogleFormsValidationError(f"Câu hỏi đánh giá \"{item['title']}\" phải có tối thiểu 2 mức.")
            item["settings"] = {
                "rating_scale_level": level,
                "icon_type": _normalize_rating_icon_type(item["settings"].get("icon_type")),
            }
        elif kind in {"grid_radio", "grid_checkbox"}:
            if not item["rows"] or not item["columns"]:
                raise GoogleFormsValidationError(f"Câu hỏi lưới \"{item['title']}\" cần đủ hàng và cột.")
            item["settings"] = {
                "shuffle_questions": _coerce_bool(item["settings"].get("shuffle_questions"), False),
            }
        else:
            item["settings"] = copy.deepcopy(item["settings"])

        normalized["items"].append(item)

    return normalized


def builder_schema_to_task_form_fields(builder_schema):
    normalized = normalize_google_form_builder_schema(builder_schema, fallback_title="Biểu mẫu")
    fields = []
    for index, item in enumerate(normalized["items"]):
        if item["kind"] in {"section", "page_break"}:
            continue

        field_type = "text"
        options_payload = {
            "pc06_item_id": item["pc06_item_id"],
            "kind": item["kind"],
        }
        if item["description"]:
            options_payload["description"] = item["description"]
        if item["kind"] == "textarea":
            field_type = "textarea"
        elif item["kind"] in {"radio", "dropdown"}:
            field_type = "radio"
            options_payload["choices"] = item["options"]
        elif item["kind"] == "checkbox":
            field_type = "checkbox"
            options_payload["choices"] = item["options"]
        elif item["kind"] == "scale":
            field_type = "number"
            options_payload.update(item["settings"])
        elif item["kind"] == "rating":
            field_type = "number"
            options_payload.update(item["settings"])
        elif item["kind"] in {"grid_radio", "grid_checkbox"}:
            field_type = "table"
            options_payload["rows"] = item["rows"]
            options_payload["columns"] = item["columns"]
            options_payload.update(item["settings"])
        elif item["kind"] in {"date", "time"}:
            field_type = "text"
            options_payload.update(item["settings"])

        fields.append(
            {
                "field_key": f"google_pc06_{item['pc06_item_id']}",
                "field_label": item["title"] or f"Câu hỏi {index + 1}",
                "field_type": field_type,
                "field_options_json": json.dumps(options_payload, ensure_ascii=False),
                "sort_order": len(fields),
                "is_required": bool(item["required"]),
            }
        )
    return fields


def _choice_options(values):
    return [{"value": value} for value in _clean_list(values)]


def _builder_item_to_question(item):
    question = {
        "required": bool(item.get("required")),
    }
    pc06_item_id = _clean_str(item.get("pc06_item_id"))
    if pc06_item_id:
        question["questionId"] = pc06_item_id

    kind = item.get("kind")
    settings = item.get("settings") or {}
    if kind == "text":
        question["textQuestion"] = {}
    elif kind == "textarea":
        question["textQuestion"] = {"paragraph": True}
    elif kind == "radio":
        question["choiceQuestion"] = {
            "type": "RADIO",
            "options": _choice_options(item.get("options")),
        }
    elif kind == "checkbox":
        question["choiceQuestion"] = {
            "type": "CHECKBOX",
            "options": _choice_options(item.get("options")),
        }
    elif kind == "dropdown":
        question["choiceQuestion"] = {
            "type": "DROP_DOWN",
            "options": _choice_options(item.get("options")),
        }
    elif kind == "scale":
        question["scaleQuestion"] = {
            "low": int(settings.get("low", 1)),
            "high": int(settings.get("high", 5)),
            "lowLabel": _clean_str(settings.get("low_label")),
            "highLabel": _clean_str(settings.get("high_label")),
        }
    elif kind == "date":
        question["dateQuestion"] = {
            "includeYear": _coerce_bool(settings.get("include_year"), True),
            "includeTime": _coerce_bool(settings.get("include_time"), False),
        }
    elif kind == "time":
        question["timeQuestion"] = {
            "duration": _coerce_bool(settings.get("duration"), False),
        }
    elif kind == "rating":
        question["ratingQuestion"] = {
            "ratingScaleLevel": int(settings.get("rating_scale_level", 5)),
            "iconType": _normalize_rating_icon_type(settings.get("icon_type")),
        }
    else:
        raise GoogleFormsValidationError(f"Loại câu hỏi Google Form chưa hỗ trợ: {kind}")
    return question


def _builder_item_to_form_item(item):
    kind = item.get("kind")
    base = {
        "title": _clean_str(item.get("title")),
        "description": _clean_str(item.get("description")),
    }
    pc06_item_id = _clean_str(item.get("pc06_item_id"))
    if pc06_item_id:
        base["itemId"] = pc06_item_id

    if kind == "section":
        base["textItem"] = {}
        return base
    if kind == "page_break":
        base["pageBreakItem"] = {}
        return base
    if kind in {"grid_radio", "grid_checkbox"}:
        row_type = "RADIO" if kind == "grid_radio" else "CHECKBOX"
        questions = []
        for row_title in item.get("rows") or []:
            questions.append(
                {
                    "required": bool(item.get("required")),
                    "rowQuestion": {"title": row_title},
                    "questionId": _safe_uuid("row"),
                }
            )
        base["questionGroupItem"] = {
            "questions": questions,
            "grid": {
                "columns": {
                    "type": row_type,
                    "options": _choice_options(item.get("columns")),
                },
                "shuffleQuestions": _coerce_bool((item.get("settings") or {}).get("shuffle_questions"), False),
            },
        }
        return base

    base["questionItem"] = {"question": _builder_item_to_question(item)}
    return base


def build_google_form_create_requests(builder_schema):
    normalized = normalize_google_form_builder_schema(builder_schema, fallback_title="Biểu mẫu")
    requests = []
    for index, item in enumerate(normalized["items"]):
        if item.get("unsupported"):
            continue
        requests.append(
            {
                "createItem": {
                    "item": _builder_item_to_form_item(item),
                    "location": {"index": index},
                }
            }
        )
    return requests


def _delete_all_items_requests(form_payload):
    requests = []
    items = list(form_payload.get("items") or [])
    for index in range(len(items) - 1, -1, -1):
        requests.append({"deleteItem": {"location": {"index": index}}})
    return requests


def build_google_form_update_requests(existing_form_payload, builder_schema):
    requests = []
    normalized = normalize_google_form_builder_schema(builder_schema, fallback_title="Biểu mẫu")
    requests.extend(_delete_all_items_requests(existing_form_payload or {}))
    for index, item in enumerate(normalized["items"]):
        if item.get("unsupported"):
            continue
        requests.append(
            {
                "createItem": {
                    "item": _builder_item_to_form_item(item),
                    "location": {"index": index},
                }
            }
        )
    return requests


def create_google_form(service, builder_schema, title, description="", unpublished=True):
    normalized = normalize_google_form_builder_schema(
        builder_schema,
        fallback_title=title,
        fallback_description=description,
    )
    body = {
        "info": {
            "title": normalized["form_info"]["title"],
        }
    }
    if normalized["form_info"]["description"]:
        body["info"]["description"] = normalized["form_info"]["description"]
    try:
        created = service.forms().create(body=body).execute() or {}
        form_id = created.get("formId")
        if not form_id:
            raise GoogleFormsSyncError("Google Forms API không trả về formId sau khi tạo.")
        requests = build_google_form_create_requests(normalized)
        if requests:
            batch_body = {"requests": requests}
            service.forms().batchUpdate(formId=form_id, body=batch_body).execute()
        if unpublished:
            publish_google_form(service, form_id, is_published=False, accept_responses=False)
        latest = fetch_google_form_definition(service, form_id)
    except GoogleFormsError:
        raise
    except Exception as exc:
        raise GoogleFormsSyncError(f"Không thể tạo Google Form: {exc}") from exc

    return {
        "form_id": form_id,
        "form_url": latest.get("responderUri") or created.get("responderUri") or f"https://docs.google.com/forms/d/{form_id}/viewform",
        "edit_url": f"https://docs.google.com/forms/d/{form_id}/edit",
        "revision_id": latest.get("revisionId") or created.get("revisionId") or "",
        "publish_settings": latest.get("publishSettings") or {},
        "raw": latest,
    }


def update_google_form(service, form_id, builder_schema, revision_id=None):
    normalized = normalize_google_form_builder_schema(builder_schema, fallback_title="Biểu mẫu")
    try:
        latest = fetch_google_form_definition(service, form_id)
        requests = [
            {
                "updateFormInfo": {
                    "info": {
                        "title": normalized["form_info"]["title"],
                        "description": normalized["form_info"]["description"],
                    },
                    "updateMask": "title,description",
                }
            }
        ]
        requests.extend(build_google_form_update_requests(latest, normalized))
        body = {"requests": requests}
        if revision_id:
            body["writeControl"] = {"requiredRevisionId": revision_id}
        response = service.forms().batchUpdate(formId=form_id, body=body).execute() or {}
        latest = fetch_google_form_definition(service, form_id)
    except GoogleFormsError:
        raise
    except Exception as exc:
        raise GoogleFormsSyncError(f"Không thể cập nhật Google Form: {exc}") from exc

    return {
        "form_id": form_id,
        "form_url": latest.get("responderUri") or f"https://docs.google.com/forms/d/{form_id}/viewform",
        "edit_url": f"https://docs.google.com/forms/d/{form_id}/edit",
        "revision_id": latest.get("revisionId") or response.get("writeControl", {}).get("requiredRevisionId") or "",
        "publish_settings": latest.get("publishSettings") or {},
        "raw": latest,
    }


def publish_google_form(service, form_id, is_published=True, accept_responses=True):
    desired_accepting = bool(accept_responses and is_published)
    body = {
        "publishSettings": {
            "publishState": {
                "isPublished": bool(is_published),
                "isAcceptingResponses": desired_accepting,
            }
        },
        "updateMask": "publishState",
    }
    try:
        response = service.forms().setPublishSettings(formId=form_id, body=body).execute() or {}
    except Exception as exc:
        raise GoogleFormsSyncError(f"Không thể cập nhật trạng thái phát hành Google Form: {exc}") from exc
    return response


def _question_type_payload(question):
    if not isinstance(question, dict):
        return "text", {}

    choice = question.get("choiceQuestion") or {}
    if choice:
        raw_type = str(choice.get("type") or "").strip().upper()
        options = [item.get("value", "").strip() for item in choice.get("options", []) if item.get("value")]
        if raw_type == "CHECKBOX":
            return "checkbox", {"choices": options}
        if raw_type == "DROP_DOWN":
            return "dropdown", {"choices": options}
        return "radio", {"choices": options}

    text_question = question.get("textQuestion") or {}
    if text_question:
        if text_question.get("paragraph"):
            return "textarea", {}
        return "text", {}

    scale_question = question.get("scaleQuestion") or {}
    if scale_question:
        return "scale", {
            "low": scale_question.get("low"),
            "high": scale_question.get("high"),
            "low_label": scale_question.get("lowLabel"),
            "high_label": scale_question.get("highLabel"),
        }

    date_question = question.get("dateQuestion") or {}
    if date_question:
        return "date", {
            "include_year": bool(date_question.get("includeYear")),
            "include_time": bool(date_question.get("includeTime")),
        }

    time_question = question.get("timeQuestion") or {}
    if time_question:
        return "time", {"duration": bool(time_question.get("duration"))}

    if question.get("fileUploadQuestion"):
        return "unsupported", {"source": "file_upload"}

    row_question = question.get("rowQuestion") or {}
    if row_question:
        return "row", {"title": _clean_str(row_question.get("title"))}

    rating_question = question.get("ratingQuestion") or {}
    if rating_question:
        return "rating", {
            "rating_scale_level": rating_question.get("ratingScaleLevel"),
            "icon_type": _normalize_rating_icon_type(rating_question.get("iconType")),
        }

    return "text", {}


def parse_google_form_definition(form_payload):
    fields = []
    question_map = {}
    items = list((form_payload or {}).get("items") or [])
    for index, item in enumerate(items):
        title = str(item.get("title") or "").strip()
        description = str(item.get("description") or "").strip()
        if item.get("questionGroupItem"):
            group = item.get("questionGroupItem") or {}
            grid = group.get("grid") or {}
            columns = [
                option.get("value", "").strip()
                for option in (grid.get("columns") or {}).get("options", []) or []
                if option.get("value")
            ]
            column_type = str((grid.get("columns") or {}).get("type") or "RADIO").strip().upper()
            row_defs = []
            question_ids = []
            for row_index, question in enumerate(group.get("questions") or []):
                question_id = str(question.get("questionId") or "").strip()
                row_payload = question.get("rowQuestion") or {}
                row_title = str(row_payload.get("title") or f"Dòng {row_index + 1}").strip()
                row_defs.append({"title": row_title, "question_id": question_id})
                if question_id:
                    question_ids.append(question_id)
            field_key = f"google_group_{item.get('itemId') or index}"
            field_type = "table"
            field_options = {
                "kind": "grid_checkbox" if column_type == "CHECKBOX" else "grid_radio",
                "columns": columns,
                "rows": [row["title"] for row in row_defs],
                "question_ids": question_ids,
                "description": description,
            }
            fields.append(
                {
                    "field_key": field_key,
                    "field_label": title or f"Câu hỏi {len(fields) + 1}",
                    "field_type": field_type,
                    "field_options_json": json.dumps(field_options, ensure_ascii=False),
                    "sort_order": len(fields),
                    "is_required": any(bool(row.get("required")) for row in group.get("questions") or []),
                }
            )
            for row in row_defs:
                question_map[row["question_id"]] = {
                    "field_key": field_key,
                    "field_label": title or f"Câu hỏi {len(fields)}",
                    "field_type": field_type,
                    "row_title": row["title"],
                    "row_titles": [row_def["title"] for row_def in row_defs],
                    "options": field_options,
                    "item_index": index,
                }
            continue

        if item.get("textItem"):
            continue
        if item.get("pageBreakItem"):
            continue

        question_item = item.get("questionItem") or {}
        question = question_item.get("question") or {}
        question_id = str(question.get("questionId") or "").strip()
        if not question_id:
            continue
        field_type, options_payload = _question_type_payload(question)
        field_label = title or f"Câu hỏi {len(fields) + 1}"
        field_key = f"google_q_{question_id}"
        field_options = dict(options_payload or {})
        field_options["question_id"] = question_id
        if description:
            field_options["description"] = description
        mapped_field_type = field_type
        if field_type == "scale":
            mapped_field_type = "number"
        elif field_type == "rating":
            mapped_field_type = "number"
        elif field_type == "unsupported":
            mapped_field_type = "textarea"
        field_def = {
            "field_key": field_key,
            "field_label": field_label,
            "field_type": mapped_field_type,
            "field_options_json": json.dumps(field_options, ensure_ascii=False),
            "sort_order": len(fields),
            "is_required": bool(question.get("required")),
        }
        fields.append(field_def)
        question_map[question_id] = {
            "field_key": field_key,
            "field_label": field_label,
            "field_type": field_type,
            "sort_order": len(fields) - 1,
            "options": field_options,
            "item_index": index,
        }
    return fields, question_map


def builder_schema_from_form_definition(form_payload):
    info = (form_payload or {}).get("info") or {}
    publish_state = ((form_payload or {}).get("publishSettings") or {}).get("publishState") or {}
    builder = {
        "form_info": {
            "title": _clean_str(info.get("title")),
            "description": _clean_str(info.get("description")),
        },
        "publish_settings": {
            "isPublished": bool(publish_state.get("isPublished")),
            "isAcceptingResponses": bool(publish_state.get("isAcceptingResponses")),
            "responderAccess": "anyone_with_link",
        },
        "matching": _default_matching(),
        "items": [],
    }
    for index, item in enumerate((form_payload or {}).get("items") or []):
        item_id = _clean_str(item.get("itemId") or _safe_uuid("import"))
        title = _clean_str(item.get("title"))
        description = _clean_str(item.get("description"))
        if item.get("textItem"):
            builder["items"].append(
                {
                    "kind": "section",
                    "title": title,
                    "description": description,
                    "required": False,
                    "options": [],
                    "rows": [],
                    "columns": [],
                    "settings": {},
                    "pc06_item_id": item_id,
                }
            )
            continue
        if item.get("pageBreakItem"):
            builder["items"].append(
                {
                    "kind": "page_break",
                    "title": title,
                    "description": description,
                    "required": False,
                    "options": [],
                    "rows": [],
                    "columns": [],
                    "settings": {},
                    "pc06_item_id": item_id,
                }
            )
            continue
        if item.get("questionGroupItem"):
            group = item.get("questionGroupItem") or {}
            column_type = str(((group.get("grid") or {}).get("columns") or {}).get("type") or "RADIO").upper()
            columns = [
                _clean_str(option.get("value"))
                for option in (((group.get("grid") or {}).get("columns") or {}).get("options") or [])
                if _clean_str(option.get("value"))
            ]
            rows = []
            required = False
            for question in group.get("questions") or []:
                row_question = question.get("rowQuestion") or {}
                rows.append(_clean_str(row_question.get("title")))
                required = required or bool(question.get("required"))
            builder["items"].append(
                {
                    "kind": "grid_checkbox" if column_type == "CHECKBOX" else "grid_radio",
                    "title": title,
                    "description": description,
                    "required": required,
                    "options": [],
                    "rows": rows,
                    "columns": columns,
                    "settings": {
                        "shuffle_questions": bool((group.get("grid") or {}).get("shuffleQuestions")),
                    },
                    "pc06_item_id": item_id,
                }
            )
            continue
        question = ((item.get("questionItem") or {}).get("question") or {})
        kind, payload = _question_type_payload(question)
        builder_item = {
            "kind": kind if kind in GOOGLE_FORMS_ITEM_KINDS else "text",
            "title": title or f"Câu hỏi {index + 1}",
            "description": description,
            "required": bool(question.get("required")),
            "options": [],
            "rows": [],
            "columns": [],
            "settings": {},
            "pc06_item_id": item_id,
        }
        if kind in {"radio", "checkbox", "dropdown"}:
            builder_item["options"] = payload.get("choices") or []
        elif kind == "scale":
            builder_item["settings"] = {
                "low": payload.get("low"),
                "high": payload.get("high"),
                "low_label": payload.get("low_label"),
                "high_label": payload.get("high_label"),
            }
        elif kind == "date":
            builder_item["settings"] = {
                "include_year": bool(payload.get("include_year")),
                "include_time": bool(payload.get("include_time")),
            }
        elif kind == "time":
            builder_item["settings"] = {"duration": bool(payload.get("duration"))}
        elif kind == "rating":
            builder_item["settings"] = {
                "rating_scale_level": payload.get("rating_scale_level"),
                "icon_type": payload.get("icon_type"),
            }
        elif kind == "unsupported":
            builder_item["kind"] = "section"
            builder_item["description"] = (description + "\n[Câu hỏi file upload không hỗ trợ chỉnh sửa qua API]").strip()
            builder_item["unsupported"] = True
        builder["items"].append(builder_item)

    return normalize_google_form_builder_schema(
        builder,
        fallback_title=_clean_str(info.get("title") or "Biểu mẫu"),
        fallback_description=_clean_str(info.get("description")),
    )


def load_google_form_into_builder(service, form_id):
    try:
        payload = fetch_google_form_definition(service, form_id)
    except Exception as exc:
        raise GoogleFormsSyncError(f"Không thể nhập cấu trúc từ Google Form: {exc}") from exc
    builder = builder_schema_from_form_definition(payload)
    return {
        "builder_schema": builder,
        "form_payload": payload,
    }


def _parse_answer_value(answer, meta):
    field_type = meta.get("field_type")
    if field_type == "table":
        row_title = meta.get("row_title")
        text_answers = answer.get("textAnswers") or {}
        values = [item.get("value", "") for item in text_answers.get("answers", []) if item.get("value") is not None]
        return row_title, values if len(values) > 1 else (values[0] if values else "")

    text_answers = answer.get("textAnswers") or {}
    if text_answers:
        values = [item.get("value", "") for item in text_answers.get("answers", []) if item.get("value") is not None]
        if field_type == "checkbox":
            return None, values
        if len(values) > 1:
            return None, values
        return None, values[0] if values else ""

    file_upload_answers = answer.get("fileUploadAnswers") or {}
    if file_upload_answers:
        files = []
        for item in file_upload_answers.get("answers", []) or []:
            files.append(
                {
                    "file_id": item.get("fileId"),
                    "file_name": item.get("fileName"),
                    "mime_type": item.get("mimeType"),
                }
            )
        return None, files
    return None, ""


def _parse_google_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def parse_google_form_responses(form_payload, responses_payload):
    fields, question_map = parse_google_form_definition(form_payload)
    parsed = []
    for response in responses_payload or []:
        raw_answers = response.get("answers") or {}
        payload = {}
        payload_by_label = {}
        for question_id, answer in raw_answers.items():
            meta = question_map.get(question_id) or {
                "field_key": f"google_q_{question_id}",
                "field_label": question_id,
                "field_type": "text",
            }
            row_title, value = _parse_answer_value(answer or {}, meta)
            if meta.get("field_type") == "table":
                existing = payload.get(meta["field_key"])
                if existing is None:
                    existing = {title: "" for title in meta.get("row_titles") or []}
                if row_title:
                    existing[row_title] = value
                payload[meta["field_key"]] = existing
                payload_by_label[f"{meta['field_label']} / {row_title}"] = value
            else:
                payload[meta["field_key"]] = value
                payload_by_label[meta["field_label"]] = value
        for key, value in list(payload.items()):
            if isinstance(value, dict):
                payload[key] = [value.get(row_title, "") for row_title in value.keys()]
        parsed.append(
            {
                "response_id": str(response.get("responseId") or "").strip(),
                "respondent_email": str(response.get("respondentEmail") or "").strip(),
                "submitted_at": _parse_google_datetime(
                    response.get("lastSubmittedTime") or response.get("createTime")
                ),
                "payload": payload,
                "payload_by_label": payload_by_label,
                "raw": response,
            }
        )
    return fields, parsed
