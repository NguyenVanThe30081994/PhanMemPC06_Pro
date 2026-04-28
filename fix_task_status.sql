-- Cập nhật trạng thái công việc từ 'Chưa bắt đầu' sang 'Chưa tiếp nhận'

-- Cập nhật bảng Task
UPDATE task 
SET initial_status = 'Chưa tiếp nhận' 
WHERE initial_status = 'Chưa bắt đầu' OR initial_status IS NULL;

-- Cập nhật bảng TaskAssignment
UPDATE task_assignment 
SET status = 'Chưa tiếp nhận' 
WHERE status = 'Chưa bắt đầu' OR status IS NULL;

-- Kiểm tra kết quả
SELECT 'Tasks updated:', COUNT(*) FROM task WHERE initial_status = 'Chưa tiếp nhận';
SELECT 'Assignments updated:', COUNT(*) FROM task_assignment WHERE status = 'Chưa tiếp nhận';
