# -*- coding: utf-8 -*-
# Convert module - temporarily disabled
# Will be implemented later

from flask import Blueprint, render_template

convert_bp = Blueprint('convert', __name__)

@convert_bp.route('/convert')
def index():
    """Render convert page"""
    return render_template('convert.html')
