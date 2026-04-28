with open("templates/task_detail.html", "r") as f:
    content = f.read()

comments_block = """        <!-- 2. Comments Section -->"""
new_comments_block = """
        {% if not is_lead %}
        <!-- Task Acceptance and Report Section for Assignees -->
        <div class="card border-0 shadow-sm rounded-4 mb-4" style="background-color: var(--bg-surface);">
            <div class="card-header border-bottom p-4" style="background-color: var(--bg-surface); border-color: var(--border) !important;">
                <h5 class="fw-bold text-main mb-0"><i class="fa-solid fa-clipboard-check me-2 text-primary"></i>Cập nhật Trạng thái & Báo cáo</h5>
            </div>
            <div class="card-body p-4">
                {% set user_assign = None %}
                {% for a, u in assigns %}
                    {% if a.user_id == session['uid'] %}
                        {% set user_assign = a %}
                    {% endif %}
                {% endfor %}
                
                {% if user_assign %}
                    <div class="d-flex align-items-center mb-4">
                        <span class="me-3 fw-bold">Trạng thái của bạn:</span>
                        <span class="badge {% if user_assign.status == 'Chưa tiếp nhận' %}bg-secondary{% elif user_assign.status == 'Đang thực hiện' %}bg-info{% elif user_assign.status == 'Hoàn thành' %}bg-success{% else %}bg-warning{% endif %} rounded-pill px-3 py-2">
                            {{ user_assign.status }}
                        </span>
                        
                        {% if user_assign.status == 'Chưa tiếp nhận' or user_assign.status == 'Chưa bắt đầu' %}
                        <form action="{{ url_for('tasks_bp.update_task_status', tid=task.id) }}" method="POST" class="ms-3 m-0">
                            <input type="hidden" name="action" value="accept">
                            <button type="submit" class="btn btn-sm btn-primary rounded-pill px-3 fw-bold">Tiếp nhận công việc</button>
                        </form>
                        {% endif %}
                    </div>
                    
                    {% if user_assign.status != 'Chưa tiếp nhận' and user_assign.status != 'Chưa bắt đầu' %}
                    <form action="{{ url_for('tasks_bp.submit_task_report', tid=task.id) }}" method="POST" enctype="multipart/form-data">
                        <div class="mb-3">
                            <label class="form-label fw-bold small text-muted">Báo cáo tiến độ / Kết quả</label>
                            <textarea name="report_content" class="form-control rounded-3" rows="3" placeholder="Nhập nội dung báo cáo tóm tắt..." required></textarea>
                        </div>
                        <div class="mb-3">
                            <label class="form-label fw-bold small text-muted">Tệp đính kèm (nếu có)</label>
                            <input type="file" name="report_file" class="form-control rounded-3">
                        </div>
                        <div class="d-flex justify-content-between align-items-center">
                            <div class="form-check">
                                <input class="form-check-input" type="checkbox" name="mark_completed" value="1" id="markCompleted">
                                <label class="form-check-label fw-bold text-success" for="markCompleted">
                                    Đánh dấu Hoàn thành
                                </label>
                            </div>
                            <button type="submit" class="btn btn-success rounded-pill px-4 fw-bold shadow-sm">Gửi Báo Cáo</button>
                        </div>
                    </form>
                    {% endif %}
                {% endif %}
            </div>
        </div>
        {% endif %}

        <!-- 2. Comments Section -->"""

content = content.replace(comments_block, new_comments_block)

with open("templates/task_detail.html", "w") as f:
    f.write(content)
