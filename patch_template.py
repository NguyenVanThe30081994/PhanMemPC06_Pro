with open("templates/task_detail.html", "r") as f:
    content = f.read()

assignees_block = """        <!-- 4. Assignments -->
        <div class="card border-0 shadow-sm rounded-4 p-4">"""

new_assignees_block = """        <!-- 4. Assignments -->
        {% if is_lead %}
        <div class="card border-0 shadow-sm rounded-4 p-4">"""

content = content.replace(assignees_block, new_assignees_block)

end_assignees_block = """                {% endfor %}
            </div>
        </div>
    </div>
</div>"""

new_end_assignees_block = """                {% endfor %}
            </div>
        </div>
        {% endif %}
    </div>
</div>"""
content = content.replace(end_assignees_block, new_end_assignees_block)

with open("templates/task_detail.html", "w") as f:
    f.write(content)
