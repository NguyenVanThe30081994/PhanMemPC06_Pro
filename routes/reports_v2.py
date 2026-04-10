from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from models import db, ReportTemplateV2, ReportVersionV2, ReportSubmissionV2, ReportValueV2, ReportAuditV2, User
from pc06_excel_engine import ExcelEngineV2
import json
import io
import os
from datetime import datetime

reports_v2_bp = Blueprint('reports_v2_bp', __name__)


@reports_v2_bp.route('/reports-v2')
def dashboard():
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
    templates = ReportTemplateV2.query.order_by(ReportTemplateV2.created_at.desc()).all()
    is_admin = session.get('is_admin', False)
    return render_template('reports_v2_dashboard.html', templates=templates, is_admin=is_admin)


@reports_v2_bp.route('/reports-v2/upload', methods=['POST'])
def upload_template():
    if not session.get('is_admin'):
        return jsonify({"error": "Unauthorized"}), 403

    file = request.files.get('template_excel')
    name = request.form.get('name', 'Báo cáo Mới')
    is_daily = request.form.get('is_daily') == 'true' or 'is_daily' in request.form

    if not file or not file.filename:
        return jsonify({"error": "No file uploaded"}), 400

    try:
        file_content = file.read()
        temp_path = os.path.join("tmp", file.filename)
        os.makedirs("tmp", exist_ok=True)
        with open(temp_path, "wb") as f:
            f.write(file_content)

        metadata = ExcelEngineV2.parse_template(temp_path)

        template = ReportTemplateV2.query.filter_by(name=name).first()
        is_new = False
        if not template:
            template = ReportTemplateV2(
                name=name,
                created_by=session.get('fullname'),
                is_daily=is_daily
            )
            db.session.add(template)
            db.session.flush()
            is_new = True
        else:
            template.is_daily = is_daily

        new_version = ReportVersionV2(
            template_id=template.id,
            version_tag=datetime.now().strftime("%Y%m%d%H%M"),
            metadata_json=json.dumps(metadata, ensure_ascii=False),
            excel_file_blob=file_content,
            is_published=True
        )
        db.session.add(new_version)

        ExcelEngineV2.save_logic_to_source(name, metadata)

        db.session.commit()
        
        if is_new:
            from utils import push_global_notif
            push_global_notif("Biểu mẫu mới", f"Vừa có biểu mẫu mới: {name}", f"/reports-v2/render/{template.id}", exclude_uid=session['uid'])

        if os.path.exists(temp_path):
            os.remove(temp_path)

        return jsonify({"success": True, "template_id": template.id, "version_id": new_version.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@reports_v2_bp.route('/reports-v2/edit/<int:tid>', methods=['GET', 'POST'])
def edit_template(tid):
    if not session.get('is_admin'):
        return redirect(url_for('auth_bp.login'))

    template = db.session.get(ReportTemplateV2, tid)
    if not template:
        flash('Không tìm thấy biểu mẫu V2!', 'danger')
        return redirect(url_for('reports_v2_bp.dashboard'))

    if request.method == 'POST':
        template.name = request.form.get('name', template.name)
        template.description = request.form.get('description', template.description)
        template.is_daily = 'is_daily' in request.form

        # If a new file is uploaded, create a new version
        file = request.files.get('template_excel')
        if file and file.filename:
            try:
                file_content = file.read()
                temp_path = os.path.join("tmp", file.filename)
                os.makedirs("tmp", exist_ok=True)
                with open(temp_path, "wb") as f:
                    f.write(file_content)

                metadata = ExcelEngineV2.parse_template(temp_path)

                # Unpublish old versions
                ReportVersionV2.query.filter_by(template_id=tid, is_published=True).update({'is_published': False})

                new_version = ReportVersionV2(
                    template_id=tid,
                    version_tag=datetime.now().strftime("%Y%m%d%H%M"),
                    metadata_json=json.dumps(metadata, ensure_ascii=False),
                    excel_file_blob=file_content,
                    is_published=True
                )
                db.session.add(new_version)
                ExcelEngineV2.save_logic_to_source(template.name, metadata)

                if os.path.exists(temp_path):
                    os.remove(temp_path)

                flash('Đã cập nhật file Excel và tạo phiên bản mới!', 'info')
            except Exception as e:
                db.session.rollback()
                flash(f'Lỗi xử lý file: {str(e)}', 'danger')
                return redirect(url_for('reports_v2_bp.edit_template', tid=tid))

        db.session.commit()
        flash('Đã cập nhật biểu mẫu V2!', 'success')
        return redirect(url_for('reports_v2_bp.dashboard'))

    versions = ReportVersionV2.query.filter_by(template_id=tid).order_by(ReportVersionV2.created_at.desc()).all()
    return render_template('reports_v2_edit.html', template=template, versions=versions)


@reports_v2_bp.route('/reports-v2/delete/<int:tid>', methods=['POST'])
def delete_template(tid):
    if not session.get('is_admin'):
        return jsonify({"error": "Unauthorized"}), 403

    template = db.session.get(ReportTemplateV2, tid)
    if not template:
        return jsonify({"error": "Not found"}), 404

    try:
        # Cascade delete: versions -> submissions -> values
        versions = ReportVersionV2.query.filter_by(template_id=tid).all()
        for v in versions:
            for sub in ReportSubmissionV2.query.filter_by(version_id=v.id).all():
                ReportValueV2.query.filter_by(submission_id=sub.id).delete()
                ReportAuditV2.query.filter_by(submission_id=sub.id).delete()
                db.session.delete(sub)
            db.session.delete(v)
        db.session.delete(template)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@reports_v2_bp.route('/reports-v2/render/<int:tid>')
def render_report(tid):
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    template = db.session.get(ReportTemplateV2, tid)
    if not template:
        return "Template Not Found", 404

    version = ReportVersionV2.query.filter_by(
        template_id=tid, is_published=True
    ).order_by(ReportVersionV2.created_at.desc()).first()
    if not version:
        return "No published version found", 404

    if not version.excel_file_blob:
        return "No Excel file stored for this version", 400

    # Load existing submitted values for current user (draft)
    submission = ReportSubmissionV2.query.filter_by(
        version_id=version.id, user_id=session['uid'], status='draft'
    ).first()
    existing_values = {}
    if submission:
        for val in submission.values:
            existing_values[val.cell_key] = val.value

    user_unit = session.get('unit_area', session.get('unit', ''))
    is_admin = session.get('is_admin', False)

    # Render each sheet faithfully using the excel_renderer engine
    from excel_renderer import render_range_to_html, _build_merge_lookup, _col_widths_px
    import openpyxl as _opx

    try:
        wb = _opx.load_workbook(io.BytesIO(version.excel_file_blob), data_only=True)
    except Exception as e:
        return f"Error loading Excel: {e}", 500

    sheets_html = []
    for ws in wb.worksheets:
        spans, shadows = _build_merge_lookup(ws)
        col_widths = _col_widths_px(ws)

        # Build colgroup
        colgroup = '<colgroup>' + ''.join(
            f'<col style="width:{w}px">' for w in col_widths
        ) + '</colgroup>'

        # Render all rows, applying unit filter for non-admin users
        # Use the "True" Used Range from metadata if available
        meta_data = {}
        try: meta_data = json.loads(version.metadata_json or '{}')
        except: pass
        
        sheet_meta = next((s for s in meta_data.get('sheets', []) if s['name'] == ws.title), None)
        if sheet_meta:
            region = sheet_meta.get('activeRenderRegion', {})
            min_row = region.get('r1', 1)
            min_col = region.get('c1', 1)
            max_row = region.get('r2', ws.max_row)
            max_col = region.get('c2', ws.max_column)
        else:
            # Fallback for old metadata
            max_row, max_col = ExcelEngineV2._get_true_max_row_col(wb, ws)
            min_row, min_col = 1, 1

        rows_html = []
        from excel_renderer import _row_height_px, _cell_css
        from openpyxl.styles.fills import PatternFill

        # Robust input marker detection
        INPUT_MARKERS = ['FFE0F2FE', '00E0F2FE', 'E0F2FE']

        for r in range(min_row, max_row + 1):
            if ws.row_dimensions[r].hidden:
                continue

            # Unit-row filtering for non-admin users
            if not is_admin and user_unit:
                # 1. Detect if row has any input cells
                has_input = False
                for c in range(1, max_col + 1):
                    cell = ws.cell(row=r, column=c)
                    try:
                        fill = cell.fill
                        if isinstance(fill, PatternFill) and fill.patternType == 'solid' and hasattr(fill.fgColor, 'rgb'):
                            rgb = str(fill.fgColor.rgb).upper()
                            if rgb in INPUT_MARKERS or any(m in rgb for m in INPUT_MARKERS):
                                has_input = True
                                break
                    except Exception: pass
                
                # 2. If it's a data row (has input), check if it matches user's unit
                if has_input:
                    row_text = ''
                    for c in range(1, max_col + 1):
                        cell = ws.cell(row=r, column=c)
                        v = cell.value
                        if v and not (isinstance(v, str) and v.startswith('=')):
                            row_text += str(v)
                    
                    if user_unit not in row_text:
                        continue

            rh = _row_height_px(ws, r)
            row_parts = [f'<tr style="height:{rh}px">']
            for c in range(1, max_col + 1):
                if (r, c) in shadows:
                    continue
                cell = ws.cell(row=r, column=c)
                rowspan, colspan = spans.get((r, c), (1, 1))
                css = _cell_css(cell)

                is_input = False
                try:
                    fill = cell.fill
                    if (isinstance(fill, PatternFill) and fill.patternType == 'solid' and hasattr(fill.fgColor, 'rgb')):
                        rgb = str(fill.fgColor.rgb).upper()
                        if rgb in INPUT_MARKERS or any(m in rgb for m in INPUT_MARKERS):
                            is_input = True
                except Exception:
                    pass

                coord = cell.coordinate
                rs_attr = f' rowspan="{rowspan}"' if rowspan > 1 else ''
                cs_attr = f' colspan="{colspan}"' if colspan > 1 else ''
                base = 'padding:3px 6px;border:1px solid #d1d5db;overflow:hidden;box-sizing:border-box;'
                if is_input:
                    base += 'background-color:#e0f2fe;'
                full_css = base + css
                td = f'<td{rs_attr}{cs_attr} style="{full_css}">'

                if is_input:
                    val = existing_values.get(coord, '')
                    safe_val = str(val).replace('"', '&quot;')
                    inner = (
                        f'<input type="text" class="grid-input" '
                        f'data-key="{coord}" data-coord="{coord}" '
                        f'value="{safe_val}" onchange="markDirty()" '
                        f'style="width:100%;height:100%;border:none;'
                        f'background:transparent;padding:2px;font-size:inherit;">'
                    )
                else:
                    raw = cell.value
                    if isinstance(raw, str) and raw.startswith('='):
                        raw = ''
                    inner = '' if raw is None else str(raw)

                row_parts.append(f'{td}{inner}</td>')
            row_parts.append('</tr>')
            rows_html.append(''.join(row_parts))

        table_html = (
            f'<table class="excel-render-table" '
            f'style="border-collapse:collapse;font-size:12px;width:100%;table-layout:fixed;'
            f'font-family:Calibri,Arial,sans-serif;min-width:1000px;">'
            f'{colgroup}'
            f'<tbody>{"".join(rows_html)}</tbody>'
            f'</table>'
        )

        from markupsafe import Markup
        sheets_html.append({
            'name': ws.title,
            'html': Markup(table_html)
        })

    v2_templates = ReportTemplateV2.query.all()
    return render_template('reports_v2_render.html',
                           template=template,
                           version=version,
                           sheets_html=sheets_html,
                           is_admin=is_admin,
                           user_unit=user_unit,
                           v2_templates=v2_templates,
                           form_type='v2')




@reports_v2_bp.route('/reports-v2/submit', methods=['POST'])
def submit_data():
    if not session.get('uid'):
        return jsonify({"error": "Unauthorized"}), 403

    data = request.json
    version_id = data.get('version_id')
    values = data.get('values', {})

    try:
        submission = ReportSubmissionV2.query.filter_by(
            version_id=version_id,
            user_id=session['uid'],
            status='draft'
        ).first()

        if not submission:
            submission = ReportSubmissionV2(
                version_id=version_id,
                user_id=session['uid'],
                org_unit=session.get('unit_area', session.get('unit', 'PC06'))
            )
            db.session.add(submission)
            db.session.flush()

        for key, val in values.items():
            existing_val = ReportValueV2.query.filter_by(
                submission_id=submission.id, cell_key=key
            ).first()
            old_val = existing_val.value if existing_val else None

            if str(old_val) != str(val):
                audit = ReportAuditV2(
                    submission_id=submission.id,
                    user_id=session['uid'],
                    cell_key=key,
                    old_value=old_val,
                    new_value=val
                )
                db.session.add(audit)

                if existing_val:
                    existing_val.value = val
                else:
                    db.session.add(ReportValueV2(
                        submission_id=submission.id, cell_key=key, value=val
                    ))

        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@reports_v2_bp.route('/reports-v2/export/<int:sid>')
def export_submission(sid):
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    submission = db.session.get(ReportSubmissionV2, sid)
    if not submission:
        return "Submission Not Found", 404

    version = submission.version
    if not version.excel_file_blob:
        return "No original template file found", 400

    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(version.excel_file_blob))

        for val in submission.values:
            for ws in wb.worksheets:
                try:
                    ws[val.cell_key].value = val.value
                except Exception:
                    pass

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        filename = f"Report_{submission.org_unit}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        from flask import send_file
        return send_file(output, as_attachment=True, download_name=filename)
    except Exception as e:
        return str(e), 500
@reports_v2_bp.route('/reports-v2/submission/<int:sub_id>')
def review_submission(sub_id):
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    submission = db.session.get(ReportSubmissionV2, sub_id)
    if not submission:
        flash('Không tìm thấy bản nộp!', 'danger')
        return redirect(url_for('forms_bp.stats'))

    version = submission.version
    template = version.template
    
    # Load submitted values
    existing_values = {val.cell_key: val.value for val in submission.values}

    from excel_renderer import _build_merge_lookup, _col_widths_px, _row_height_px, _cell_css
    import openpyxl as _opx

    try:
        wb = _opx.load_workbook(io.BytesIO(version.excel_file_blob), data_only=True)
    except Exception as e:
        return f"Error loading Excel: {e}", 500

    sheets_html = []
    meta_data = {}
    try: meta_data = json.loads(version.metadata_json or '{}')
    except: pass

    for ws in wb.worksheets:
        sheet_meta = next((s for s in meta_data.get('sheets', []) if s['name'] == ws.title), None)
        if sheet_meta:
            region = sheet_meta.get('activeRenderRegion', {})
            min_row = region.get('r1', 1)
            min_col = region.get('c1', 1)
            max_row = region.get('r2', ws.max_row)
            max_col = region.get('c2', ws.max_column)
        else:
            max_row, max_col = ExcelEngineV2._get_true_max_row_col(wb, ws)
            min_row, min_col = 1, 1

        spans, shadows = _build_merge_lookup(ws)
        col_widths = []
        for i in range(min_col, max_col + 1):
            letter = _opx.utils.get_column_letter(i)
            w = ws.column_dimensions[letter].width or 8.43
            col_widths.append(max(int(w * 7), 45))

        colgroup = '<colgroup>' + ''.join(f'<col style="width:{w}px">' for w in col_widths) + '</colgroup>'
        rows_html = []

        for r in range(min_row, max_row + 1):
            if ws.row_dimensions[r].hidden: continue
            rh = _row_height_px(ws, r)
            row_parts = [f'<tr style="height:{rh}px">']
            for c in range(min_col, max_col + 1):
                if (r, c) in shadows: continue
                cell = ws.cell(row=r, column=c)
                rowspan, colspan = spans.get((r, c), (1, 1))
                css = _cell_css(cell)
                
                coord = cell.coordinate
                val = existing_values.get(coord, cell.value if cell.value and not str(cell.value).startswith('=') else '')
                
                rs_attr = f' rowspan="{rowspan}"' if rowspan > 1 else ''
                cs_attr = f' colspan="{colspan}"' if colspan > 1 else ''
                # Highlight input cells but make them span/div instead of input
                is_input = False
                INPUT_MARKERS = ['FFE0F2FE', '00E0F2FE', 'E0F2FE']
                try:
                    fill = cell.fill
                    if (isinstance(fill, PatternFill) and fill.patternType == 'solid' and hasattr(fill.fgColor, 'rgb')):
                        rgb = str(fill.fgColor.rgb).upper()
                        if rgb in INPUT_MARKERS or any(m in rgb for m in INPUT_MARKERS):
                            is_input = True
                except Exception: pass
                
                bg = 'background-color:#f0f9ff;' if is_input else ''
                td = f'<td{rs_attr}{cs_attr} style="padding:3px 6px;border:1px solid #d1d5db;{bg}{css}">'
                row_parts.append(f'{td}{val}</td>')
            row_parts.append('</tr>')
            rows_html.append(''.join(row_parts))

        sheets_html.append({
            'name': ws.title,
            'html': f'<table class="excel-render-table" style="border-collapse:collapse;font-size:12px;width:100%;table-layout:fixed;font-family:Calibri,Arial,sans-serif;min-width:1000px;">{colgroup}<tbody>{"".join(rows_html)}</tbody></table>'
        })

    return render_template('reports_v2_review.html', 
                           submission=submission, 
                           template=template,
                           sheets=sheets_html)
