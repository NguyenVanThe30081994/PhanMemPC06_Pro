-- Tạo công việc giao cho "Đội nghiệp vụ 1"
INSERT INTO task (domain, title, content, deadline, author_id, author_name, priority, task_type, initial_status, created_at)
VALUES (
    'Đội nghiệp vụ 1',
    'Báo cáo tình hình công tác tháng 4/2026',
    'Yêu cầu đơn vị báo cáo tình hình công tác trong tháng 4/2026. Nội dung bao gồm: kết quả đạt được, khó khăn vướng mắc, đề xuất giải pháp.',
    '2026-05-05',
    1,
    'Tài khoản quản trị',
    'Cao',
    'Báo cáo định kỳ',
    'Chưa tiếp nhận',
    datetime('now')
);

-- Lấy task_id vừa tạo
SELECT 'TASK CREATED:' as info;
SELECT id, title, domain FROM task WHERE title LIKE '%Báo cáo tình hình%';

-- Tạo TaskAssignment cho tất cả user thuộc "Đội nghiệp vụ 1"
INSERT INTO task_assignment (task_id, user_id, status, updated_at)
SELECT 
    (SELECT id FROM task WHERE title LIKE '%Báo cáo tình hình%' LIMIT 1),
    u.id,
    'Chưa tiếp nhận',
    datetime('now')
FROM user u
WHERE u.unit_area = 'Đội nghiệp vụ 1' AND u.is_active = 1;

-- Kiểm tra assignments đã tạo
SELECT '' as blank;
SELECT 'ASSIGNMENTS CREATED:' as info;
SELECT ta.id, u.fullname, u.unit_area, ta.status, t.title
FROM task_assignment ta
JOIN user u ON ta.user_id = u.id
JOIN task t ON ta.task_id = t.id
WHERE t.title LIKE '%Báo cáo tình hình%';
