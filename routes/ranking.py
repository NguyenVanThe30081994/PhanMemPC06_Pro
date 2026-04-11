from datetime import datetime
import io
import re

import openpyxl
import pandas as pd
from flask import Blueprint, jsonify, render_template, request, send_file
from utils import normalize_unit_name, remove_accents, safe_float, render_auto_template

from models import RankingEntry, RankingIndicator, RankingUnit, db
from utils import normalize_unit_name, remove_accents, safe_float


ranking_bp = Blueprint('ranking_bp', __name__)


@ranking_bp.route('/ranking')
def index():
    units = RankingUnit.query.all()
    indicators = RankingIndicator.query.all()
    leaderboard = calculate_leaderboard()
    return render_auto_template('ranking.html', units=units, indicators=indicators, leaderboard=leaderboard)


@ranking_bp.route('/ranking/input')
def input_data():
    indicators = RankingIndicator.query.all()
    return render_template('ranking_input.html', indicators=indicators)


@ranking_bp.route('/ranking/api/save', methods=['POST'])
def save_entry():
    data = request.json
    unit_id = data.get('unit_id')
    indicator_id = data.get('indicator_id')
    val = data.get('value')

    if val is None or val == '':
        return jsonify({"status": "no_value"})

    entry = RankingEntry.query.filter_by(unit_id=unit_id, indicator_id=indicator_id).first()
    if not entry:
        entry = RankingEntry(unit_id=unit_id, indicator_id=indicator_id)
        db.session.add(entry)

    entry.raw_value = float(val)
    db.session.commit()
    return jsonify({"status": "ok"})


@ranking_bp.route('/ranking/api/values/<int:indicator_id>')
def get_values(indicator_id):
    entries = RankingEntry.query.filter_by(indicator_id=indicator_id).all()
    return jsonify({e.unit_id: e.raw_value for e in entries})


@ranking_bp.route('/ranking/template')
def download_template():
    units = RankingUnit.query.all()
    indicators = RankingIndicator.query.all()

    data = {"Đơn vị Công an xã/thị trấn": [u.name for u in units]}
    for ind in indicators:
        data[ind.name] = [0.0] * len(units)

    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='DuLieuChamDiem')
        ws = writer.sheets['DuLieuChamDiem']
        for i, _ in enumerate(df.columns):
            ws.column_dimensions[openpyxl.utils.get_column_letter(i + 1)].width = 30

    output.seek(0)
    return send_file(
        output,
        download_name=f"Mau_ChamDiem_{datetime.now().strftime('%Y%m%d')}.xlsx",
        as_attachment=True,
    )


def _normalize_indicator_key(value):
    text = remove_accents(value or "")
    text = re.sub(r'[^a-z0-9]+', ' ', text).strip()
    return re.sub(r'\s+', ' ', text)


def _is_unit_column(value):
    key = _normalize_indicator_key(value)
    unit_tokens = [
        'don vi',
        'ten don vi',
        'cong an xa',
        'cong an phuong',
        'cong an thi tran',
        'xa thi tran',
        'ten xa',
        'ten phuong',
        'ten thi tran',
    ]
    return any(token in key for token in unit_tokens)


def _choose_value_column(df, unit_col):
    candidates = [col for col in df.columns if col != unit_col]
    if not candidates:
        return None

    ranked_candidates = []
    for col in candidates:
        non_null = df[col].dropna()
        if len(non_null) == 0:
            continue
        numeric_count = sum(
            1
            for val in non_null.head(50)
            if safe_float(val) != 0 or str(val).strip() in {'0', '0.0', '0,0'}
        )
        ranked_candidates.append((numeric_count, len(non_null), col))

    if not ranked_candidates:
        return candidates[0]

    ranked_candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return ranked_candidates[0][2]


import pdfplumber

@ranking_bp.route('/ranking/import', methods=['POST'])
def import_ranking_data():
    if 'file' not in request.files:
        return jsonify({"success": False, "message": "Không tìm thấy file!"}), 400

    file = request.files['file']
    indicator_id = request.form.get('indicator_id')
    if not file.filename:
        return jsonify({"success": False, "message": "File không hợp lệ!"}), 400

    filename = file.filename.lower()
    db_units = RankingUnit.query.all()
    unit_map = {normalize_unit_name(u.name): u for u in db_units}
    
    selected_indicator = None
    if indicator_id:
        selected_indicator = db.session.get(RankingIndicator, int(indicator_id))

    imported_values = {} # (unit_id, indicator_id) -> float
    matched_indicator_ids = set()
    unmatched_units = set()
    unmatched_indicators = set()
    processed_sheets = []

    try:
        if filename.endswith(('.xlsx', '.xls')):
            # --- EXCEL LOGIC ---
            excel_file = pd.ExcelFile(file)
            db_indicators = RankingIndicator.query.all()
            indicator_aliases = {}
            for ind in db_indicators:
                for alias in [ind.name, ind.sheet_name]:
                    alias_key = _normalize_indicator_key(alias)
                    if alias_key:
                        indicator_aliases[alias_key] = ind

            for sheet_name in excel_file.sheet_names:
                df = pd.read_excel(excel_file, sheet_name=sheet_name)
                if df.empty or len(df.columns) == 0: continue
                df = df.dropna(how='all')
                if df.empty: continue
                
                df.columns = [str(c).strip() for c in df.columns]
                unit_col = next((col for col in df.columns if _is_unit_column(col)), df.columns[0])

                active_cols = []
                if selected_indicator:
                    # If specific indicator selected, find the best value column (excluding unit column)
                    value_col = _choose_value_column(df, unit_col)
                    if value_col:
                        active_cols.append((value_col, selected_indicator))
                else:
                    # Original logic: auto-detect multiple indicators
                    for col in df.columns:
                        if col == unit_col: continue
                        indicator = indicator_aliases.get(_normalize_indicator_key(col))
                        if indicator:
                            active_cols.append((col, indicator))
                        else:
                            unmatched_indicators.add(str(col).strip())
                    
                    if not active_cols:
                        sheet_indicator = indicator_aliases.get(_normalize_indicator_key(sheet_name))
                        if sheet_indicator:
                            value_col = _choose_value_column(df, unit_col)
                            if value_col:
                                active_cols.append((value_col, sheet_indicator))

                if not active_cols: continue
                processed_sheets.append(sheet_name)

                for _, row in df.iterrows():
                    raw_name = row.get(unit_col)
                    if pd.isna(raw_name) or str(raw_name).strip() == '': continue
                    unit = unit_map.get(normalize_unit_name(str(raw_name).strip()))
                    if not unit:
                        unmatched_units.add(str(raw_name).strip())
                        continue
                    for col, indicator in active_cols:
                        imported_values[(unit.id, indicator.id)] = safe_float(row.get(col))
                        matched_indicator_ids.add(indicator.id)

        elif filename.endswith('.pdf'):
            # --- PDF LOGIC ---
            if not selected_indicator:
                return jsonify({"success": False, "message": "Vui lòng chọn Chỉ tiêu trước khi tải file PDF."}), 400
            
            with pdfplumber.open(file) as pdf:
                for page in pdf.pages:
                    # 1. Try Extracting Tables
                    tables = page.extract_tables()
                    for table in tables:
                        for row in table:
                            if not row or len(row) < 2: continue
                            # Search for unit name in any cell
                            unit = None
                            val = None
                            for cell in row:
                                if not cell: continue
                                u = unit_map.get(normalize_unit_name(cell))
                                if u: 
                                    unit = u
                                    break
                            
                            if unit:
                                # Look for a number in the row
                                for cell in row:
                                    f_val = safe_float(cell)
                                    if f_val != 0 or str(cell).strip() in ['0', '0.0']:
                                        val = f_val
                                        break
                                if val is not None:
                                    imported_values[(unit.id, selected_indicator.id)] = val
                                    matched_indicator_ids.add(selected_indicator.id)
                    
                    # 2. Fallback to Text extraction if no values found in tables
                    if not imported_values:
                        text = page.extract_text()
                        if text:
                            for line in text.split('\n'):
                                for u_norm, unit in unit_map.items():
                                    if u_norm in normalize_unit_name(line):
                                        # Use regex to find the last number in the line
                                        nums = re.findall(r'(\d+[.,]?\d*)', line)
                                        if nums:
                                            imported_values[(unit.id, selected_indicator.id)] = safe_float(nums[-1])
                                            matched_indicator_ids.add(selected_indicator.id)
                                        break

        else:
            return jsonify({"success": False, "message": "Định dạng file không được hỗ trợ (chỉ nhận .xlsx, .xls, .pdf)"}), 400

        if not imported_values:
            return jsonify({
                "success": False,
                "message": "Không quét được dữ liệu hợp lệ. Vui lòng kiểm tra lại cấu trúc file."
            }), 400

        # --- SAVE DATA ---
        if selected_indicator:
            # Wipe only the specific indicator's data
            RankingEntry.query.filter_by(indicator_id=selected_indicator.id).delete()
        else:
            # Wipe all only if importing whole sheet (auto-detect mode)
            db.session.query(RankingEntry).delete()

        for (unit_id, indicator_id), value in imported_values.items():
            db.session.add(RankingEntry(unit_id=unit_id, indicator_id=indicator_id, raw_value=value))

        db.session.commit()
        return jsonify({
            "success": True,
            "synced_entries": len(imported_values),
            "indicator_name": selected_indicator.name if selected_indicator else None,
            "processed_sheets": processed_sheets,
            "matched_indicators": len(matched_indicator_ids),
            "unmatched_units": sorted(unmatched_units)[:10],
            "unmatched_indicators": sorted(unmatched_indicators)[:10],
        })

    except Exception as e:
        db.session.rollback()
        import traceback
        print(traceback.format_exc())
        return jsonify({"success": False, "message": f"Lỗi hệ thống: {str(e)}"}), 500


@ranking_bp.route('/ranking/export')
def export_ranking():
    leaderboard = calculate_leaderboard()

    data = []
    for item in leaderboard:
        data.append({
            "Thứ hạng": item['rank'],
            "Đơn vị Công an xã": item['name'],
            "Tổng điểm cộng dồn (Thấp là tốt)": item['total_score'],
            "Phân nhóm": f"Nhóm {item['group']}",
            "Điểm nhóm quy đổi": item['group_points'],
        })

    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Xếp hạng 124 xã')
        worksheet = writer.sheets['Xếp hạng 124 xã']

        for i, col in enumerate(df.columns):
            column_len = max(df[col].astype(str).str.len().max(), len(col)) + 5
            worksheet.column_dimensions[openpyxl.utils.get_column_letter(i + 1)].width = column_len

    output.seek(0)
    filename = f"XepHang_PC06_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return send_file(output, download_name=filename, as_attachment=True)


def calculate_leaderboard():
    units = RankingUnit.query.all()
    indicators = RankingIndicator.query.all()

    unit_totals = {u.id: 0 for u in units}
    unit_names = {u.id: u.name for u in units}

    for ind in indicators:
        entries = RankingEntry.query.filter_by(indicator_id=ind.id).all()
        val_map = {e.unit_id: e.raw_value for e in entries}

        for u in units:
            if u.id not in val_map:
                val_map[u.id] = 0

        sorted_unit_ids = sorted(val_map.keys(), key=lambda uid: val_map[uid], reverse=ind.higher_is_better)

        for rank, uid in enumerate(sorted_unit_ids, 1):
            unit_totals[uid] += rank * ind.coef

    final_list = []
    for uid, total in unit_totals.items():
        final_list.append({"id": uid, "name": unit_names[uid], "total_score": total})

    final_list = sorted(final_list, key=lambda x: x['total_score'])

    for i, item in enumerate(final_list, 1):
        item['rank'] = i
        base_points = 0
        if i <= 10:
            item['group'] = 1
            base_points = 12
        elif i <= 30:
            item['group'] = 2
            base_points = 9
        elif i <= 50:
            item['group'] = 3
            base_points = 8
        elif i <= 70:
            item['group'] = 4
            base_points = 7
        elif i <= 90:
            item['group'] = 5
            base_points = 6
        elif i <= 110:
            item['group'] = 6
            base_points = 5
        else:
            item['group'] = 7
            base_points = 2

        anat_ind = RankingIndicator.query.filter(RankingIndicator.sheet_name.like('%dangkyxe%')).first()
        if anat_ind:
            entry = RankingEntry.query.filter_by(unit_id=item['id'], indicator_id=anat_ind.id).first()
            if entry and entry.raw_value > 0:
                base_points -= 4

        item['group_points'] = base_points

    return final_list
