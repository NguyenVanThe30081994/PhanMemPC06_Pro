with open("templates/tasks.html", "r") as f:
    content = f.read()

content = content.replace("t.initial_status or 'Chưa bắt đầu'", "t.initial_status or 'Chưa tiếp nhận'")

with open("templates/tasks.html", "w") as f:
    f.write(content)
