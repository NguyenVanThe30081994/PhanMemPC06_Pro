import re

with open('templates/reporting_cycle_detail.html', 'r') as f:
    content = f.read()

replacement = """                    <div class="col-6">
                        <div class="p-3 bg-light rounded-3 h-100">
                            <div class="small text-muted">{{ 'Đúng ngày' if is_daily else 'Trong hạn' }}</div>
                            <div class="fw-bold fs-5">{{ on_time_total }}</div>
                        </div>
                    </div>
                    <div class="col-6">
                        <div class="p-3 bg-light rounded-3 h-100">
                            <div class="small text-muted">{{ 'Quá ngày' if is_daily else 'Quá hạn' }}</div>
                            <div class="fw-bold fs-5">{{ late_total }}</div>
                        </div>
                    </div>"""

pattern = r"""                    <div class="col-6">\s*<div class="p-3 bg-light rounded-3 h-100">\s*<div class="small text-muted">Trong hạn</div>\s*<div class="fw-bold fs-5">{{ on_time_total }}</div>\s*</div>\s*</div>\s*<div class="col-6">\s*<div class="p-3 bg-light rounded-3 h-100">\s*<div class="small text-muted">Quá hạn</div>\s*<div class="fw-bold fs-5">{{ late_total }}</div>\s*</div>\s*</div>"""

new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)

with open('templates/reporting_cycle_detail.html', 'w') as f:
    f.write(new_content)

