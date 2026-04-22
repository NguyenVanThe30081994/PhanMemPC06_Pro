"""
Zalo OA Reminder Scheduler
- Automatically checks tasks and sends ZNS reminders
- Uses APScheduler for development
- Can also be run via cPanel Cron
"""
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import date, timedelta
from flask import current_app


# Global scheduler instance
scheduler = BackgroundScheduler()


def init_scheduler(app):
    """Initialize scheduler with Flask app"""
    scheduler.init_app(app)
    scheduler.start()


def check_and_send_reminders():
    """
    Main job: Check tasks and send reminders
    Runs via APScheduler - needs app context
    """
    with current_app.app_context():
        _process_deadline_warnings()
        _process_overdue_tasks()


def _process_deadline_warnings():
    """Send reminder for tasks deadline within 2 days"""
    from models import db, Task, TaskAssignment, User, ZaloConfig
    from zalo_service import ZaloOAService
    
    config = ZaloConfig.query.first()
    if not config or not config.is_active or not config.template_deadline_warning:
        return
    
    # Tasks deadline within 2 days
    tomorrow = date.today() + timedelta(days=2)
    upcoming_tasks = Task.query.filter(
        Task.deadline != None,
        Task.deadline >= date.today(),
        Task.deadline <= tomorrow
    ).all()
    
    service = ZaloOAService(config)
    
    for task in upcoming_tasks:
        for assignment in task.assignments:
            if assignment.status == 'Hoàn thành':
                continue
            
            user = db.session.get(User, assignment.user_id)
            if not user or not user.phone:
                continue
            
            template_data = {
                'ten_can_bo': user.fullname or user.username,
                'ten_nhiem_vu': task.title,
                'ngay_giao': task.created_at.strftime('%d/%m/%Y'),
                'ngay_deadline': task.deadline.strftime('%d/%m/%Y'),
                'muc_uu_tien': task.priority or 'Bình thường',
                'link_nhiem_vu': f"https://domain.com/tasks/{task.id}"
            }
            
            service.send_zns(
                db.session,
                phone=user.phone,
                template_id=config.template_deadline_warning,
                template_data=template_data,
                template_type='deadline_warning'
            )


def _process_overdue_tasks():
    """Send alert for overdue tasks"""
    from models import db, Task, TaskAssignment, User, ZaloConfig
    from zalo_service import ZaloOAService
    
    config = ZaloConfig.query.first()
    if not config or not config.is_active or not config.template_overdue:
        return
    
    # Overdue tasks
    today = date.today()
    overdue_tasks = Task.query.filter(
        Task.deadline != None,
        Task.deadline < today
    ).all()
    
    service = ZaloOAService(config)
    
    for task in overdue_tasks:
        for assignment in task.assignments:
            if assignment.status == 'Hoàn thành':
                continue
            
            user = db.session.get(User, assignment.user_id)
            if not user or not user.phone:
                continue
            
            days_overdue = (today - task.deadline).days
            
            template_data = {
                'ten_can_bo': user.fullname or user.username,
                'ten_nhiem_vu': task.title,
                'so_ngay_qua_han': days_overdue,
                'ngay_deadline': task.deadline.strftime('%d/%m/%Y'),
                'nguoi_giao': task.author_name or 'Admin',
                'link_nhiem_vu': f"https://domain.com/tasks/{task.id}"
            }
            
            service.send_zns(
                db.session,
                phone=user.phone,
                template_id=config.template_overdue,
                template_data=template_data,
                template_type='overdue'
            )


# ==================== CRON VERSION ====================
# For cPanel cron, use this simpler script

def run_cron():
    """
    Simple cron runner - no Flask app context needed
    Usage: Set up cron job in cPanel to run this script
    """
    import sys
    import os
    
    # Setup path - adjust to your project
    project_path = os.path.dirname(os.path.abspath(__file__))
    if project_path not in sys.path:
        sys.path.insert(0, project_path)
    
    from app import app, db
    from models import Task, TaskAssignment, User, ZaloConfig
    
    with app.app_context():
        config = ZaloConfig.query.first()
        if not config or not config.is_active:
            print("Zalo not configured - skipping")
            return
        
        from zalo_service import ZaloOAService
        service = ZaloOAService(config)
        
        # Process overdue
        today = date.today()
        overdue = Task.query.filter(
            Task.deadline != None,
            Task.deadline < today
        ).all()
        
        count = 0
        for task in overdue:
            for assignment in task.assignments:
                if assignment.status == 'Hoàn thành':
                    continue
                user = db.session.get(User, assignment.user_id)
                if not user or not user.phone:
                    continue
                
                days_overdue = (today - task.deadline).days
                result = service.send_zns(
                    db.session,
                    phone=user.phone,
                    template_id=config.template_overdue,
                    template_data={
                        'ten_can_bo': user.fullname or user.username,
                        'ten_nhiem_vu': task.title,
                        'so_ngay_qua_han': days_overdue,
                        'ngay_deadline': task.deadline.strftime('%d/%m/%Y'),
                        'nguoi_giao': task.author_name or 'Admin',
                        'link_nhiem_vu': f"https://domain.com/tasks/{task.id}"
                    },
                    template_type='overdue'
                )
                count += 1
        
        print(f"Sent {count} overdue reminders")


if __name__ == '__main__':
    run_cron()
