# -*- coding: utf-8 -*-
import copy
import json
import re
from datetime import datetime

from utils import remove_accents


AI_ENGINE_NAME = "pc06-task-import-ai"

_STOPWORDS = {
    "bao", "cao", "cong", "tac", "thuc", "hien", "tong", "hop", "noi", "dung",
    "de", "cuong", "theo", "cho", "va", "cua", "cac", "don", "vi", "nguoi",
    "thang", "tuan", "ngay", "phan", "muc", "yeu", "cau", "du", "lieu", "form",
    "google", "excel", "word", "txt", "mau", "nhap", "xuat", "giao", "viec",
}

_NUMERIC_MARKERS = (
    "chi tieu", "so lieu", "tong so", "tong hop so", "ty le", "phan tram", "thong ke",
    "so ho so", "tong ho so", "san luong", "chi so", "so vu", "so truong hop",
)

_ATTACHMENT_MARKERS = (
    "file", "tep", "dinh kem", "minh chung", "phu luc", "anh", "video", "scan",
    "van ban", "quyet dinh", "ke hoach", "danh sach", "bang tong hop", "excel",
    "bieu mau", "tai lieu", "bien ban",
)

_URGENT_MARKERS = ("khan", "gap", "ngay", "truoc", "han", "som")

_OUTLINE_ASSIGNMENT_HINTS = (
    "giao tung muc", "phan cong tung muc", "theo tung dong", "moi don vi", "moi muc",
)
_SOURCE_TYPE_LABELS = {
    "docx_outline": "Word/TXT de cuong cong tac",
    "docx_report_outline": "Word/TXT de cuong bao cao",
    "xlsx_form": "Excel bieu mau",
    "google_form_remote": "Google Form",
    "blueprint_json": "Blueprint JSON",
}


def _normalize_text(value):
    text = remove_accents(str(value or "")).replace("_", " ").replace("-", " ")
    text = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _tokenize(value):
    normalized = _normalize_text(value)
    if not normalized:
        return []
    return [
        token
        for token in normalized.split()
        if len(token) >= 2 and token not in _STOPWORDS
    ]


def _overlap_score(text_a, text_b):
    tokens_a = set(_tokenize(text_a))
    tokens_b = set(_tokenize(text_b))
    if not tokens_a or not tokens_b:
        return 0.0
    overlap = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    if union <= 0:
        return 0.0
    score = overlap / union
    normalized_a = _normalize_text(text_a)
    normalized_b = _normalize_text(text_b)
    if normalized_b and normalized_b in normalized_a:
        score += 0.25
    return min(score, 1.0)


def _contains_any_marker(text, markers):
    normalized = _normalize_text(text)
    if not normalized:
        return False
    return any(marker in normalized for marker in markers)


def _catalog_entry(raw_item, item_type):
    return {
        "type": item_type,
        "id": raw_item.get("id"),
        "value": raw_item.get("value"),
        "label": raw_item.get("name") or raw_item.get("label") or raw_item.get("fullname") or raw_item.get("username") or "",
        "tokens": _tokenize(raw_item.get("name") or raw_item.get("label") or raw_item.get("fullname") or raw_item.get("username") or ""),
        "raw": raw_item,
    }


def _confidence_label(score):
    if score >= 0.85:
        return "rất cao"
    if score >= 0.6:
        return "cao"
    if score >= 0.35:
        return "trung bình"
    return "thấp"


def _pick_best_candidates(text, catalog, limit=3):
    ranked = []
    for entry in catalog or []:
        score = _overlap_score(text, entry.get("label"))
        if score <= 0:
            continue
        ranked.append(
            {
                "score": round(score, 4),
                "label": entry.get("label") or "",
                "id": entry.get("id"),
                "value": entry.get("value"),
                "type": entry.get("type"),
            }
        )
    ranked.sort(key=lambda item: (-item["score"], item["label"]))
    return ranked[:limit]


def _history_assignment_candidates(text, history_entries, limit=3, current_domain="", current_category=""):
    ranked = []
    normalized_current_domain = _normalize_text(current_domain)
    normalized_current_category = _normalize_text(current_category)
    for entry in history_entries or []:
        score = _overlap_score(text, entry.get("title"))
        if score < 0.3:
            continue
        domain_match_bonus = 0.0
        category_match_bonus = 0.0
        if normalized_current_domain and normalized_current_domain == _normalize_text(entry.get("domain")):
            domain_match_bonus = 0.18
        if normalized_current_category and normalized_current_category == _normalize_text(entry.get("category")):
            category_match_bonus = 0.1
        submitted_rate = float(entry.get("submitted_rate") or 0.0)
        completed_rate = float(entry.get("completed_rate") or 0.0)
        on_time_rate = float(entry.get("on_time_rate") or 0.0)
        raw_history_quality_score = (
            score
            + domain_match_bonus
            + category_match_bonus
            + submitted_rate * 0.08
            + completed_rate * 0.16
            + on_time_rate * 0.14
        )
        history_quality_score = min(raw_history_quality_score, 1.0)
        ranked.append(
            {
                "score": round(score, 4),
                "history_quality_score": round(history_quality_score, 4),
                "raw_history_quality_score": round(raw_history_quality_score, 4),
                "title": entry.get("title") or "",
                "category": entry.get("category") or "",
                "domain": entry.get("domain") or "",
                "assign_type": entry.get("assign_type") or "",
                "unit_domains": list(entry.get("unit_domains") or []),
                "role_ids": list(entry.get("role_ids") or []),
                "user_ids": list(entry.get("user_ids") or []),
                "total_assignments": int(entry.get("total_assignments") or 0),
                "submitted_assignments": int(entry.get("submitted_assignments") or 0),
                "completed_assignments": int(entry.get("completed_assignments") or 0),
                "submitted_rate": submitted_rate,
                "completed_rate": completed_rate,
                "on_time_assignments": int(entry.get("on_time_assignments") or 0),
                "late_assignments": int(entry.get("late_assignments") or 0),
                "on_time_rate": on_time_rate,
                "deadline_tracked": bool(entry.get("deadline_tracked")),
                "domain_match_bonus": round(domain_match_bonus, 4),
                "category_match_bonus": round(category_match_bonus, 4),
            }
        )
    ranked.sort(key=lambda item: (-item["raw_history_quality_score"], -item["history_quality_score"], -item["score"], item["title"]))
    return ranked[:limit]


def _suggest_title(config):
    title = str(config.get("title") or "").strip()
    if title:
        return title[:255]
    source_name = str(config.get("source_name") or "").strip()
    if source_name:
        return source_name[:255]
    collection_mode = str(config.get("collection_mode") or "file").strip().lower()
    if collection_mode == "outline":
        return "Đợt giao việc điều hành"
    if collection_mode == "form":
        return "Biểu mẫu thu thập báo cáo"
    return "Đợt báo cáo tổng hợp"


def _suggest_summary(config):
    summary = str(config.get("summary") or "").strip()
    if summary:
        return summary[:4000]
    collection_mode = str(config.get("collection_mode") or "file").strip().lower()
    if collection_mode == "outline":
        count = len([item for item in (config.get("items") or []) if str(item.get("title") or "").strip()])
        return f"Đợt điều hành gồm {count} đầu mục, giao cho các đơn vị xử lý và báo cáo kết quả trong hệ thống."
    if collection_mode == "form":
        count = len([field for field in (config.get("form_fields") or []) if str(field.get('field_label') or '').strip()])
        return f"Biểu mẫu thu thập {count} trường dữ liệu, dùng để chuẩn hóa báo cáo và tổng hợp số liệu."
    count = len([field for field in (config.get("report_fields") or []) if str(field.get('label') or '').strip()])
    return f"Nhiệm vụ báo cáo tổng hợp có {count} chỉ tiêu cấu trúc kèm phần thuyết minh và minh chứng."


def _infer_priority(text):
    return "Cao" if _contains_any_marker(text, _URGENT_MARKERS) else "Trung bình"


def _suggest_catalog_value(text, options):
    ranked = _pick_best_candidates(text, options, limit=1)
    if not ranked:
        return "", "", 0.0
    top = ranked[0]
    return top.get("value") or "", top.get("label") or "", float(top.get("score") or 0.0)


def _assignment_has_targets(assign_type, unit_domains=None, role_ids=None, user_ids=None, fallback_domain=""):
    normalized = str(assign_type or "").strip().lower()
    if normalized == "unit":
        return bool([value for value in (unit_domains or []) if str(value or "").strip()] or [fallback_domain] if str(fallback_domain or "").strip() else [])
    if normalized == "role":
        return bool([value for value in (role_ids or []) if str(value).isdigit()])
    if normalized == "user":
        return bool([value for value in (user_ids or []) if str(value).isdigit()])
    return False


def _build_assignment_display(suggestion, context):
    unit_lookup = context.get("unit_lookup") or {}
    role_lookup = context.get("role_lookup") or {}
    user_lookup = context.get("user_lookup") or {}
    display_targets = []
    assign_type = suggestion.get("assign_type") or ""
    if assign_type == "unit":
        for value in suggestion.get("unit_domains") or []:
            display_targets.append(unit_lookup.get(value) or value)
    elif assign_type == "role":
        for value in suggestion.get("role_ids") or []:
            display_targets.append(role_lookup.get(int(value), str(value)))
    elif assign_type == "user":
        for value in suggestion.get("user_ids") or []:
            display_targets.append(user_lookup.get(int(value), str(value)))
    return display_targets


def _history_execution_reason(entry):
    total = int(entry.get("total_assignments") or 0)
    submitted = int(entry.get("submitted_assignments") or 0)
    completed = int(entry.get("completed_assignments") or 0)
    if total <= 0:
        return "Chưa có dữ liệu thực thi."
    if completed > 0:
        base_text = f"Lịch sử thực hiện: {completed}/{total} đã hoàn thành, {submitted}/{total} đã nộp."
    else:
        base_text = f"Lịch sử thực hiện: {submitted}/{total} đã nộp."
    if bool(entry.get("deadline_tracked")):
        on_time = int(entry.get("on_time_assignments") or 0)
        late = int(entry.get("late_assignments") or 0)
        base_text += f" Đúng hạn: {on_time}, trễ hạn: {late}."
    return base_text


def _history_specialty_reason(entry):
    reasons = []
    if float(entry.get("domain_match_bonus") or 0.0) > 0:
        reasons.append("Trùng đội nghiệp vụ với nháp hiện tại.")
    if float(entry.get("category_match_bonus") or 0.0) > 0:
        reasons.append("Trùng lĩnh vực với nháp hiện tại.")
    return " ".join(reasons)


def _semantic_fit_signal(score):
    if score >= 0.72:
        return {
            "key": "semantic_strong",
            "label": "Khớp nội dung mạnh",
            "tone": "primary",
            "detail": f"Điểm khớp ngữ nghĩa {round(score, 2)}.",
        }
    if score >= 0.4:
        return {
            "key": "semantic_medium",
            "label": "Khớp nội dung khá",
            "tone": "info",
            "detail": f"Điểm khớp ngữ nghĩa {round(score, 2)}.",
        }
    return None


def _history_fit_signals(entry):
    signals = []
    completed_rate = float(entry.get("completed_rate") or 0.0)
    submitted_rate = float(entry.get("submitted_rate") or 0.0)
    on_time_rate = float(entry.get("on_time_rate") or 0.0)
    if float(entry.get("domain_match_bonus") or 0.0) > 0:
        signals.append(
            {
                "key": "domain_match",
                "label": "Phù hợp chuyên môn",
                "tone": "success",
                "detail": "Trùng đội nghiệp vụ với nháp hiện tại.",
            }
        )
    if float(entry.get("category_match_bonus") or 0.0) > 0:
        signals.append(
            {
                "key": "category_match",
                "label": "Đúng lĩnh vực",
                "tone": "success",
                "detail": "Trùng lĩnh vực nghiệp vụ với nháp hiện tại.",
            }
        )
    if completed_rate >= 0.8:
        signals.append(
            {
                "key": "completion_strong",
                "label": "Lịch sử hoàn thành tốt",
                "tone": "success",
                "detail": f"Tỷ lệ hoàn thành {round(completed_rate * 100)}%.",
            }
        )
    elif submitted_rate >= 0.8:
        signals.append(
            {
                "key": "submission_strong",
                "label": "Lịch sử nộp báo cáo tốt",
                "tone": "info",
                "detail": f"Tỷ lệ nộp {round(submitted_rate * 100)}%.",
            }
        )
    if bool(entry.get("deadline_tracked")) and on_time_rate >= 0.8:
        signals.append(
            {
                "key": "on_time_strong",
                "label": "Đúng hạn tốt",
                "tone": "warning",
                "detail": f"Tỷ lệ đúng hạn {round(on_time_rate * 100)}%.",
            }
        )
    return signals


def _normalized_workload_entry(raw_entry):
    if not isinstance(raw_entry, dict):
        return {
            "active_assignments": 0,
            "overdue_assignments": 0,
            "due_soon_assignments": 0,
            "high_priority_assignments": 0,
            "titles": [],
        }
    return {
        "active_assignments": max(int(raw_entry.get("active_assignments") or 0), 0),
        "overdue_assignments": max(int(raw_entry.get("overdue_assignments") or 0), 0),
        "due_soon_assignments": max(int(raw_entry.get("due_soon_assignments") or 0), 0),
        "high_priority_assignments": max(int(raw_entry.get("high_priority_assignments") or 0), 0),
        "titles": [str(title or "").strip() for title in (raw_entry.get("titles") or []) if str(title or "").strip()][:5],
    }


def _context_workload_map(context, key_name):
    raw_map = context.get(key_name) or {}
    normalized = {}
    if not isinstance(raw_map, dict):
        return normalized
    for raw_key, raw_entry in raw_map.items():
        key = raw_key
        if key_name in {"user_workload_map", "role_workload_map"}:
            try:
                key = int(raw_key)
            except Exception:
                continue
        else:
            key = str(raw_key or "").strip()
            if not key:
                continue
        normalized[key] = _normalized_workload_entry(raw_entry)
    return normalized


def _merge_workload_entries(entries):
    merged = {
        "active_assignments": 0,
        "overdue_assignments": 0,
        "due_soon_assignments": 0,
        "high_priority_assignments": 0,
        "titles": [],
    }
    seen_titles = set()
    for entry in entries or []:
        normalized = _normalized_workload_entry(entry)
        merged["active_assignments"] += int(normalized.get("active_assignments") or 0)
        merged["overdue_assignments"] += int(normalized.get("overdue_assignments") or 0)
        merged["due_soon_assignments"] += int(normalized.get("due_soon_assignments") or 0)
        merged["high_priority_assignments"] += int(normalized.get("high_priority_assignments") or 0)
        for title in normalized.get("titles") or []:
            normalized_title = _normalize_text(title)
            if not normalized_title or normalized_title in seen_titles:
                continue
            seen_titles.add(normalized_title)
            merged["titles"].append(title)
            if len(merged["titles"]) >= 5:
                break
    return merged


def _scope_workload_entry(assign_type, context, *, unit_domains=None, role_ids=None, user_ids=None):
    normalized_assign_type = str(assign_type or "").strip().lower()
    user_map = _context_workload_map(context, "user_workload_map")
    role_map = _context_workload_map(context, "role_workload_map")
    unit_map = _context_workload_map(context, "unit_workload_map")
    entries = []
    if normalized_assign_type == "user":
        for value in (user_ids or []):
            if str(value).isdigit() and int(value) in user_map:
                entries.append(user_map[int(value)])
    elif normalized_assign_type == "role":
        for value in (role_ids or []):
            if str(value).isdigit() and int(value) in role_map:
                entries.append(role_map[int(value)])
    elif normalized_assign_type == "unit":
        for value in (unit_domains or []):
            key = str(value or "").strip()
            if key and key in unit_map:
                entries.append(unit_map[key])
    if not entries:
        return _normalized_workload_entry({})
    return _merge_workload_entries(entries)


def _workload_penalty(entry):
    normalized = _normalized_workload_entry(entry)
    active = int(normalized.get("active_assignments") or 0)
    overdue = int(normalized.get("overdue_assignments") or 0)
    due_soon = int(normalized.get("due_soon_assignments") or 0)
    penalty = 0.0
    if active >= 8:
        penalty += 0.14
    elif active >= 5:
        penalty += 0.08
    elif active >= 3:
        penalty += 0.04
    if overdue >= 2:
        penalty += 0.12
    elif overdue >= 1:
        penalty += 0.06
    if due_soon >= 3:
        penalty += 0.04
    return min(round(penalty, 4), 0.28)


def _workload_fit_signals(entry):
    normalized = _normalized_workload_entry(entry)
    active = int(normalized.get("active_assignments") or 0)
    overdue = int(normalized.get("overdue_assignments") or 0)
    due_soon = int(normalized.get("due_soon_assignments") or 0)
    signals = []
    if overdue >= 2:
        signals.append(
            {
                "key": "workload_overdue_high",
                "label": "Đang có việc quá hạn",
                "tone": "danger",
                "detail": f"Hiện còn {overdue} việc quá hạn cần xử lý trước.",
            }
        )
    elif overdue == 1:
        signals.append(
            {
                "key": "workload_overdue_some",
                "label": "Có việc sắp tắc",
                "tone": "warning",
                "detail": "Đang còn ít nhất 1 việc quá hạn.",
            }
        )
    if active >= 8:
        signals.append(
            {
                "key": "workload_active_high",
                "label": "Tải công việc rất cao",
                "tone": "danger",
                "detail": f"Đang mở {active} việc cùng lúc.",
            }
        )
    elif active >= 5:
        signals.append(
            {
                "key": "workload_active_medium",
                "label": "Tải công việc cao",
                "tone": "warning",
                "detail": f"Đang mở {active} việc cùng lúc.",
            }
        )
    elif due_soon >= 3:
        signals.append(
            {
                "key": "workload_due_soon",
                "label": "Nhiều việc sắp đến hạn",
                "tone": "warning",
                "detail": f"Có {due_soon} việc sắp đến hạn.",
            }
        )
    return signals


def _workload_reason(entry):
    normalized = _normalized_workload_entry(entry)
    active = int(normalized.get("active_assignments") or 0)
    overdue = int(normalized.get("overdue_assignments") or 0)
    due_soon = int(normalized.get("due_soon_assignments") or 0)
    if active <= 0 and overdue <= 0 and due_soon <= 0:
        return ""
    parts = [f"{active} việc đang mở"]
    if overdue > 0:
        parts.append(f"{overdue} việc quá hạn")
    if due_soon > 0:
        parts.append(f"{due_soon} việc sắp đến hạn")
    return "Tải vận hành hiện tại: " + ", ".join(parts) + "."


def _apply_workload_to_assignment_candidate(candidate, context):
    enriched = copy.deepcopy(candidate or {})
    workload_entry = _scope_workload_entry(
        enriched.get("assign_type"),
        context,
        unit_domains=enriched.get("unit_domains") or [],
        role_ids=enriched.get("role_ids") or [],
        user_ids=enriched.get("user_ids") or [],
    )
    penalty = _workload_penalty(workload_entry)
    enriched["workload"] = workload_entry
    enriched["workload_penalty"] = penalty
    if penalty > 0:
        enriched["confidence_score"] = max(float(enriched.get("confidence_score") or 0.0) - penalty, 0.0)
        signals = list(enriched.get("fit_signals") or [])
        signals.extend(_workload_fit_signals(workload_entry))
        deduped_signals = []
        seen_signal_keys = set()
        for signal in signals:
            key = str((signal or {}).get("key") or "").strip()
            if key and key in seen_signal_keys:
                continue
            if key:
                seen_signal_keys.add(key)
            deduped_signals.append(signal)
        enriched["fit_signals"] = deduped_signals
        reason = _workload_reason(workload_entry)
        if reason:
            enriched.setdefault("reasons", []).append(reason)
        score_breakdown = dict(enriched.get("score_breakdown") or {})
        score_breakdown["workload_penalty"] = penalty
        score_breakdown["active_assignments"] = int(workload_entry.get("active_assignments") or 0)
        score_breakdown["overdue_assignments"] = int(workload_entry.get("overdue_assignments") or 0)
        score_breakdown["due_soon_assignments"] = int(workload_entry.get("due_soon_assignments") or 0)
        enriched["score_breakdown"] = score_breakdown
    enriched["confidence_label"] = _confidence_label(float(enriched.get("confidence_score") or 0.0))
    return enriched


def _assignment_signature(suggestion):
    assign_type = str(suggestion.get("assign_type") or "").strip().lower()
    if assign_type == "unit":
        return ("unit", tuple(sorted(str(value or "").strip() for value in (suggestion.get("unit_domains") or []) if str(value or "").strip())))
    if assign_type == "role":
        return ("role", tuple(sorted(int(value) for value in (suggestion.get("role_ids") or []) if str(value).isdigit())))
    if assign_type == "user":
        return ("user", tuple(sorted(int(value) for value in (suggestion.get("user_ids") or []) if str(value).isdigit())))
    return ("", ())


def _assignment_candidate(assign_type, *, unit_domains=None, role_ids=None, user_ids=None, score=0.0, reason="", source="", context=None, fit_signals=None, score_breakdown=None):
    suggestion = {
        "assign_type": str(assign_type or "").strip().lower(),
        "unit_domains": list(unit_domains or []),
        "role_ids": list(role_ids or []),
        "user_ids": list(user_ids or []),
        "confidence_score": max(float(score or 0.0), 0.0),
        "confidence_label": _confidence_label(float(score or 0.0)),
        "display_targets": [],
        "reasons": [str(reason).strip()] if str(reason or "").strip() else [],
        "source": str(source or "").strip(),
        "fit_signals": list(fit_signals or []),
        "score_breakdown": dict(score_breakdown or {}),
    }
    suggestion["display_targets"] = _build_assignment_display(suggestion, context or {})
    return suggestion


def _assignment_alternatives(text, context, history_candidates, user_candidates, role_candidates, unit_candidates, primary_signature):
    alternatives = []
    seen = {primary_signature}

    def push(candidate):
        adjusted_candidate = _apply_workload_to_assignment_candidate(candidate, context)
        signature = _assignment_signature(adjusted_candidate)
        if signature == ("", ()) or signature in seen:
            return
        seen.add(signature)
        alternatives.append(adjusted_candidate)

    for candidate in history_candidates or []:
        specialty_reason = _history_specialty_reason(candidate)
        push(
            _assignment_candidate(
                candidate.get("assign_type"),
                unit_domains=candidate.get("unit_domains") or [],
                role_ids=candidate.get("role_ids") or [],
                user_ids=candidate.get("user_ids") or [],
                score=min(float(candidate.get("raw_history_quality_score") or candidate.get("history_quality_score") or candidate.get("score") or 0.0), 1.0),
                reason=(
                    f"Tương tự công việc trước đây: {candidate.get('title')}. {_history_execution_reason(candidate)}"
                    + (f" {specialty_reason}" if specialty_reason else "")
                ),
                source="history",
                context=context,
                fit_signals=_history_fit_signals(candidate),
                score_breakdown={
                    "semantic_score": float(candidate.get("score") or 0.0),
                    "history_quality_score": float(candidate.get("history_quality_score") or 0.0),
                    "raw_history_quality_score": float(candidate.get("raw_history_quality_score") or 0.0),
                    "submitted_rate": float(candidate.get("submitted_rate") or 0.0),
                    "completed_rate": float(candidate.get("completed_rate") or 0.0),
                    "on_time_rate": float(candidate.get("on_time_rate") or 0.0),
                    "domain_match_bonus": float(candidate.get("domain_match_bonus") or 0.0),
                    "category_match_bonus": float(candidate.get("category_match_bonus") or 0.0),
                },
            )
        )

    for candidate in user_candidates or []:
        if float(candidate.get("score") or 0.0) < 0.2:
            continue
        push(
            _assignment_candidate(
                "user",
                user_ids=[int(candidate.get("id"))],
                score=float(candidate.get("score") or 0.0),
                reason=f"Khớp với cá nhân {candidate.get('label')}.",
                source="catalog_user",
                context=context,
                fit_signals=[signal for signal in [_semantic_fit_signal(float(candidate.get("score") or 0.0))] if signal],
                score_breakdown={
                    "semantic_score": float(candidate.get("score") or 0.0),
                },
            )
        )

    for candidate in role_candidates or []:
        if float(candidate.get("score") or 0.0) < 0.2:
            continue
        push(
            _assignment_candidate(
                "role",
                role_ids=[int(candidate.get("id"))],
                score=float(candidate.get("score") or 0.0),
                reason=f"Khớp với vai trò {candidate.get('label')}.",
                source="catalog_role",
                context=context,
                fit_signals=[signal for signal in [_semantic_fit_signal(float(candidate.get("score") or 0.0))] if signal],
                score_breakdown={
                    "semantic_score": float(candidate.get("score") or 0.0),
                },
            )
        )

    for candidate in unit_candidates or []:
        if float(candidate.get("score") or 0.0) < 0.18:
            continue
        push(
            _assignment_candidate(
                "unit",
                unit_domains=[candidate.get("value")],
                score=float(candidate.get("score") or 0.0),
                reason=f"Khớp với đơn vị {candidate.get('label')}.",
                source="catalog_unit",
                context=context,
                fit_signals=[signal for signal in [_semantic_fit_signal(float(candidate.get("score") or 0.0))] if signal],
                score_breakdown={
                    "semantic_score": float(candidate.get("score") or 0.0),
                },
            )
        )

    alternatives.sort(
        key=lambda item: (
            -float(item.get("confidence_score") or 0.0),
            str(item.get("assign_type") or ""),
            ",".join(item.get("display_targets") or []),
        )
    )
    return alternatives[:3]


def _suggest_assignment(text, context, current_domain="", fallback_domain="", current_category=""):
    unit_candidates = _pick_best_candidates(text, context.get("unit_catalog") or [], limit=3)
    role_candidates = _pick_best_candidates(text, context.get("role_catalog") or [], limit=3)
    user_candidates = _pick_best_candidates(text, context.get("user_catalog") or [], limit=3)
    history_candidates = _history_assignment_candidates(
        text,
        context.get("history_entries") or [],
        limit=3,
        current_domain=current_domain,
        current_category=current_category,
    )

    reasons = []
    workload_cautions = []
    suggestion = {
        "assign_type": "",
        "unit_domains": [],
        "role_ids": [],
        "user_ids": [],
        "confidence_score": 0.0,
        "confidence_label": "thấp",
        "display_targets": [],
        "reasons": reasons,
        "history_matches": history_candidates,
        "alternatives": [],
        "fit_signals": [],
        "score_breakdown": {},
        "workload_cautions": workload_cautions,
    }

    if history_candidates and float(history_candidates[0].get("score") or 0.0) >= 0.6:
        best = history_candidates[0]
        history_suggestion = _apply_workload_to_assignment_candidate(
            {
                "assign_type": best.get("assign_type") or "",
                "unit_domains": list(best.get("unit_domains") or []),
                "role_ids": list(best.get("role_ids") or []),
                "user_ids": list(best.get("user_ids") or []),
                "confidence_score": min(float(best.get("raw_history_quality_score") or best.get("history_quality_score") or best.get("score") or 0.0) + 0.08, 1.0),
                "fit_signals": _history_fit_signals(best),
                "score_breakdown": {
                    "semantic_score": float(best.get("score") or 0.0),
                    "history_quality_score": float(best.get("history_quality_score") or 0.0),
                    "raw_history_quality_score": float(best.get("raw_history_quality_score") or 0.0),
                    "submitted_rate": float(best.get("submitted_rate") or 0.0),
                    "completed_rate": float(best.get("completed_rate") or 0.0),
                    "on_time_rate": float(best.get("on_time_rate") or 0.0),
                    "domain_match_bonus": float(best.get("domain_match_bonus") or 0.0),
                    "category_match_bonus": float(best.get("category_match_bonus") or 0.0),
                },
                "reasons": [],
            },
            context,
        )
        suggestion.update(history_suggestion)
        specialty_reason = _history_specialty_reason(best)
        reasons.append(
            f"Tương tự công việc trước đây: {best.get('title')}. {_history_execution_reason(best)}"
            + (f" {specialty_reason}" if specialty_reason else "")
        )

    user_top = user_candidates[0] if user_candidates else None
    role_top = role_candidates[0] if role_candidates else None
    unit_top = unit_candidates[0] if unit_candidates else None
    normalized_text = _normalize_text(text)

    current_confidence = float(suggestion.get("confidence_score") or 0.0)

    if user_top:
        user_candidate = _apply_workload_to_assignment_candidate(
            {
                "assign_type": "user",
                "user_ids": [int(user_top["id"])],
                "unit_domains": [],
                "role_ids": [],
                "confidence_score": float(user_top["score"] or 0.0),
                "fit_signals": [signal for signal in [_semantic_fit_signal(float(user_top["score"] or 0.0))] if signal],
                "score_breakdown": {
                    "semantic_score": float(user_top["score"] or 0.0),
                },
                "reasons": [],
            },
            context,
        )
        user_candidate_score = float(user_candidate.get("confidence_score") or 0.0)
    else:
        user_candidate = None
        user_candidate_score = 0.0

    if user_top and (
        user_candidate_score >= 0.72
        or (
            float(user_top["score"]) >= 0.32
            and _normalize_text(user_top.get("label")) in normalized_text
        )
    ) and user_candidate_score >= current_confidence + 0.02:
        suggestion.update(
            {
                **user_candidate,
            }
        )
        reasons.append(f"Khớp trực tiếp với cá nhân {user_top['label']}.")
        current_confidence = float(suggestion.get("confidence_score") or 0.0)
    elif user_top and float(user_candidate.get("workload_penalty") or 0.0) >= 0.08:
        workload_cautions.append(
            f"Cá nhân {user_top['label']} đang có tải vận hành cao nên chưa nên ưu tiên giao trực tiếp."
        )

    if role_top:
        role_candidate = _apply_workload_to_assignment_candidate(
            {
                "assign_type": "role",
                "role_ids": [int(role_top["id"])],
                "unit_domains": [],
                "user_ids": [],
                "confidence_score": float(role_top["score"] or 0.0),
                "fit_signals": [signal for signal in [_semantic_fit_signal(float(role_top["score"] or 0.0))] if signal],
                "score_breakdown": {
                    "semantic_score": float(role_top["score"] or 0.0),
                },
                "reasons": [],
            },
            context,
        )
        role_candidate_score = float(role_candidate.get("confidence_score") or 0.0)
    else:
        role_candidate = None
        role_candidate_score = 0.0

    if role_top and role_candidate_score >= max(float(unit_top["score"]) + 0.12 if unit_top else 0.0, 0.55) and role_candidate_score >= current_confidence + 0.02:
        suggestion.update(
            {
                **role_candidate,
            }
        )
        reasons.append(f"Khớp tốt với vai trò {role_top['label']}.")
        current_confidence = float(suggestion.get("confidence_score") or 0.0)

    if unit_top:
        unit_candidate = _apply_workload_to_assignment_candidate(
            {
                "assign_type": "unit",
                "unit_domains": [unit_top["value"]],
                "role_ids": [],
                "user_ids": [],
                "confidence_score": float(unit_top["score"] or 0.0),
                "fit_signals": [signal for signal in [_semantic_fit_signal(float(unit_top["score"] or 0.0))] if signal],
                "score_breakdown": {
                    "semantic_score": float(unit_top["score"] or 0.0),
                },
                "reasons": [],
            },
            context,
        )
        unit_candidate_score = float(unit_candidate.get("confidence_score") or 0.0)
    else:
        unit_candidate = None
        unit_candidate_score = 0.0

    if unit_top and unit_candidate_score >= 0.28 and unit_candidate_score >= current_confidence + 0.02:
        suggestion.update(
            {
                **unit_candidate,
            }
        )
        reasons.append(f"Khớp gần nhất với đơn vị {unit_top['label']}.")
    elif unit_top and float(unit_candidate.get("workload_penalty") or 0.0) >= 0.08:
        workload_cautions.append(
            f"Đơn vị {unit_top['label']} đang có tải vận hành cao, quản trị nên cân nhắc phương án khác."
        )

    if not suggestion["assign_type"] and current_domain:
        suggestion.update(_apply_workload_to_assignment_candidate(
            {
                "assign_type": "unit",
                "unit_domains": [current_domain],
                "confidence_score": 0.32,
                "fit_signals": [
                    {
                        "key": "current_domain_default",
                        "label": "Theo đơn vị đang chọn",
                        "tone": "secondary",
                        "detail": "Dùng đơn vị nghiệp vụ của nháp làm mặc định.",
                    }
                ],
                "score_breakdown": {
                    "semantic_score": 0.0,
                },
                "reasons": [],
            },
            context,
        ))
        reasons.append("Dùng đơn vị nghiệp vụ đang chọn của nháp làm mặc định.")
    elif not suggestion["assign_type"] and fallback_domain:
        suggestion.update(_apply_workload_to_assignment_candidate(
            {
                "assign_type": "unit",
                "unit_domains": [fallback_domain],
                "confidence_score": 0.3,
                "fit_signals": [
                    {
                        "key": "fallback_domain_default",
                        "label": "Theo bối cảnh chung",
                        "tone": "secondary",
                        "detail": "Suy ra từ nội dung tổng thể của tài liệu.",
                    }
                ],
                "score_breakdown": {
                    "semantic_score": 0.0,
                },
                "reasons": [],
            },
            context,
        ))
        reasons.append("Suy ra từ nội dung tổng thể của tài liệu.")

    suggestion["reasons"] = reasons
    suggestion["workload_cautions"] = workload_cautions
    suggestion["confidence_label"] = _confidence_label(float(suggestion["confidence_score"] or 0.0))
    suggestion["display_targets"] = _build_assignment_display(suggestion, context)
    suggestion["alternatives"] = _assignment_alternatives(
        text,
        context,
        history_candidates,
        user_candidates,
        role_candidates,
        unit_candidates,
        _assignment_signature(suggestion),
    )
    return suggestion


def _outline_item_ai_suggestion(item, index, config, context, fallback_domain):
    title = str(item.get("title") or "").strip()
    guide_text = str(item.get("guide_text") or "").strip()
    combined_text = f"{title}. {guide_text}".strip()
    report_kind = "number" if _contains_any_marker(combined_text, _NUMERIC_MARKERS) else "narrative"
    attachment_required = bool(item.get("attachment_required")) or _contains_any_marker(combined_text, _ATTACHMENT_MARKERS)
    assignment = _suggest_assignment(
        combined_text,
        context,
        current_domain=str(config.get("domain") or "").strip(),
        fallback_domain=fallback_domain,
        current_category=str(config.get("category") or "").strip(),
    )
    return {
        "index": index,
        "title": title,
        "current": {
            "assign_type": item.get("assign_type") or "",
            "unit_domains": list(item.get("unit_domains") or []),
            "role_ids": list(item.get("role_ids") or []),
            "user_ids": list(item.get("user_ids") or []),
            "report_kind": item.get("report_kind") or "narrative",
            "attachment_required": bool(item.get("attachment_required")),
        },
        "suggestion": {
            **assignment,
            "report_kind": report_kind,
            "attachment_required": attachment_required,
        },
    }


def _report_field_ai_suggestion(field, index, config, context, fallback_domain):
    label = str(field.get("label") or "").strip()
    help_text = str(field.get("help_text") or "").strip()
    placeholder = str(field.get("placeholder") or "").strip()
    combined_text = ". ".join(value for value in [label, help_text, placeholder] if value).strip()
    assignment = _suggest_assignment(
        combined_text,
        context,
        current_domain=str(config.get("domain") or "").strip(),
        fallback_domain=fallback_domain,
        current_category=str(config.get("category") or "").strip(),
    )
    target_type = str(assignment.get("assign_type") or "").strip().lower() or "all"
    return {
        "index": index,
        "label": label,
        "current": {
            "target_type": str(field.get("target_type") or "all").strip().lower() or "all",
            "target_unit_domains": list(field.get("target_unit_domains") or []),
            "target_role_ids": list(field.get("target_role_ids") or []),
            "target_user_ids": list(field.get("target_user_ids") or []),
            "required": bool(field.get("required")),
            "type": str(field.get("type") or "text").strip().lower() or "text",
        },
        "suggestion": {
            **assignment,
            "target_type": target_type,
            "target_unit_domains": list(assignment.get("unit_domains") or []),
            "target_role_ids": list(assignment.get("role_ids") or []),
            "target_user_ids": list(assignment.get("user_ids") or []),
        },
    }


def _form_field_ai_suggestion(field, index, config, context, fallback_domain):
    label = str(field.get("field_label") or "").strip()
    field_type = str(field.get("field_type") or "text").strip().lower() or "text"
    option_text = str(field.get("field_options_text") or "").strip()
    combined_text = ". ".join(value for value in [label, field_type, option_text] if value).strip()
    assignment = _suggest_assignment(
        combined_text,
        context,
        current_domain=str(config.get("domain") or "").strip(),
        fallback_domain=fallback_domain,
        current_category=str(config.get("category") or "").strip(),
    )
    target_type = str(assignment.get("assign_type") or "").strip().lower() or "all"
    return {
        "index": index,
        "label": label,
        "current": {
            "target_type": str(field.get("target_type") or "all").strip().lower() or "all",
            "target_unit_domains": list(field.get("target_unit_domains") or []),
            "target_role_ids": list(field.get("target_role_ids") or []),
            "target_user_ids": list(field.get("target_user_ids") or []),
            "required": bool(field.get("is_required")),
            "type": field_type,
        },
        "suggestion": {
            **assignment,
            "target_type": target_type,
            "target_unit_domains": list(assignment.get("unit_domains") or []),
            "target_role_ids": list(assignment.get("role_ids") or []),
            "target_user_ids": list(assignment.get("user_ids") or []),
        },
    }


def _template_suggestions(config, context, max_items=3):
    if str(config.get("collection_mode") or "").strip().lower() not in {"file", "form"}:
        return []
    title = str(config.get("title") or "").strip()
    summary = str(config.get("summary") or "").strip()
    domain = str(config.get("domain") or "").strip()
    text = " ".join(value for value in [title, summary, domain] if value).strip()
    ranked = []
    for template in context.get("report_templates") or []:
        name = template.get("name") or ""
        professional_unit = template.get("professional_unit") or ""
        report_type_name = template.get("report_type_name") or ""
        score = max(
            _overlap_score(text, name),
            _overlap_score(text, professional_unit),
            _overlap_score(text, report_type_name),
        )
        if score <= 0.2:
            continue
        ranked.append(
            {
                "id": template.get("id"),
                "name": name,
                "professional_unit": professional_unit,
                "report_type_name": report_type_name,
                "confidence_score": round(score, 4),
                "confidence_label": _confidence_label(score),
                "reason": f"Trùng ngữ nghĩa với mẫu báo cáo {name}.",
            }
        )
    ranked.sort(key=lambda item: (-item["confidence_score"], item["name"]))
    return ranked[:max_items]


def _build_assignment_strategy(collection_mode, outline_items, global_assignment, report_field_items, form_field_items=None):
    if collection_mode == "outline":
        total_items = len(outline_items or [])
        assigned_items = sum(
            1
            for item in (outline_items or [])
            if str((item.get("current") or {}).get("assign_type") or "").strip()
            or str((item.get("suggestion") or {}).get("assign_type") or "").strip()
        )
        return {
            "mode": "per_item",
            "label": "Giao theo từng đầu mục",
            "summary": f"{assigned_items}/{total_items} đầu mục đã có hoặc có thể suy ra phương án giao việc." if total_items else "Chưa có đầu mục để phân tích giao việc.",
        }

    if collection_mode == "form":
        targeted_fields = sum(
            1
            for item in (form_field_items or [])
            if str((item.get("current") or {}).get("target_type") or "").strip().lower() in {"unit", "role", "user"}
            or str((item.get("suggestion") or {}).get("target_type") or "").strip().lower() in {"unit", "role", "user"}
        )
        total_fields = len(form_field_items or [])
        targets = (global_assignment or {}).get("display_targets") or []
        target_text = ", ".join(targets) if targets else "chưa suy ra người nhận"
        if total_fields:
            return {
                "mode": "task_level_with_field_scope",
                "label": "Giao toàn nhiệm vụ, chia field biểu mẫu theo phạm vi",
                "summary": f"Giao toàn task cho {target_text}; có {targeted_fields}/{total_fields} field đã có hoặc có thể suy ra phạm vi riêng.",
            }
        return {
            "mode": "task_level",
            "label": "Giao toàn nhiệm vụ, thu thập trên biểu mẫu",
            "summary": f"Ưu tiên giao toàn task cho {target_text}, sau đó chuẩn hóa dữ liệu ở cấp field.",
        }

    targeted_fields = sum(
        1
        for item in (report_field_items or [])
        if str((item.get("current") or {}).get("target_type") or "").strip().lower() in {"unit", "role", "user"}
        or str((item.get("suggestion") or {}).get("target_type") or "").strip().lower() in {"unit", "role", "user"}
    )
    total_fields = len(report_field_items or [])
    return {
        "mode": "task_level_with_field_scope",
        "label": "Giao toàn nhiệm vụ, chia nội dung báo cáo theo field",
        "summary": (
            f"Có {targeted_fields}/{total_fields} chỉ tiêu đang có hoặc có thể suy ra phạm vi theo đơn vị/vai trò/cá nhân."
            if total_fields
            else "Chưa có chỉ tiêu cấu trúc để phân tích phạm vi báo cáo."
        ),
    }


def _count_config_payload_items(config, collection_mode):
    if collection_mode == "outline":
        return len([item for item in (config.get("items") or []) if str(item.get("title") or "").strip()])
    if collection_mode == "form":
        return len([field for field in (config.get("form_fields") or []) if str(field.get("field_label") or "").strip()])
    count = len([field for field in (config.get("report_fields") or []) if str(field.get("label") or "").strip()])
    if bool(config.get("report_narrative_enabled", True)):
        count += 1
    if bool(config.get("report_attachment_enabled")):
        count += 1
    return count


def _build_specialist_brief(config, analysis):
    current_config = config or {}
    collection_mode = str(current_config.get("collection_mode") or "file").strip().lower()
    source_type = str(current_config.get("source_type") or "").strip().lower()
    item_count = _count_config_payload_items(current_config, collection_mode)
    assignment_strategy = analysis.get("assignment_strategy") or {}
    recipient_insights = analysis.get("recipient_insights") or {}
    blockers = analysis.get("blockers") or []
    warnings = analysis.get("warnings") or []
    opportunities = analysis.get("opportunities") or []

    if collection_mode == "outline":
        input_summary = f"Đã tách được {item_count} đầu mục giao việc từ nguồn tham chiếu."
        delivery_label = "Phát hành thành task OUTLINE"
        delivery_summary = "Hệ thống sẽ tạo đầu mục và assignment theo từng dòng để các đơn vị theo dõi, cập nhật và nộp kết quả ngay trong hệ thống."
    elif collection_mode == "form":
        input_summary = f"Đã chuẩn hóa được {item_count} field biểu mẫu để thu thập dữ liệu."
        delivery_label = "Phát hành thành task FORM"
        delivery_summary = "Hệ thống sẽ giao toàn nhiệm vụ cho đơn vị thực hiện, đồng thời chỉ hiển thị các field thuộc phạm vi từng đơn vị/vai trò khi đã cấu hình."
    else:
        input_summary = f"Đã chuẩn hóa được {item_count} thành phần báo cáo để phát hành theo mẫu nội bộ."
        delivery_label = "Phát hành thành task FILE"
        delivery_summary = "Hệ thống sẽ giao toàn nhiệm vụ, cho phép đơn vị nộp một bộ báo cáo có cấu trúc gồm thuyết minh, chỉ tiêu và minh chứng."

    monitoring_summary = (
        f"Cần rà ngay {len(blockers)} blocker trước khi phát hành."
        if blockers
        else (
            f"Có {len(warnings)} cảnh báo và {len(opportunities)} cơ hội tối ưu để quản trị cân nhắc."
            if warnings or opportunities
            else "Có thể phát hành sau khi quản trị rà lần cuối cấu hình giao việc."
        )
    )
    if recipient_insights.get("empty_payload_recipients"):
        monitoring_summary += f" Hiện có {len(recipient_insights.get('empty_payload_recipients') or [])} người nhận chưa thấy nội dung."
    elif recipient_insights.get("fragmented_units"):
        monitoring_summary += f" Hiện có {len(recipient_insights.get('fragmented_units') or [])} đơn vị bị chia qua nhiều nhóm nộp."
    elif recipient_insights.get("high_workload_recipients"):
        monitoring_summary += f" Hiện có {len(recipient_insights.get('high_workload_recipients') or [])} người nhận đang có tải vận hành cao."
    elif recipient_insights.get("overloaded_recipients"):
        monitoring_summary += f" Hiện có {len(recipient_insights.get('overloaded_recipients') or [])} người nhận đang quá tải đầu mục."
    elif recipient_insights.get("recipient_count"):
        monitoring_summary += (
            f" Quy mô phát hành hiện suy ra {recipient_insights.get('recipient_count', 0)} người nhận"
            f" / {recipient_insights.get('unit_count', 0)} đơn vị."
        )

    return {
        "input_channel_label": _SOURCE_TYPE_LABELS.get(source_type) or "Nguồn tham chiếu nội bộ",
        "input_summary": input_summary,
        "assignment_model_label": assignment_strategy.get("label") or "Chưa suy ra phương án giao việc",
        "assignment_summary": assignment_strategy.get("summary") or "Quản trị cần chốt lại người nhận trước khi phát hành.",
        "delivery_model_label": delivery_label,
        "delivery_summary": delivery_summary,
        "monitoring_label": "Điểm quản trị cần theo dõi",
        "monitoring_summary": monitoring_summary,
    }


def _build_workflow_stages(collection_mode, has_source_data, publish_ready, blockers, warnings, outline_items, global_assignment, report_field_items, form_field_items=None):
    if collection_mode == "outline":
        inferred_assignment = any(str((item.get("suggestion") or {}).get("assign_type") or "").strip() for item in (outline_items or []))
    else:
        inferred_assignment = bool(str((global_assignment or {}).get("assign_type") or "").strip())

    has_field_scope = any(
        str((item.get("current") or {}).get("target_type") or "").strip().lower() in {"unit", "role", "user"}
        or str((item.get("suggestion") or {}).get("target_type") or "").strip().lower() in {"unit", "role", "user"}
        for item in (report_field_items or [])
    ) or any(
        str((item.get("current") or {}).get("target_type") or "").strip().lower() in {"unit", "role", "user"}
        or str((item.get("suggestion") or {}).get("target_type") or "").strip().lower() in {"unit", "role", "user"}
        for item in (form_field_items or [])
    )

    return [
        {
            "key": "input",
            "label": "Phân tích dữ liệu đầu vào",
            "status": "done" if has_source_data else "todo",
            "detail": "Đã đọc được cấu trúc nháp và chuẩn hóa về workflow blueprint." if has_source_data else "Chưa có dữ liệu đầu vào hợp lệ để AI phân tích.",
        },
        {
            "key": "proposal",
            "label": "Đề xuất phương án giao việc",
            "status": "done" if inferred_assignment else ("warning" if has_source_data else "todo"),
            "detail": "AI đã suy ra được phương án giao việc phù hợp với nội dung." if inferred_assignment else "Chưa suy ra rõ người nhận, quản trị nên rà lại tiêu đề và đầu mục.",
        },
        {
            "key": "configure",
            "label": "Cấu hình giao việc",
            "status": "warning" if blockers or warnings else "done",
            "detail": (
                f"Còn {len(blockers)} blocker và {len(warnings)} cảnh báo cần xử lý trước khi chốt."
                if blockers or warnings
                else (
                    "Đã đủ cấu hình để quản trị duyệt và phát hành."
                    if collection_mode != "file" or not report_field_items or has_field_scope
                    else "Đã đủ cấu hình cơ bản, có thể bổ sung phạm vi field theo đơn vị để tách báo cáo sâu hơn."
                )
            ),
        },
        {
            "key": "publish",
            "label": "Hoàn thiện và phát hành",
            "status": "done" if publish_ready else "todo",
            "detail": "Có thể phát hành thành nhiệm vụ nội bộ cho các đơn vị." if publish_ready else "Chưa nên phát hành cho đến khi xử lý xong các blocker.",
        },
    ]


def _build_recommended_actions(collection_mode, blockers, warnings, report_field_items, form_field_items=None):
    actions = list(blockers[:3])
    if collection_mode == "form":
        unscoped_fields = [
            item.get("label")
            for item in (form_field_items or [])
            if str((item.get("current") or {}).get("target_type") or "all").strip().lower() == "all"
            and str((item.get("suggestion") or {}).get("target_type") or "all").strip().lower() in {"unit", "role", "user"}
        ]
        if unscoped_fields:
            actions.append(f"Rà lại phạm vi giao cho các field biểu mẫu: {', '.join(unscoped_fields[:3])}.")
    if collection_mode == "file":
        unscoped_fields = [
            item.get("label")
            for item in (report_field_items or [])
            if str((item.get("current") or {}).get("target_type") or "all").strip().lower() == "all"
            and str((item.get("suggestion") or {}).get("target_type") or "all").strip().lower() in {"unit", "role", "user"}
        ]
        if unscoped_fields:
            actions.append(f"Rà lại phạm vi giao cho các chỉ tiêu: {', '.join(unscoped_fields[:3])}.")
    if warnings and len(actions) < 4:
        actions.extend(warnings[: max(0, 4 - len(actions))])
    return actions[:4]


def _context_recipient_catalog(context):
    recipients = []
    seen = set()
    for raw_item in context.get("recipient_catalog") or []:
        if not isinstance(raw_item, dict):
            continue
        recipient_id = raw_item.get("id")
        if recipient_id is None:
            continue
        try:
            recipient_id = int(recipient_id)
        except Exception:
            continue
        if recipient_id in seen:
            continue
        seen.add(recipient_id)
        recipients.append(
            {
                "id": recipient_id,
                "label": str(raw_item.get("label") or raw_item.get("fullname") or raw_item.get("username") or f"UID {recipient_id}").strip(),
                "username": str(raw_item.get("username") or "").strip(),
                "role_id": int(raw_item.get("role_id")) if str(raw_item.get("role_id") or "").isdigit() else None,
                "role_name": str(raw_item.get("role_name") or "").strip(),
                "unit_domain": str(raw_item.get("unit_domain") or "").strip(),
                "unit_name": str(raw_item.get("unit_name") or "").strip(),
                "unit_key": str(raw_item.get("unit_key") or "").strip(),
            }
        )
    if recipients:
        return recipients

    for raw_item in context.get("user_catalog") or []:
        if not isinstance(raw_item, dict):
            continue
        recipient_id = raw_item.get("id")
        if recipient_id is None:
            continue
        try:
            recipient_id = int(recipient_id)
        except Exception:
            continue
        if recipient_id in seen:
            continue
        seen.add(recipient_id)
        recipients.append(
            {
                "id": recipient_id,
                "label": str(raw_item.get("label") or f"UID {recipient_id}").strip(),
                "username": "",
                "role_id": None,
                "role_name": "",
                "unit_domain": "",
                "unit_name": "",
                "unit_key": "",
            }
        )
    return recipients


def _recipient_matches_unit(recipient, target_unit_domains):
    normalized_targets = {
        _normalize_text(value)
        for value in (target_unit_domains or [])
        if str(value or "").strip()
    }
    if not normalized_targets:
        return False
    recipient_candidates = {
        _normalize_text(recipient.get("unit_domain") or ""),
        _normalize_text(recipient.get("unit_name") or ""),
        _normalize_text(recipient.get("unit_key") or ""),
    }
    recipient_candidates.discard("")
    return bool(recipient_candidates & normalized_targets)


def _resolve_recipients_for_scope(assign_type, context, unit_domains=None, role_ids=None, user_ids=None, fallback_domain=""):
    recipients = _context_recipient_catalog(context)
    normalized_assign_type = str(assign_type or "").strip().lower()
    if normalized_assign_type == "user":
        selected_ids = {int(value) for value in (user_ids or []) if str(value).isdigit()}
        return [recipient for recipient in recipients if recipient["id"] in selected_ids]
    if normalized_assign_type == "role":
        selected_role_ids = {int(value) for value in (role_ids or []) if str(value).isdigit()}
        return [recipient for recipient in recipients if recipient.get("role_id") in selected_role_ids]
    if normalized_assign_type == "unit":
        normalized_domains = [str(value or "").strip() for value in (unit_domains or []) if str(value or "").strip()]
        if not normalized_domains and str(fallback_domain or "").strip():
            normalized_domains = [str(fallback_domain).strip()]
        return [recipient for recipient in recipients if _recipient_matches_unit(recipient, normalized_domains)]
    return []


def _recipient_visible_for_target(recipient, target_type, unit_domains=None, role_ids=None, user_ids=None):
    normalized_target_type = str(target_type or "all").strip().lower() or "all"
    if normalized_target_type == "unit":
        return _recipient_matches_unit(recipient, unit_domains or [])
    if normalized_target_type == "role":
        role_id = recipient.get("role_id")
        return bool(role_id and role_id in {int(value) for value in (role_ids or []) if str(value).isdigit()})
    if normalized_target_type == "user":
        return recipient.get("id") in {int(value) for value in (user_ids or []) if str(value).isdigit()}
    return True


def _recipient_row(recipient):
    workload = _normalized_workload_entry(recipient.get("workload"))
    return {
        "user_id": recipient.get("id"),
        "user_name": recipient.get("label") or f"UID {recipient.get('id')}",
        "unit_name": recipient.get("unit_name") or "Chưa có đơn vị",
        "role_name": recipient.get("role_name") or "",
        "payload_count": 0,
        "payload_labels": [],
        "active_assignments": int(workload.get("active_assignments") or 0),
        "overdue_assignments": int(workload.get("overdue_assignments") or 0),
        "due_soon_assignments": int(workload.get("due_soon_assignments") or 0),
    }


def _recipient_submission_group_info(assign_type, recipient):
    normalized_assign_type = str(assign_type or "").strip().lower()
    recipient_id = int(recipient.get("id") or 0)
    user_name = str(recipient.get("label") or recipient.get("username") or f"UID {recipient_id}").strip()
    unit_name = str(recipient.get("unit_name") or "Chưa có đơn vị").strip() or "Chưa có đơn vị"
    unit_key = str(recipient.get("unit_key") or "").strip()
    if not unit_key:
        unit_key = _normalize_text(recipient.get("unit_domain") or unit_name) or f"user:{recipient_id}"
    role_id = int(recipient.get("role_id") or 0)
    role_name = str(recipient.get("role_name") or "").strip() or "Chưa phân vai trò"

    if normalized_assign_type == "unit":
        return {
            "mode": "unit",
            "mode_label": "Nộp theo đơn vị",
            "group_key": f"unit:{unit_key}",
            "group_label": f"Đơn vị {unit_name}",
            "unit_name": unit_name,
            "member_label": user_name,
        }
    if normalized_assign_type == "role":
        return {
            "mode": "role",
            "mode_label": "Nộp theo vai trò",
            "group_key": f"role:{role_id}:unit:{unit_key}",
            "group_label": f"{role_name} - {unit_name}",
            "unit_name": unit_name,
            "member_label": user_name,
        }
    return {
        "mode": "user",
        "mode_label": "Nộp cá nhân",
        "group_key": f"user:{recipient_id}",
        "group_label": user_name,
        "unit_name": unit_name,
        "member_label": user_name,
    }


def _recipient_unit_summaries(rows):
    unit_map = {}
    for row in rows or []:
        unit_name = str(row.get("unit_name") or "Chưa có đơn vị").strip()
        summary = unit_map.setdefault(
            unit_name,
            {"unit_name": unit_name, "recipient_count": 0, "payload_count": 0, "active_assignments": 0, "overdue_assignments": 0},
        )
        summary["recipient_count"] += 1
        summary["payload_count"] += int(row.get("payload_count") or 0)
        summary["active_assignments"] += int(row.get("active_assignments") or 0)
        summary["overdue_assignments"] += int(row.get("overdue_assignments") or 0)
    return sorted(unit_map.values(), key=lambda item: (-item["payload_count"], _normalize_text(item["unit_name"])))


def _finalize_submission_groups(group_map):
    groups = []
    for group in (group_map or {}).values():
        member_names = sorted(group.get("_member_names") or [], key=_normalize_text)
        payload_labels = sorted(group.get("_payload_labels") or [], key=_normalize_text)
        groups.append(
            {
                "group_key": group.get("group_key") or "",
                "group_label": group.get("group_label") or "",
                "mode": group.get("mode") or "user",
                "mode_label": group.get("mode_label") or "Nộp cá nhân",
                "unit_name": group.get("unit_name") or "Chưa có đơn vị",
                "member_names": member_names[:8],
                "payload_labels": payload_labels[:12],
                "recipient_count": len(member_names),
                "payload_count": len(payload_labels),
            }
        )
    return sorted(
        groups,
        key=lambda item: (-int(item.get("recipient_count") or 0), -int(item.get("payload_count") or 0), _normalize_text(item.get("group_label") or "")),
    )


def _build_unit_delivery_matrix(rows, submission_groups):
    row_map = {}
    for row in rows or []:
        unit_name = str(row.get("unit_name") or "Chưa có đơn vị").strip() or "Chưa có đơn vị"
        summary = row_map.setdefault(
            unit_name,
            {
                "unit_name": unit_name,
                "recipient_names": set(),
                "active_assignments": 0,
                "overdue_assignments": 0,
            },
        )
        user_name = str(row.get("user_name") or "").strip()
        if user_name:
            summary["recipient_names"].add(user_name)
        summary["active_assignments"] += int(row.get("active_assignments") or 0)
        summary["overdue_assignments"] += int(row.get("overdue_assignments") or 0)

    unit_map = {}
    for group in submission_groups or []:
        unit_name = str(group.get("unit_name") or "Chưa có đơn vị").strip() or "Chưa có đơn vị"
        summary = unit_map.setdefault(
            unit_name,
            {
                "unit_name": unit_name,
                "submission_modes": set(),
                "group_labels": set(),
                "payload_labels": set(),
                "member_names": set(),
            },
        )
        summary["submission_modes"].add(str(group.get("mode_label") or "Nộp cá nhân").strip())
        summary["group_labels"].add(str(group.get("group_label") or "").strip())
        for payload_label in (group.get("payload_labels") or []):
            if str(payload_label or "").strip():
                summary["payload_labels"].add(str(payload_label).strip())
        for member_name in (group.get("member_names") or []):
            if str(member_name or "").strip():
                summary["member_names"].add(str(member_name).strip())

    matrix = []
    for unit_name in sorted(set(row_map) | set(unit_map), key=_normalize_text):
        row_entry = row_map.get(unit_name, {})
        group_entry = unit_map.get(unit_name, {})
        recipient_names = sorted(
            (group_entry.get("member_names") or set()) | (row_entry.get("recipient_names") or set()),
            key=_normalize_text,
        )
        group_labels = sorted(group_entry.get("group_labels") or [], key=_normalize_text)
        payload_labels = sorted(group_entry.get("payload_labels") or [], key=_normalize_text)
        submission_modes = sorted(group_entry.get("submission_modes") or [], key=_normalize_text)
        matrix.append(
            {
                "unit_name": unit_name,
                "recipient_count": len(recipient_names),
                "submission_group_count": len(group_labels),
                "payload_count": len(payload_labels),
                "recipient_names": recipient_names[:8],
                "submission_modes": submission_modes[:4],
                "group_labels": group_labels[:8],
                "payload_labels": payload_labels[:12],
                "active_assignments": int(row_entry.get("active_assignments") or 0),
                "overdue_assignments": int(row_entry.get("overdue_assignments") or 0),
            }
        )
    return sorted(
        matrix,
        key=lambda item: (-int(item.get("submission_group_count") or 0), -int(item.get("payload_count") or 0), _normalize_text(item.get("unit_name") or "")),
    )


def _coordination_hotspots(collection_mode, submission_groups, unit_delivery_matrix):
    normalized_mode = str(collection_mode or "").strip().lower()
    hotspots = []
    fragmented_units = []
    if normalized_mode in {"form", "file"}:
        fragmented_units = [
            {
                "unit_name": item.get("unit_name"),
                "submission_group_count": int(item.get("submission_group_count") or 0),
                "payload_count": int(item.get("payload_count") or 0),
                "recipient_count": int(item.get("recipient_count") or 0),
            }
            for item in (unit_delivery_matrix or [])
            if int(item.get("submission_group_count") or 0) > 1 and int(item.get("payload_count") or 0) > 0
        ]
    single_owner_groups = [
        {
            "group_label": item.get("group_label"),
            "mode_label": item.get("mode_label"),
            "payload_count": int(item.get("payload_count") or 0),
            "recipient_count": int(item.get("recipient_count") or 0),
        }
        for item in (submission_groups or [])
        if int(item.get("recipient_count") or 0) == 1 and int(item.get("payload_count") or 0) >= 4
    ]
    large_submission_groups = [
        {
            "group_label": item.get("group_label"),
            "mode_label": item.get("mode_label"),
            "payload_count": int(item.get("payload_count") or 0),
            "recipient_count": int(item.get("recipient_count") or 0),
        }
        for item in (submission_groups or [])
        if int(item.get("recipient_count") or 0) >= 4 or int(item.get("payload_count") or 0) >= 8
    ]

    for item in fragmented_units[:3]:
        hotspots.append(
            {
                "scope": item.get("unit_name") or "Đơn vị",
                "tone": "warning",
                "detail": (
                    f"Đơn vị này sẽ phải phối hợp qua {item.get('submission_group_count', 0)} nhóm nộp"
                    f" cho {item.get('payload_count', 0)} nội dung."
                ),
            }
        )
    for item in single_owner_groups[:3]:
        hotspots.append(
            {
                "scope": item.get("group_label") or "Nhóm nộp",
                "tone": "warning",
                "detail": f"Nhóm nộp này chỉ có 1 người nhưng đang gánh {item.get('payload_count', 0)} nội dung.",
            }
        )
    for item in large_submission_groups[:3]:
        hotspots.append(
            {
                "scope": item.get("group_label") or "Nhóm nộp",
                "tone": "warning",
                "detail": (
                    f"Nhóm nộp này có quy mô phối hợp lớn: {item.get('recipient_count', 0)} người"
                    f" / {item.get('payload_count', 0)} nội dung."
                ),
            }
        )
    return {
        "coordination_hotspots": hotspots[:5],
        "fragmented_units": fragmented_units,
        "single_owner_groups": single_owner_groups,
        "large_submission_groups": large_submission_groups,
    }


def _recipient_overload_rows(rows):
    active_rows = [row for row in (rows or []) if int(row.get("payload_count") or 0) > 0]
    if len(active_rows) < 2:
        return []
    total_payload = sum(int(row.get("payload_count") or 0) for row in active_rows)
    average_payload = total_payload / len(active_rows) if active_rows else 0.0
    threshold = max(4.0, average_payload + 1.5)
    overloaded = [
        row
        for row in active_rows
        if float(row.get("payload_count") or 0) >= threshold
        and float(row.get("payload_count") or 0) >= average_payload * 1.4
    ]
    return sorted(overloaded, key=lambda item: (-item["payload_count"], _normalize_text(item["user_name"])))


def _build_recipient_insights(config, context):
    current_config = config or {}
    collection_mode = str(current_config.get("collection_mode") or "file").strip().lower()
    fallback_domain = str(current_config.get("domain") or "").strip()
    recipient_rows = {}
    submission_group_map = {}

    def ensure_row(recipient):
        recipient_id = recipient.get("id")
        if recipient_id not in recipient_rows:
            workload = _scope_workload_entry("user", context, user_ids=[recipient_id])
            recipient_rows[recipient_id] = _recipient_row({**recipient, "workload": workload})
        return recipient_rows[recipient_id]

    def register_submission_payload(recipient, assign_type, payload_label):
        label = str(payload_label or "").strip()
        if not label:
            return
        info = _recipient_submission_group_info(assign_type, recipient)
        group = submission_group_map.setdefault(
            info["group_key"],
            {
                "group_key": info["group_key"],
                "group_label": info["group_label"],
                "mode": info["mode"],
                "mode_label": info["mode_label"],
                "unit_name": info["unit_name"],
                "_member_names": set(),
                "_payload_labels": set(),
            },
        )
        member_label = str(info.get("member_label") or "").strip()
        if member_label:
            group["_member_names"].add(member_label)
        group["_payload_labels"].add(label)

    if collection_mode == "outline":
        for item in (current_config.get("items") or []):
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            recipients = _resolve_recipients_for_scope(
                item.get("assign_type"),
                context,
                unit_domains=item.get("unit_domains") or [],
                role_ids=item.get("role_ids") or [],
                user_ids=item.get("user_ids") or [],
                fallback_domain=fallback_domain,
            )
            for recipient in recipients:
                row = ensure_row(recipient)
                row["payload_count"] += 1
                row["payload_labels"].append(title)
                register_submission_payload(recipient, item.get("assign_type"), title)
    elif collection_mode == "form":
        fields = [field for field in (current_config.get("form_fields") or []) if str(field.get("field_label") or "").strip()]
        task_assign_type = current_config.get("assign_type")
        recipients = _resolve_recipients_for_scope(
            task_assign_type,
            context,
            unit_domains=current_config.get("unit_domains") or [],
            role_ids=current_config.get("role_ids") or [],
            user_ids=current_config.get("user_ids") or [],
            fallback_domain=fallback_domain,
        )
        for recipient in recipients:
            row = ensure_row(recipient)
            for field in fields:
                if not _recipient_visible_for_target(
                    recipient,
                    field.get("target_type") or "all",
                    unit_domains=field.get("target_unit_domains") or [],
                    role_ids=field.get("target_role_ids") or [],
                    user_ids=field.get("target_user_ids") or [],
                ):
                    continue
                row["payload_count"] += 1
                label = str(field.get("field_label") or "").strip()
                row["payload_labels"].append(label)
                register_submission_payload(recipient, task_assign_type, label)
    else:
        task_assign_type = current_config.get("assign_type")
        recipients = _resolve_recipients_for_scope(
            task_assign_type,
            context,
            unit_domains=current_config.get("unit_domains") or [],
            role_ids=current_config.get("role_ids") or [],
            user_ids=current_config.get("user_ids") or [],
            fallback_domain=fallback_domain,
        )
        for recipient in recipients:
            row = ensure_row(recipient)
            if bool(current_config.get("report_narrative_enabled", True)) and _recipient_visible_for_target(
                recipient,
                current_config.get("report_narrative_target_type") or "all",
                unit_domains=current_config.get("report_narrative_unit_domains") or [],
                role_ids=current_config.get("report_narrative_role_ids") or [],
                user_ids=current_config.get("report_narrative_user_ids") or [],
            ):
                row["payload_count"] += 1
                label = str(current_config.get("report_narrative_label") or "Báo cáo lời tổng hợp").strip()
                row["payload_labels"].append(label)
                register_submission_payload(recipient, task_assign_type, label)
            if bool(current_config.get("report_attachment_enabled")) and _recipient_visible_for_target(
                recipient,
                current_config.get("report_attachment_target_type") or "all",
                unit_domains=current_config.get("report_attachment_unit_domains") or [],
                role_ids=current_config.get("report_attachment_role_ids") or [],
                user_ids=current_config.get("report_attachment_user_ids") or [],
            ):
                row["payload_count"] += 1
                label = str(current_config.get("report_attachment_label") or "Tệp minh chứng").strip()
                row["payload_labels"].append(label)
                register_submission_payload(recipient, task_assign_type, label)
            for field in (current_config.get("report_fields") or []):
                label = str(field.get("label") or "").strip()
                if not label:
                    continue
                if not _recipient_visible_for_target(
                    recipient,
                    field.get("target_type") or "all",
                    unit_domains=field.get("target_unit_domains") or [],
                    role_ids=field.get("target_role_ids") or [],
                    user_ids=field.get("target_user_ids") or [],
                ):
                    continue
                row["payload_count"] += 1
                row["payload_labels"].append(label)
                register_submission_payload(recipient, task_assign_type, label)

    rows = sorted(
        recipient_rows.values(),
        key=lambda item: (-int(item["payload_count"] or 0), _normalize_text(item["unit_name"]), _normalize_text(item["user_name"])),
    )
    submission_groups = _finalize_submission_groups(submission_group_map)
    unit_delivery_matrix = _build_unit_delivery_matrix(rows, submission_groups)
    coordination_audit = _coordination_hotspots(collection_mode, submission_groups, unit_delivery_matrix)
    empty_payload_rows = [row for row in rows if int(row.get("payload_count") or 0) == 0]
    high_workload_rows = [
        row for row in rows
        if _workload_penalty(
            {
                "active_assignments": row.get("active_assignments"),
                "overdue_assignments": row.get("overdue_assignments"),
                "due_soon_assignments": row.get("due_soon_assignments"),
            }
        ) >= 0.08
    ]
    overloaded_rows = _recipient_overload_rows(rows) if collection_mode == "outline" else []
    return {
        "recipient_count": len(rows),
        "unit_count": len({str(row.get("unit_name") or "").strip() for row in rows if str(row.get("unit_name") or "").strip()}),
        "payload_total": sum(int(row.get("payload_count") or 0) for row in rows),
        "rows": rows,
        "empty_payload_recipients": [
            {
                "user_id": row.get("user_id"),
                "user_name": row.get("user_name"),
                "unit_name": row.get("unit_name"),
            }
            for row in empty_payload_rows
        ],
        "overloaded_recipients": [
            {
                "user_id": row.get("user_id"),
                "user_name": row.get("user_name"),
                "unit_name": row.get("unit_name"),
                "payload_count": row.get("payload_count"),
            }
            for row in overloaded_rows
        ],
        "high_workload_recipients": [
            {
                "user_id": row.get("user_id"),
                "user_name": row.get("user_name"),
                "unit_name": row.get("unit_name"),
                "active_assignments": row.get("active_assignments"),
                "overdue_assignments": row.get("overdue_assignments"),
            }
            for row in high_workload_rows
        ],
        "unit_summaries": _recipient_unit_summaries(rows),
        "submission_groups": submission_groups,
        "unit_delivery_matrix": unit_delivery_matrix,
        "coordination_hotspots": coordination_audit.get("coordination_hotspots") or [],
        "fragmented_units": coordination_audit.get("fragmented_units") or [],
        "single_owner_groups": coordination_audit.get("single_owner_groups") or [],
        "large_submission_groups": coordination_audit.get("large_submission_groups") or [],
    }


def analyze_task_import_config(config, context, llm_commentary="", llm_meta=None):
    current_config = copy.deepcopy(config or {})
    collection_mode = str(current_config.get("collection_mode") or "file").strip().lower()
    title_text = _suggest_title(current_config)
    summary_text = _suggest_summary(current_config)
    content_text = " ".join(
        value for value in [
            title_text,
            summary_text,
            current_config.get("source_name"),
            current_config.get("source_ref"),
        ] if str(value or "").strip()
    )

    blockers = []
    warnings = []
    opportunities = []

    if not str(current_config.get("title") or "").strip():
        warnings.append("Nháp chưa có tiêu đề rõ ràng cho nhiệm vụ phát hành.")
    if not str(current_config.get("summary") or "").strip():
        opportunities.append("Có thể bổ sung tóm tắt chuẩn hóa để đơn vị nhận việc hiểu nhanh mục tiêu.")

    suggested_domain, suggested_domain_label, domain_score = _suggest_catalog_value(content_text, context.get("unit_catalog") or [])
    suggested_category, suggested_category_label, category_score = _suggest_catalog_value(content_text, context.get("field_catalog") or [])
    suggested_priority = _infer_priority(content_text)

    analysis = {
        "version": 2,
        "engine": AI_ENGINE_NAME,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "hybrid" if llm_commentary else "rules+history",
        "collection_mode": collection_mode,
        "publish_ready": True,
        "score": 100,
        "summary": "",
        "blockers": blockers,
        "warnings": warnings,
        "opportunities": opportunities,
        "recommended_updates": {
            "title": title_text,
            "summary": summary_text,
            "domain": suggested_domain,
            "domain_label": suggested_domain_label,
            "domain_score": round(domain_score, 4),
            "category": suggested_category,
            "category_label": suggested_category_label,
            "category_score": round(category_score, 4),
            "priority": suggested_priority,
            "task_type": str(current_config.get("task_type") or "Công việc thường xuyên").strip() or "Công việc thường xuyên",
        },
        "global_assignment": None,
        "outline_items": [],
        "form_fields": [],
        "report_fields": [],
        "assignment_strategy": {},
        "workflow_stages": [],
        "recommended_actions": [],
        "template_suggestions": _template_suggestions(current_config, context),
        "recipient_insights": {},
        "specialist_brief": {},
        "llm_commentary": str(llm_commentary or "").strip(),
        "llm_meta": llm_meta or {},
    }

    fallback_domain = suggested_domain or str(current_config.get("domain") or "").strip()

    if collection_mode == "outline":
        items = [item for item in (current_config.get("items") or []) if str(item.get("title") or "").strip()]
        if not items:
            blockers.append("Nháp outline chưa có đầu mục hợp lệ.")
        for index, item in enumerate(items):
            item_analysis = _outline_item_ai_suggestion(item, index, current_config, context, fallback_domain)
            current_assignment = item_analysis["current"]
            if not _assignment_has_targets(
                current_assignment.get("assign_type"),
                unit_domains=current_assignment.get("unit_domains"),
                role_ids=current_assignment.get("role_ids"),
                user_ids=current_assignment.get("user_ids"),
                fallback_domain=str(current_config.get("domain") or "").strip(),
                ):
                blockers.append(f'Đầu mục "{item_analysis["title"]}" chưa được gán người thực hiện.')
            for caution in (item_analysis.get("suggestion") or {}).get("workload_cautions") or []:
                warnings.append(f'Đầu mục "{item_analysis["title"]}": {caution}')
            analysis["outline_items"].append(item_analysis)

        if len({(_normalize_text(item.get("title")), item.get("title")) for item in items}) != len(items):
            warnings.append("Có đầu mục trùng hoặc gần trùng nhau, nên rà soát để tránh giao việc lặp.")

        if any(
            item_analysis["suggestion"].get("report_kind") == "number"
            and item_analysis["current"].get("report_kind") != "number"
            for item_analysis in analysis["outline_items"]
        ):
            opportunities.append("Một số đầu mục có dấu hiệu phù hợp kiểu báo cáo số, có thể chuẩn hóa để tổng hợp nhanh hơn.")
    elif collection_mode == "form":
        fields = [field for field in (current_config.get("form_fields") or []) if str(field.get("field_label") or "").strip()]
        if not fields:
            blockers.append("Nháp biểu mẫu chưa có trường dữ liệu hợp lệ.")
        global_assignment = _suggest_assignment(
            content_text,
            context,
            current_domain=str(current_config.get("domain") or "").strip(),
            fallback_domain=fallback_domain,
            current_category=str(current_config.get("category") or "").strip(),
        )
        analysis["global_assignment"] = global_assignment
        for caution in (global_assignment or {}).get("workload_cautions") or []:
            warnings.append(caution)
        if not _assignment_has_targets(
            current_config.get("assign_type"),
            unit_domains=current_config.get("unit_domains"),
            role_ids=current_config.get("role_ids"),
            user_ids=current_config.get("user_ids"),
            fallback_domain=str(current_config.get("domain") or "").strip(),
        ):
            blockers.append("Nháp biểu mẫu chưa cấu hình phân công toàn nhiệm vụ.")
        if len(fields) == 1:
            warnings.append("Biểu mẫu hiện chỉ có 1 trường, có thể thiếu dữ liệu tổng hợp cần thu.")
        for index, field in enumerate(fields):
            field_analysis = _form_field_ai_suggestion(field, index, current_config, context, fallback_domain)
            for caution in (field_analysis.get("suggestion") or {}).get("workload_cautions") or []:
                warnings.append(f'Field "{field_analysis["label"]}": {caution}')
            analysis["form_fields"].append(field_analysis)
        if any(
            str((item.get("current") or {}).get("target_type") or "all").strip().lower() == "all"
            and str((item.get("suggestion") or {}).get("target_type") or "all").strip().lower() in {"unit", "role", "user"}
            and float((item.get("suggestion") or {}).get("confidence_score") or 0.0) >= 0.45
            for item in analysis["form_fields"]
        ):
            opportunities.append("Một số field biểu mẫu có thể chia phạm vi theo đơn vị/vai trò để mỗi nơi chỉ nhập phần của mình.")
    else:
        report_fields = [field for field in (current_config.get("report_fields") or []) if str(field.get("label") or "").strip()]
        global_assignment = _suggest_assignment(
            content_text,
            context,
            current_domain=str(current_config.get("domain") or "").strip(),
            fallback_domain=fallback_domain,
            current_category=str(current_config.get("category") or "").strip(),
        )
        analysis["global_assignment"] = global_assignment
        for caution in (global_assignment or {}).get("workload_cautions") or []:
            warnings.append(caution)
        if not _assignment_has_targets(
            current_config.get("assign_type"),
            unit_domains=current_config.get("unit_domains"),
            role_ids=current_config.get("role_ids"),
            user_ids=current_config.get("user_ids"),
            fallback_domain=str(current_config.get("domain") or "").strip(),
        ):
            blockers.append("Nháp báo cáo file chưa cấu hình phân công toàn nhiệm vụ.")
        if not report_fields and not bool(current_config.get("report_narrative_enabled")):
            blockers.append("Nháp file chưa có schema báo cáo hợp lệ.")
        if not report_fields:
            warnings.append("Nhiệm vụ file mới có phần thuyết minh/phụ lục, chưa có chỉ tiêu cấu trúc.")
        for index, field in enumerate(report_fields):
            field_analysis = _report_field_ai_suggestion(field, index, current_config, context, fallback_domain)
            for caution in (field_analysis.get("suggestion") or {}).get("workload_cautions") or []:
                warnings.append(f'Chỉ tiêu "{field_analysis["label"]}": {caution}')
            analysis["report_fields"].append(field_analysis)
        if any(
            str((item.get("current") or {}).get("target_type") or "all").strip().lower() == "all"
            and str((item.get("suggestion") or {}).get("target_type") or "all").strip().lower() in {"unit", "role", "user"}
            and float((item.get("suggestion") or {}).get("confidence_score") or 0.0) >= 0.45
            for item in analysis["report_fields"]
        ):
            opportunities.append("Một số chỉ tiêu có thể tách phạm vi theo đơn vị/vai trò để mỗi nơi chỉ thấy phần cần báo cáo.")

    recipient_insights = _build_recipient_insights(current_config, context)
    analysis["recipient_insights"] = recipient_insights
    if recipient_insights.get("empty_payload_recipients"):
        empty_names = [item.get("user_name") for item in recipient_insights.get("empty_payload_recipients", []) if item.get("user_name")]
        blockers.append(
            f"Có {len(empty_names)} người nhận chưa thấy nội dung báo cáo nào: {', '.join(empty_names[:3])}."
        )
    if recipient_insights.get("high_workload_recipients"):
        heavy_names = [item.get("user_name") for item in recipient_insights.get("high_workload_recipients", []) if item.get("user_name")]
        warnings.append(
            "Một số người nhận đang có tải vận hành cao: "
            + ", ".join(heavy_names[:3])
            + ". Nên cân nhắc chuyển bớt đầu mục hoặc chọn phương án giao theo đơn vị/vai trò."
        )
    if collection_mode in {"form", "file"} and recipient_insights.get("fragmented_units"):
        fragmented_names = [item.get("unit_name") for item in recipient_insights.get("fragmented_units", []) if item.get("unit_name")]
        warnings.append(
            "Một số đơn vị sẽ phải phối hợp qua nhiều nhóm nộp: "
            + ", ".join(fragmented_names[:3])
            + ". Nên rà lại kiểu giao việc để đầu ra phát hành gọn hơn."
        )
    if recipient_insights.get("overloaded_recipients"):
        overloaded_names = [item.get("user_name") for item in recipient_insights.get("overloaded_recipients", []) if item.get("user_name")]
        opportunities.append(
            "Cân nhắc chia lại đầu mục cho "
            + ", ".join(overloaded_names[:2])
            + " vì đang nhận nhiều nội dung hơn mặt bằng chung."
        )
    if recipient_insights.get("single_owner_groups"):
        opportunities.append(
            "Có nhóm nộp đang phụ thuộc vào một cá nhân cho nhiều nội dung. Có thể cân nhắc chuyển sang giao theo đơn vị hoặc vai trò."
        )
    if recipient_insights.get("large_submission_groups"):
        warnings.append("Có nhóm nộp có quy mô phối hợp lớn. Nên chốt rõ đầu mối tổng hợp trước khi phát hành.")

    analysis["publish_ready"] = not blockers
    analysis["score"] = max(0, 100 - len(blockers) * 22 - len(warnings) * 6)
    analysis["summary"] = (
        "Sẵn sàng phát hành." if analysis["publish_ready"]
        else f"Còn {len(blockers)} điểm cần hoàn thiện trước khi phát hành."
    )
    analysis["assignment_strategy"] = _build_assignment_strategy(
        collection_mode,
        analysis["outline_items"],
        analysis["global_assignment"],
        analysis["report_fields"],
        analysis["form_fields"],
    )
    analysis["workflow_stages"] = _build_workflow_stages(
        collection_mode,
        bool(
            (
                analysis["outline_items"]
                if collection_mode == "outline"
                else (analysis["form_fields"] if collection_mode == "form" else analysis["report_fields"])
            )
            or current_config.get("form_fields")
            or current_config.get("report_narrative_enabled")
        ),
        analysis["publish_ready"],
        blockers,
        warnings,
        analysis["outline_items"],
        analysis["global_assignment"],
        analysis["report_fields"],
        analysis["form_fields"],
    )
    analysis["recommended_actions"] = _build_recommended_actions(
        collection_mode,
        blockers,
        warnings,
        analysis["report_fields"],
        analysis["form_fields"],
    )
    analysis["specialist_brief"] = _build_specialist_brief(current_config, analysis)
    return analysis


def build_task_import_ai_prompt(config, heuristic_analysis):
    compact = {
        "title": heuristic_analysis.get("recommended_updates", {}).get("title"),
        "summary": heuristic_analysis.get("recommended_updates", {}).get("summary"),
        "collection_mode": heuristic_analysis.get("collection_mode"),
        "blockers": heuristic_analysis.get("blockers") or [],
        "warnings": heuristic_analysis.get("warnings") or [],
        "outline_items": [
            {
                "title": item.get("title"),
                "assign_type": (item.get("suggestion") or {}).get("assign_type"),
                "targets": (item.get("suggestion") or {}).get("display_targets"),
                "report_kind": (item.get("suggestion") or {}).get("report_kind"),
            }
            for item in (heuristic_analysis.get("outline_items") or [])[:12]
        ],
        "form_fields": [
            {
                "label": item.get("label"),
                "target_type": (item.get("suggestion") or {}).get("target_type"),
                "targets": (item.get("suggestion") or {}).get("display_targets"),
            }
            for item in (heuristic_analysis.get("form_fields") or [])[:12]
        ],
        "report_fields": [
            {
                "label": item.get("label"),
                "target_type": (item.get("suggestion") or {}).get("target_type"),
                "targets": (item.get("suggestion") or {}).get("display_targets"),
            }
            for item in (heuristic_analysis.get("report_fields") or [])[:12]
        ],
        "global_assignment": heuristic_analysis.get("global_assignment"),
        "assignment_strategy": heuristic_analysis.get("assignment_strategy") or {},
        "specialist_brief": heuristic_analysis.get("specialist_brief") or {},
        "template_suggestions": heuristic_analysis.get("template_suggestions") or [],
        "recipient_insights": {
            "recipient_count": (heuristic_analysis.get("recipient_insights") or {}).get("recipient_count", 0),
            "empty_payload_recipients": (heuristic_analysis.get("recipient_insights") or {}).get("empty_payload_recipients", []),
            "high_workload_recipients": (heuristic_analysis.get("recipient_insights") or {}).get("high_workload_recipients", []),
            "overloaded_recipients": (heuristic_analysis.get("recipient_insights") or {}).get("overloaded_recipients", []),
            "fragmented_units": (heuristic_analysis.get("recipient_insights") or {}).get("fragmented_units", []),
            "coordination_hotspots": (heuristic_analysis.get("recipient_insights") or {}).get("coordination_hotspots", []),
        },
    }
    prompt = (
        "Bạn là AI điều hành báo cáo tích hợp nội bộ PC06.\n"
        "Nhiệm vụ: đọc nháp import, đánh giá phương án giao việc và khuyến nghị tinh gọn để quản trị duyệt trước khi phát hành.\n"
        "Yêu cầu trả lời bằng tiếng Việt, rất ngắn gọn, tối đa 6 ý, không xã giao.\n"
        "Chia 3 phần: Nhận định / Rủi ro / Khuyến nghị phát hành.\n"
        "Không nhắc lại toàn bộ dữ liệu đầu vào.\n\n"
        f"Nháp hiện tại:\n{json.dumps(compact, ensure_ascii=False, indent=2)}"
    )
    return prompt


def _selected_ai_sections(sections):
    if sections is None:
        return {"metadata", "global_assignment", "outline_items", "form_fields", "report_fields"}
    if isinstance(sections, str):
        sections = [sections]
    normalized = {
        str(section or "").strip().lower()
        for section in (sections or [])
        if str(section or "").strip()
    }
    if not normalized or "all" in normalized:
        return {"metadata", "global_assignment", "outline_items", "form_fields", "report_fields"}
    allowed = {"metadata", "global_assignment", "outline_items", "form_fields", "report_fields"}
    return {section for section in normalized if section in allowed}


def _normalized_selected_indexes(selection, key):
    if not isinstance(selection, dict):
        return None
    raw_values = selection.get(key)
    if raw_values is None:
        return None
    if not isinstance(raw_values, (list, tuple, set)):
        raw_values = [raw_values]
    normalized = []
    for value in raw_values:
        try:
            numeric_value = int(value)
        except (TypeError, ValueError):
            continue
        if numeric_value not in normalized:
            normalized.append(numeric_value)
    return normalized


def _normalized_selected_index_map(selection, key):
    if not isinstance(selection, dict):
        return {}
    raw_mapping = selection.get(key)
    if not isinstance(raw_mapping, dict):
        return {}
    normalized = {}
    for raw_key, raw_value in raw_mapping.items():
        try:
            index = int(raw_key)
            alt_index = int(raw_value)
        except (TypeError, ValueError):
            continue
        normalized[index] = alt_index
    return normalized


def _alternative_override(base_suggestion, alternative, *, is_target_scope=False):
    if not isinstance(alternative, dict):
        return dict(base_suggestion or {})
    merged = dict(base_suggestion or {})
    merged["assign_type"] = str(alternative.get("assign_type") or merged.get("assign_type") or "").strip().lower()
    merged["unit_domains"] = list(alternative.get("unit_domains") or [])
    merged["role_ids"] = list(alternative.get("role_ids") or [])
    merged["user_ids"] = list(alternative.get("user_ids") or [])
    merged["confidence_score"] = float(alternative.get("confidence_score") or merged.get("confidence_score") or 0.0)
    merged["confidence_label"] = alternative.get("confidence_label") or _confidence_label(merged["confidence_score"])
    merged["display_targets"] = list(alternative.get("display_targets") or [])
    merged["reasons"] = list(alternative.get("reasons") or [])
    if is_target_scope:
        merged["target_type"] = merged["assign_type"] or "all"
        merged["target_unit_domains"] = list(alternative.get("unit_domains") or [])
        merged["target_role_ids"] = list(alternative.get("role_ids") or [])
        merged["target_user_ids"] = list(alternative.get("user_ids") or [])
    return merged


def apply_ai_analysis_to_config(config, analysis, mode="safe", sections=None, selection=None):
    updated = copy.deepcopy(config or {})
    applied = []
    recommended = analysis.get("recommended_updates") or {}
    safe_mode = str(mode or "safe").strip().lower() != "force"
    selected_sections = _selected_ai_sections(sections)
    selected_outline_indexes = _normalized_selected_indexes(selection, "outline_indexes")
    selected_form_field_indexes = _normalized_selected_indexes(selection, "form_field_indexes")
    selected_report_field_indexes = _normalized_selected_indexes(selection, "report_field_indexes")
    selected_outline_alternatives = _normalized_selected_index_map(selection, "outline_alternative_indexes")
    selected_form_field_alternatives = _normalized_selected_index_map(selection, "form_field_alternative_indexes")
    selected_report_field_alternatives = _normalized_selected_index_map(selection, "report_field_alternative_indexes")
    global_assignment_alternative_index = None
    if isinstance(selection, dict) and str(selection.get("global_assignment_alternative_index", "")).strip() != "":
        try:
            global_assignment_alternative_index = int(selection.get("global_assignment_alternative_index"))
        except (TypeError, ValueError):
            global_assignment_alternative_index = None

    if "metadata" in selected_sections and not str(updated.get("title") or "").strip() and recommended.get("title"):
        updated["title"] = str(recommended["title"]).strip()[:255]
        applied.append("Bổ sung tiêu đề nhiệm vụ.")
    if "metadata" in selected_sections and not str(updated.get("summary") or "").strip() and recommended.get("summary"):
        updated["summary"] = str(recommended["summary"]).strip()[:4000]
        applied.append("Bổ sung tóm tắt nhiệm vụ.")
    if "metadata" in selected_sections and not str(updated.get("domain") or "").strip() and recommended.get("domain"):
        updated["domain"] = recommended.get("domain")
        applied.append("Gợi ý đơn vị nghiệp vụ chính.")
    if "metadata" in selected_sections and not str(updated.get("category") or "").strip() and recommended.get("category"):
        updated["category"] = recommended.get("category")
        applied.append("Gợi ý lĩnh vực chính.")
    if "metadata" in selected_sections and str(updated.get("priority") or "").strip() in {"", "Trung bình"} and recommended.get("priority") == "Cao":
        updated["priority"] = "Cao"
        applied.append("Nâng mức ưu tiên theo tín hiệu khẩn.")

    if str(updated.get("collection_mode") or "").strip().lower() == "outline":
        items = list(updated.get("items") or [])
        if "outline_items" in selected_sections:
            for item_analysis in analysis.get("outline_items") or []:
                index = int(item_analysis.get("index") or 0)
                if index >= len(items):
                    continue
                if selected_outline_indexes is not None and index not in selected_outline_indexes:
                    continue
                item = items[index]
                suggestion = item_analysis.get("suggestion") or {}
                alternative_index = selected_outline_alternatives.get(index)
                if alternative_index is not None:
                    alternatives = suggestion.get("alternatives") or []
                    if 0 <= alternative_index < len(alternatives):
                        suggestion = _alternative_override(suggestion, alternatives[alternative_index], is_target_scope=False)
                if (item.get("report_kind") or "narrative") == "narrative" and suggestion.get("report_kind") == "number":
                    item["report_kind"] = "number"
                    applied.append(f'Đổi "{item.get("title")}" sang báo cáo số.')
                if not bool(item.get("attachment_required")) and bool(suggestion.get("attachment_required")):
                    item["attachment_required"] = True
                    applied.append(f'Bật yêu cầu minh chứng cho "{item.get("title")}".')
                if not _assignment_has_targets(
                    item.get("assign_type"),
                    unit_domains=item.get("unit_domains"),
                    role_ids=item.get("role_ids"),
                    user_ids=item.get("user_ids"),
                    fallback_domain=str(updated.get("domain") or "").strip(),
                ):
                    item["assign_type"] = suggestion.get("assign_type") or item.get("assign_type") or ""
                    item["unit_domains"] = list(suggestion.get("unit_domains") or [])
                    item["role_ids"] = list(suggestion.get("role_ids") or [])
                    item["user_ids"] = list(suggestion.get("user_ids") or [])
                    if item.get("assign_type"):
                        applied.append(f'Gợi ý phân công cho "{item.get("title")}".')
        updated["items"] = items
    else:
        if "global_assignment" in selected_sections and not _assignment_has_targets(
            updated.get("assign_type"),
            unit_domains=updated.get("unit_domains"),
            role_ids=updated.get("role_ids"),
            user_ids=updated.get("user_ids"),
            fallback_domain=str(updated.get("domain") or "").strip(),
        ):
            global_assignment = analysis.get("global_assignment") or {}
            if global_assignment_alternative_index is not None:
                alternatives = global_assignment.get("alternatives") or []
                if 0 <= global_assignment_alternative_index < len(alternatives):
                    global_assignment = _alternative_override(global_assignment, alternatives[global_assignment_alternative_index], is_target_scope=False)
            updated["assign_type"] = global_assignment.get("assign_type") or updated.get("assign_type") or ""
            updated["unit_domains"] = list(global_assignment.get("unit_domains") or [])
            updated["role_ids"] = list(global_assignment.get("role_ids") or [])
            updated["user_ids"] = list(global_assignment.get("user_ids") or [])
            if updated.get("assign_type"):
                applied.append("Bổ sung phân công toàn nhiệm vụ.")
        if str(updated.get("collection_mode") or "").strip().lower() == "form":
            form_fields = list(updated.get("form_fields") or [])
            min_confidence = 0.35 if not safe_mode else 0.55
            if "form_fields" in selected_sections:
                for field_analysis in analysis.get("form_fields") or []:
                    index = int(field_analysis.get("index") or 0)
                    if index >= len(form_fields):
                        continue
                    if selected_form_field_indexes is not None and index not in selected_form_field_indexes:
                        continue
                    field = form_fields[index]
                    current_target_type = str(field.get("target_type") or "all").strip().lower() or "all"
                    suggestion = field_analysis.get("suggestion") or {}
                    alternative_index = selected_form_field_alternatives.get(index)
                    if alternative_index is not None:
                        alternatives = suggestion.get("alternatives") or []
                        if 0 <= alternative_index < len(alternatives):
                            suggestion = _alternative_override(suggestion, alternatives[alternative_index], is_target_scope=True)
                    suggested_target_type = str(suggestion.get("target_type") or "all").strip().lower() or "all"
                    confidence_score = float(suggestion.get("confidence_score") or 0.0)
                    if current_target_type not in {"", "all"}:
                        continue
                    if suggested_target_type not in {"unit", "role", "user"} or confidence_score < min_confidence:
                        continue
                    field["target_type"] = suggested_target_type
                    field["target_unit_domains"] = list(suggestion.get("target_unit_domains") or [])
                    field["target_role_ids"] = list(suggestion.get("target_role_ids") or [])
                    field["target_user_ids"] = list(suggestion.get("target_user_ids") or [])
                    applied.append(f'Gợi ý phạm vi nhập liệu cho "{field.get("field_label") or field.get("field_key") or "field"}".')
            updated["form_fields"] = form_fields
        if str(updated.get("collection_mode") or "").strip().lower() == "file":
            report_fields = list(updated.get("report_fields") or [])
            min_confidence = 0.35 if not safe_mode else 0.55
            if "report_fields" in selected_sections:
                for field_analysis in analysis.get("report_fields") or []:
                    index = int(field_analysis.get("index") or 0)
                    if index >= len(report_fields):
                        continue
                    if selected_report_field_indexes is not None and index not in selected_report_field_indexes:
                        continue
                    field = report_fields[index]
                    current_target_type = str(field.get("target_type") or "all").strip().lower() or "all"
                    suggestion = field_analysis.get("suggestion") or {}
                    alternative_index = selected_report_field_alternatives.get(index)
                    if alternative_index is not None:
                        alternatives = suggestion.get("alternatives") or []
                        if 0 <= alternative_index < len(alternatives):
                            suggestion = _alternative_override(suggestion, alternatives[alternative_index], is_target_scope=True)
                    suggested_target_type = str(suggestion.get("target_type") or "all").strip().lower() or "all"
                    confidence_score = float(suggestion.get("confidence_score") or 0.0)
                    if current_target_type not in {"", "all"}:
                        continue
                    if suggested_target_type not in {"unit", "role", "user"} or confidence_score < min_confidence:
                        continue
                    field["target_type"] = suggested_target_type
                    field["target_unit_domains"] = list(suggestion.get("target_unit_domains") or [])
                    field["target_role_ids"] = list(suggestion.get("target_role_ids") or [])
                    field["target_user_ids"] = list(suggestion.get("target_user_ids") or [])
                    applied.append(f'Gợi ý phạm vi báo cáo cho "{field.get("label") or field.get("key") or "chỉ tiêu"}".')
            updated["report_fields"] = report_fields

    updated["ai_analysis"] = copy.deepcopy(analysis)
    updated["ai_last_mode"] = "safe" if safe_mode else "force"
    updated["ai_last_sections"] = sorted(selected_sections)
    updated["ai_last_selection"] = {
        "outline_indexes": list(selected_outline_indexes or []),
        "form_field_indexes": list(selected_form_field_indexes or []),
        "report_field_indexes": list(selected_report_field_indexes or []),
        "outline_alternative_indexes": dict(selected_outline_alternatives),
        "form_field_alternative_indexes": dict(selected_form_field_alternatives),
        "report_field_alternative_indexes": dict(selected_report_field_alternatives),
        "global_assignment_alternative_index": global_assignment_alternative_index,
    }
    updated["ai_last_applied_at"] = datetime.now().isoformat(timespec="seconds")
    return updated, applied
