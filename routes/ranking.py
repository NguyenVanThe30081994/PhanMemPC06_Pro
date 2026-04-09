from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from models import db, RankingUnit, RankingIndicator, RankingEntry
import pandas as pd
import io

ranking_bp = Blueprint('ranking_bp', __name__)

@ranking_bp.route('/ranking')
def index():
    # Load all units and indicators
    units = RankingUnit.query.all()
    indicators = RankingIndicator.query.all()
    
    # Calculate current state
    leaderboard = calculate_leaderboard()
    
    return render_template('ranking.html', units=units, indicators=indicators, leaderboard=leaderboard)

@ranking_bp.route('/ranking/input')
def input_data():
    indicators = RankingIndicator.query.all()
    units = RankingUnit.query.all()
    return render_template('ranking_input.html', indicators=indicators, units=units)

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

def calculate_leaderboard():
    # Logic based on V13 plan
    # 1. For each indicator, rank all 124 units
    units = RankingUnit.query.all()
    indicators = RankingIndicator.query.all()
    
    unit_totals = {u.id: 0 for u in units}
    unit_names = {u.id: u.name for u in units}
    
    for ind in indicators:
        entries = RankingEntry.query.filter_by(indicator_id=ind.id).all()
        # Map values
        val_map = {e.unit_id: e.raw_value for e in entries}
        # Filling missing
        for u in units:
            if u.id not in val_map: val_map[u.id] = 0
            
        # Rank them
        sorted_unit_ids = sorted(val_map.keys(), key=lambda uid: val_map[uid], reverse=ind.higher_is_better)
        
        # Assign points (Rank * Coef)
        # Note: In Excel, Rank 1 = 1 point. Low sum = good.
        for rank, uid in enumerate(sorted_unit_ids, 1):
            # Handle ties (simplified for now, ideally same value = same rank)
            unit_totals[uid] += rank * ind.coef
            
    # Final Ranking
    final_list = []
    for uid, total in unit_totals.items():
        final_list.append({"id": uid, "name": unit_names[uid], "total_score": total})
        
    # Sort by total_score ASCENDING (Lower is better)
    final_list = sorted(final_list, key=lambda x: x['total_score'])
    
    # Assign Tiers
    # Tier 1 (10), Tier 2 (20), etc.
    for i, item in enumerate(final_list, 1):
        item['rank'] = i
        base_points = 0
        if i <= 10: item['group'] = 1; base_points = 12
        elif i <= 30: item['group'] = 2; base_points = 9
        elif i <= 50: item['group'] = 3; base_points = 8
        elif i <= 70: item['group'] = 4; base_points = 7
        elif i <= 90: item['group'] = 5; base_points = 6
        elif i <= 110: item['group'] = 6; base_points = 5
        else: item['group'] = 7; base_points = 2
        
        # Check security violation (id of indicator "treem" or similar if assigned to ANAT)
        # For now, let's check a specific indicator named "An ninh an toàn" or similar
        # If the unit has a value > 0 in ANAT indicator, subtract 4
        # We'll look for an indicator with sheet_name 'dangkyxe' or specifically added for ANAT
        # For simplicity, if you want a fixed penalty, we could add a checkbox in UI.
        # But let's check indicator with sheet_name 'dangkyxe' (Col 23 in excel was ANAT)
        anat_ind = RankingIndicator.query.filter(RankingIndicator.sheet_name.like('%dangkyxe%')).first()
        if anat_ind:
            entry = RankingEntry.query.filter_by(unit_id=item['id'], indicator_id=anat_ind.id).first()
            if entry and entry.raw_value > 0:
                base_points -= 4
        
        item['group_points'] = base_points
        
    return final_list
