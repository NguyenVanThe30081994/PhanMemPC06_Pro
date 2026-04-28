-- Xóa dữ liệu test cũ
DELETE FROM task_assignment WHERE task_id IN (SELECT id FROM task WHERE title LIKE '%test%');
DELETE FROM task WHERE title LIKE '%test%';

-- Tạo thêm users thuộc các đơn vị khác nhau để test
INSERT OR IGNORE INTO user (username, password_hash, fullname, role_id, unit_area, is_active, must_change_password)
VALUES 
('user_dv1', 'pbkdf2:sha256:600000$test$test', 'Nguyễn Văn A', 2, 'Đội nghiệp vụ 1', 1, 0),
('user_dv2', 'pbkdf2:sha256:600000$test$test', 'Trần Thị B', 2, 'Đội nghiệp vụ 1', 1, 0),
('user_dv3', 'pbkdf2:sha256:600000$test$test', 'Lê Văn C', 2, 'Đội nghiệp vụ 2', 1, 0);

-- Kiểm tra users đã tạo
SELECT 'USERS BY UNIT:' as info;
SELECT id, fullname, unit_area FROM user WHERE is_active = 1 ORDER BY unit_area;
