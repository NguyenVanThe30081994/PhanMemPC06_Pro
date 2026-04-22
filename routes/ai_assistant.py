# -*- coding: utf-8 -*-
from flask import Blueprint, render_template, request, session, jsonify, redirect, url_for
import os
import requests
import re
import json
from datetime import datetime

ai_bp = Blueprint('ai_bp', __name__, url_prefix='/ai')

# OpenAI API Key - Project Key với Org ID
OPENAI_API_KEY = 'sk-proj-Q8P7u9VwRz2jKxL1mN4bV5cA6dE7fG8hI9jK0lL1mN2oP3qR4sT5uV6wX7yZ8A9B'
OPENAI_ORG_ID = 'org-NEWORGID1234567890ABCDEF'

# TTHC Knowledge Base - Thủ tục hành chính PC06
TTHC_KNOWLEDGE = {
    "cấp giấy giới thiệu": {
        "answer": "Để cấp giấy giới thiệu, công dân cần chuẩn bị: 1) Đơn xin cấp giấy giới thiệu; 2) CMND/CCCD; 3) Các giấy tờ liên quan đến mục đích giới thiệu. Thời gian giải quyết: trong ngày hoặc tối đa 3 ngày làm việc.",
        "keywords": ["giấy giới thiệu", "cấp giấy", "xác nhận"]
    },
    "đăng ký thường trú": {
        "answer": "Hồ sơ đăng ký thường trú gồm: 1) Tờ khai đăng ký thường trú; 2) CMND/CCCD của người đăng ký; 3) Sổ hộ khẩu hoặc giấy tờ chứng minh chỗ ở hợp pháp. Thời gian: 15 ngày kể từ ngày nhận đủ hồ sơ.",
        "keywords": ["thường trú", "đăng ký", "hộ khẩu", "cư trú"]
    },
    "đăng ký tạm trú": {
        "answer": "Hồ sơ đăng ký tạm trú: 1) Tờ khai đăng ký tạm trú; 2) CMND/CCCD; 3) Giấy tờ chứng minh chỗ ở hợp pháp (hợp đồng thuê nhà, xác nhận của chủ nhà...). Thời gian: 3 ngày làm việc.",
        "keywords": ["tạm trú", "đăng ký", "tạm vắng"]
    },
    "lý lịch tư pháp": {
        "answer": "Giấy lý lịch tư pháp được cấp tại Công an cấp huyện hoặc cấp tỉnh. Hồ sơ: 1) Đơn xin cấp; 2) CMND/CCCD; 3) Sổ hộ khẩu. Thời gian: 10 ngày làm việc.",
        "keywords": ["lý lịch", "tư pháp", "phi pháp"]
    },
    "hộ chiếu": {
        "answer": "Hồ sơ xin cấp hộ chiếu: 1) Tờ khai theo mẫu; 2) 02 ảnh 4x6; 3) CMND/CCCD; 4) Sổ hộ khẩu. Nộp tại Công an tỉnh hoặc Phòng quản lý xuất nhập cảnh. Thời gian: 15 ngày làm việc.",
        "keywords": ["hộ chiếu", "passport", "xuất cảnh", "nhập cảnh"]
    },
    "đăng ký kinh doanh": {
        "answer": "Đăng ký kinh doanh tại Phòng Đăng ký kinh doanh thuộc Sở Kế hoạch và Đầu tư. Hồ sơ: 1) Giấy đề nghị đăng ký; 2) Điều lệ công ty; 3) Danh sách thành viên/cổ đông. Thời gian: 3 ngày làm việc.",
        "keywords": ["kinh doanh", "đăng ký", "thành lập", "doanh nghiệp"]
    },
    "thuế": {
        "answer": "Các thủ tục thuế thường gặp: 1) Đăng ký thuế; 2) Khai thuế; 3) Hoàn thuế; 4) Gia hạn nộp thuế. Nộp hồ sơ tại Chi cục Thuế hoặc qua cổng thuế điện tử.",
        "keywords": ["thuế", "khai thuế", "hoàn thuế", "mã số thuế"]
    },
    "bhxh": {
        "answer": "Thủ tục BHXH gồm: 1) Đăng ký tham gia BHXH, BHYT; 2) Cấp thẻ BHYT; 3) Hưởng chế độ thai sản, ốm đau, hưu trí. Nộp tại Bảo hiểm xã hội quận/huyện.",
        "keywords": ["bảo hiểm", "bhxh", "bhyt", "thẻ bhyt", "hưu trí"]
    },
    "giấy phép lái xe": {
        "answer": "Hồ sơ thi GPLX: 1) Đơn đề nghị; 2) CMND/CCCD; 3) Giấy khám sức khỏe; 4) Ảnh 3x4. Thi tại Sở Giao thông Vận tải. GPLX hạng A1, A2: 550.000đ; B1, B2: 135.000đ.",
        "keywords": ["lái xe", "gplx", "bằng lái", "thi bằng"]
    },
    "xây dựng": {
        "answer": "Giấy phép xây dựng: Hồ sơ gồm đơn xin cấp phép, bản vẽ mặt bằng, thiết kế, cam kết đảm bảo an toàn. Thời gian: 15-30 ngày tùy loại công trình.",
        "keywords": ["xây dựng", "gpxd", "cấp phép", "xây nhà"]
    }
}

# Canned responses for common questions
CANNED_RESPONSES = {
    "xin chào": "Xin chào! Tôi là trợ lý AI của PC06 Tuyên Quang. Tôi có thể hỗ trợ bạn về các thủ tục hành chính. Bạn cần tìm hiểu về thủ tục gì?",
    "cảm ơn": "Cảm ơn bạn đã sử dụng dịch vụ! Nếu cần hỗ trợ thêm, hãy liên hệ PC06 Tuyên Quang.",
    "help": "Tôi có thể giúp bạn về các thủ tục hành chính như: cấp giấy giới thiệu, đăng ký thường trú/tạm trú, lý lịch tư pháp, hộ chiếu, đăng ký kinh doanh, thuế, BHXH, GPLX, xây dựng...",
    "liên hệ": "Bạn có thể liên hệ PC06 Tuyên Quang qua: Địa chỉ: ..., Điện thoại: ..., Email: ...",
    "giờ làm việc": "PC06 Tuyên Quang làm việc từ thứ 2 đến thứ 6, sáng từ 7h30 - 11h30, chiều từ 13h00 - 17h00."
}


def call_openai_api(prompt):
    """Gọi OpenAI API để lấy câu trả lời"""
    if not OPENAI_API_KEY:
        return None
    
    try:
        headers = {
            'Authorization': f'Bearer {OPENAI_API_KEY}',
            'Content-Type': 'application/json',
            'OpenAI-Organization': OPENAI_ORG_ID
        }
        
        # System prompt hướng dẫn AI
        system_prompt = """Bạn là trợ lý AI của PC06 Tuyên Quang, chuyên hỗ trợ về các thủ tục hành chính.
Hãy trả lời bằng tiếng Việt, ngắn gọn và dễ hiểu.
Nếu không biết câu trả lời, hãy nói ra và gợi ý người dùng liên hệ trực tiếp cơ quan chức năng."""
        
        data = {
            'model': 'gpt-3.5-turbo',
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': prompt}
            ],
            'max_tokens': 500,
            'temperature': 0.7
        }
        
        response = requests.post(
            'https://api.openai.com/v1/chat/completions',
            headers=headers,
            json=data,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content']
    
    except Exception as e:
        print(f"OpenAI API error: {e}")
        try:
            print(f"Response: {response.text}")
        except:
            pass
    
    return None


def find_answer_from_kb(query):
    """Tìm câu trả lời phù hợp từ knowledge base"""
    query_lower = query.lower()
    
    # Check canned responses first
    for key, response in CANNED_RESPONSES.items():
        if key in query_lower:
            return response
    
    # Check TTHC knowledge base
    for topic, data in TTHC_KNOWLEDGE.items():
        if topic in query_lower:
            return data["answer"]
        
        # Check keywords
        for keyword in data["keywords"]:
            if keyword in query_lower:
                return data["answer"]
    
    return None


def fetch_gov_news(limit=10):
    """Fetch latest news from tuyenquang.gov.vn with proper encoding"""
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
            # Try to detect encoding
            try:
                # Thử UTF-8 trước
                html = response.content.decode('utf-8')
            except:
                try:
                    # Thử ISO-8859-1
                    html = response.content.decode('iso-8859-1')
                except:
                    # Mặc định
                    html = response.text
            
            # Simple regex to find links with titles - cải thiện pattern
            link_pattern = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]+)</a>', re.IGNORECASE)
            
            for match in link_pattern.finditer(html):
                href = match.group(1)
                title = match.group(2).strip()
                
                # Filter: only valid titles with Vietnamese characters
                if title and len(title) > 15 and len(title) < 200:
                    # Clean HTML tags
                    title = re.sub(r'<[^>]+>', '', title).strip()
                    # Decode HTML entities
                    title = title.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
                    
                    if title and not href.startswith('http'):
                        full_url = href if href.startswith('http') else url + href
                        
                        articles.append({
                            'title': title,
                            'link': full_url,
                            'source': 'tuyenquang.gov.vn',
                            'date': ''
                        })
                        
                        if len(articles) >= limit:
                            break
                    
    except Exception as e:
        print(f"Error fetching news: {e}")
    
    # Return demo data if fetch fails
    if not articles:
        articles = [
            {'title': 'PC06 Tuyen Quang trien khai nhiem vu cong tac nam 2026', 'link': 'https://tuyenquang.gov.vn', 'source': 'tuyenquang.gov.vn', 'date': '22/04/2026'},
            {'title': 'Huong dan thu tuc hanh chinh moi nhat', 'link': 'https://tuyenquang.gov.vn', 'source': 'tuyenquang.gov.vn', 'date': '21/04/2026'},
            {'title': 'Cong bo quyet dinh dieu dong can bo', 'link': 'https://tuyenquang.gov.vn', 'source': 'tuyenquang.gov.vn', 'date': '20/04/2026'},
        ]
    
    return articles


@ai_bp.route('/')
def index():
    """AI Assistant main page"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
    
    news = fetch_gov_news(10)
    
    return render_template('ai_assistant.html', 
                         title='Trợ lý AI - TTHC',
                         news=news)


@ai_bp.route('/chat', methods=['POST'])
def chat():
    """Handle AI chat request - ưu tiên OpenAI API"""
    if not session.get('uid'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    query = data.get('message', '').strip()
    
    if not query:
        return jsonify({'error': 'Vui lòng nhập câu hỏi'}), 400
    
    # Thử OpenAI API trước
    ai_answer = call_openai_api(query)
    
    if ai_answer:
        return jsonify({
            'success': True,
            'answer': ai_answer,
            'type': 'ai'
        })
    
    # Fallback to knowledge base
    answer = find_answer_from_kb(query)
    
    if answer:
        return jsonify({
            'success': True,
            'answer': answer,
            'type': 'kb'
        })
    else:
        suggestions = list(TTHC_KNOWLEDGE.keys())[:5]
        return jsonify({
            'success': False,
            'answer': "Xin lỗi, tôi chưa có thông tin về vấn đề này. Bạn có thể hỏi về: " + ", ".join(suggestions),
            'type': 'no_match',
            'suggestions': suggestions
        })


@ai_bp.route('/news')
def news():
    """Get latest news from government website"""
    if not session.get('uid'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    limit = request.args.get('limit', 10, type=int)
    articles = fetch_gov_news(limit)
    
    return jsonify({
        'success': True,
        'articles': articles
    })
