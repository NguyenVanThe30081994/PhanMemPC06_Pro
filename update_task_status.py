#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script để cập nhật trạng thái công việc cũ từ 'Chưa bắt đầu' sang 'Chưa tiếp nhận'
"""

from app import app, db
from models import Task, TaskAssignment

def update_old_task_statuses():
    with app.app_context():
        # Cập nhật Task.initial_status
        tasks_updated = Task.query.filter(
            (Task.initial_status == 'Chưa bắt đầu') | 
            (Task.initial_status == None)
        ).update({Task.initial_status: 'Chưa tiếp nhận'})
        
        # Cập nhật TaskAssignment.status
        assignments_updated = TaskAssignment.query.filter(
            (TaskAssignment.status == 'Chưa bắt đầu') | 
            (TaskAssignment.status == None)
        ).update({TaskAssignment.status: 'Chưa tiếp nhận'})
        
        db.session.commit()
        
        print(f"✅ Đã cập nhật {tasks_updated} công việc")
        print(f"✅ Đã cập nhật {assignments_updated} phân công")
        print("✅ Hoàn tất!")

if __name__ == '__main__':
    update_old_task_statuses()
