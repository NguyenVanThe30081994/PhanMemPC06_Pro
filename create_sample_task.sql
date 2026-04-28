-- Tạo công việc mẫu để test chức năng tiếp nhận
INSERT INTO task (domain, title, content, deadline, author_id, author_name, priority, task_type, initial_status, created_at)
VALUES (
    'Đội nghiệp vụ 1',
    'Công việc test - Kiểm tra nút tiếp nhận',
    'Đây là công việc mẫu để kiểm tra chức năng tiếp nhận công việc của các đơn vị được giao việc. Vui lòng vào trang công việc và nhấn nút TIẾP NHẬN CÔNG VIỆC.',
    '2026-05-15',
    1,
    'Tài khoản quản trị',
    'Cao',
    'Công việc thường xuyên',
    'Chưa tiếp nhận',
    datetime('now')
);

-- Giao công việc cho user ID 1
INSERT INTO task_assignment (task_id, user_id, status, updated_at)
VALUES (
    (SELECT id FROM task WHERE title = 'Công việc test - Kiểm tra nút tiếp nhận'),
    1,
    'Chưa tiếp nhận',
    datetime('now')
);

-- Kiểm tra kết quả
SELECT 'TASK CREATED:' as result;
SELECT id, title, domain, initial_status FROM task WHERE title LIKE '%test%';

SELECT '' as blank;
SELECT 'ASSIGNMENT CREATED:' as result;
SELECT ta.id, ta.task_id, ta.user_id, ta.status, u.fullname 
FROM task_assignment ta 
LEFT JOIN user u ON ta.user_id = u.id;
