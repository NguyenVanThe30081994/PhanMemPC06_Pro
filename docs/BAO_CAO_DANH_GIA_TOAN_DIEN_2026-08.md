# BÁO CÁO ĐÁNH GIÁ TOÀN DIỆN MÃ NGUỒN PhanMemPC06_Pro

**Ngày:** 14/08/2026
**Phiên bản hệ thống:** 3.5.0 (`config.py:95`)
**Phương pháp:** đọc trực tiếp mã nguồn, đối chiếu tài liệu nội bộ (`docs/`, `THIET_KE_CHUC_NANG_TASK_CUOI.md`, `CHANGELOG.md`), thống kê bằng grep/wc.
**Mục tiêu:** chỉ ra điểm cần cải thiện về **tính năng** và đề xuất **giải pháp + lộ trình**.

---

## 1. TÓM TẮT ĐIỀU HÀNH

| Nhóm | Đánh giá | Mức rủi ro nếu không xử lý |
|------|----------|---------------------------|
| Bảo mật nền tảng | ✅ Tốt hơn mặt bằng chung (CSRF, headers, lockout, re-auth, phân quyền chuẩn hóa) | — |
| Bảo mật tính năng | ⚠️ Có 3 điểm hở cần vá sớm (API vệ tinh public, `db.create_all` trong route, CI không chạy test) | 🔴 Cao |
| Tính năng vận hành | ⚠️ Thiếu cảnh báo hạn tự động, thông báo chỉ trong app, chế độ FORM chưa hoàn tất | 🟠 Trung bình |
| Kiến trúc & bảo trì | ⚠️ File route 11.213 dòng, utils 55 hàm lẫn lộn, migration tự viết | 🔴 Cao (chi phí bảo trì tăng dần) |
| Hiệu năng | ⚠️ Thiếu index, tác vụ nặng chạy đồng bộ trong request | 🟠 Trung bình |
| Quy trình CI/CD | ⚠️ Deploy FTP không qua bước test | 🟠 Trung bình |

**Kết luận một câu:** nền móng bảo mật và mô hình dữ liệu task đã tốt; điểm nghẽn lớn nhất là **tính năng vận hành tự động (nhắc hạn, thông báo đa kênh)** và **khả năng bảo trì do file quá lớn**. Cả hai đều có lộ trình xử lý cuốn chiếu, không cần viết lại hệ thống.

**Số liệu khảo sát:** 26 file Python gốc + 11 file routes (~17.000 dòng routes), 37 model SQLAlchemy (`models.py`), 37 template (~23.600 dòng), 205 test trong 26 file test, 9 blueprint.

---

## 2. ĐIỂM MẠNH CẦN GHI NHẬN VÀ GIỮ LẠI

1. **Bảo mật nền tảng có đầu tư** — hiếm thấy ở dự án cùng quy mô:
   - CSRF token toàn cục + kiểm tra Origin/Referer + `compare_digest` (`app.py:528-556`)
   - Security headers đầy đủ: CSP, HSTS, X-Frame-Options, Permissions-Policy, COOP/CORP (`app.py:301-340`)
   - Rate-limit sliding window theo IP × endpoint, ngưỡng riêng cho `/api/` (`app.py:347`)
   - Khóa đăng nhập lũy tiến theo lịch tăng dần, áp cả username lẫn IP, collapse mật khẩu lặp lại (`routes/auth.py:209-327`), delay chống brute-force (`AUTH_FAILURE_DELAY_MS`)
   - Thiết bị tin cậy + cảnh báo đăng nhập từ thiết bị lạ (`routes/auth.py:126-176`), re-auth cho thao tác nhạy cảm (`/reauth`), session binding theo IP/UA/session_version
   - Mật khẩu pbkdf2:sha256 (`models.py:227`), chính sách mật khẩu mạnh, bắt buộc đổi mật khẩu lần đầu
2. **Phân quyền bài bản:** vai trò chính + vai trò phụ theo đơn vị (`UserRole`), ủy quyền tạm thời (`Delegation`), cây đơn vị cho data-scope (`Unit`), nhật ký phân quyền riêng (`PermissionLog`), chuẩn hóa `view/process/exec` theo `docs/ma-tran-quyen-chuan-2026.md`.
3. **Mô hình dữ liệu task đã tái cấu trúc đúng hướng:** `Task → TaskItem → TaskAssignment/TaskParticipant → TaskSubmission` với 3 hình thái OUTLINE/FILE/FORM (`models.py:269-472`, thiết kế tại `THIET_KE_CHUC_NANG_TASK_CUOI.md`) — khớp mô hình các phần mềm giao việc hiện đại.
4. **Tích hợp phong phú:** Google Forms sync (`google_forms.py`), Google OAuth (`routes/google_auth.py`), parse đề cương Word/TXT (`outline_parser.py`), xuất Word tổng hợp + Excel, đề xuất gán việc bằng scoring (`task_import_ai.py`), rút gọn link + QR (`routes/shortlink.py`), bản đồ vệ tinh, danh bạ import Excel.
5. **Có bộ test nghiêm túc:** 205 test phủ auth security, task runtime, google forms, policies, workspace… (`tests/`).
6. **Tài liệu nội bộ tốt:** đề án cải tổ kiến trúc, lộ trình triển khai, tổng rà soát đơn giản hóa (`docs/`) — báo cáo này kế thừa và nối tiếp các tài liệu đó, không đề xuất hướng đi mâu thuẫn.

---

## 3. CÁC ĐIỂM CẦN CẢI THIỆN VỀ TÍNH NĂNG (trọng tâm theo yêu cầu)

### 3.1. Chưa có nhắc hạn / cảnh báo quá hạn tự động — điểm nghẽn vận hành lớn nhất
**Hiện trạng:** Hệ thống có deadline, trạng thái, luồng "trả lại bổ sung", nhưng việc theo dõi hạn hoàn toàn thủ công: người dùng phải tự mở trang task để biết sắp đến hạn. `APScheduler` đã khai báo trong `requirements.txt` nhưng **không có dòng code nào sử dụng** (grep toàn repo không thấy). Trường `User.phone` chú thích "SĐT Zalo format E.164" (`models.py:222`) nhưng không có mã tích hợp Zalo nào.
**Hệ quả:** Công việc quá hạn chỉ bị phát hiện khi lãnh đạo hỏi; phần mềm chưa làm tròn vai "điều hành".
**Giải pháp đề xuất:**
- Thêm module `deadline_watchdog.py` chạy bằng APScheduler (dependency đã có): quét `Task.deadline` + `TaskAssignment.status` theo lịch (vd mỗi giờ) → sinh `Notification` qua `push_notif`/`push_global_notif` sẵn có (`utils.py:743, 776`), ngưỡng cấu hình qua `.env` (sớm 3 ngày / 1 ngày / quá hạn, nhắc lại theo chu kỳ).
- Cần cơ chế dedupe (vd lưu mốc nhắc cuối vào bảng mới `task_reminder_state` hoặc `TaskSubmission.cycle_key`-style) để không spam thông báo.
- Dashboard "Việc sắp/quá hạn" cho lãnh đạo: thống kê đơn vị × trạng thái × hạn, tái sử dụng ma trận tiến độ `đầu mục × đơn vị` đã có ở chế độ OUTLINE.
- Giai đoạn 2: Zalo OA push (dữ liệu phone đã sẵn), gửi khi: giao việc mới, sắp đến hạn, bị trả lại.

### 3.2. Chế độ FORM (thu thập số liệu) mới dừng ở khung dữ liệu
**Hiện trạng:** Thiết kế chốt (`THIET_KE_CHUC_NANG_TASK_CUOI.md` §4.3) ghi rõ FORM là giai đoạn 2, "giữ sẵn mô hình trong thiết kế, chưa đưa vào đợt refactor đầu tiên". Lưới nhập bảng đã có (CHANGELOG 2026-08-04), `TaskFormField`/`TaskSubmission.numeric_value` đã tồn tại, nhưng thiếu: tổng hợp số liệu tự động, xác thực dữ liệu, khóa sổ theo chu kỳ.
**Giải pháp đề xuất:**
- Tổng hợp submission dạng số thành bảng pivot `đơn vị × chỉ tiêu`, xuất Excel (openpyxl đã có trong requirements).
- Xác thực theo `TaskFormField.field_type` (số/ngày/lựa chọn), bắt buộc theo `is_required`.
- Khóa sổ theo chu kỳ: tận dụng `report_cycles.py` (đã có `normalize_config`, `parse_config`, logic chu kỳ tuần/tháng) thay vì viết mới.

### 3.3. Thông báo chỉ có một kênh (trong app)
**Hiện trạng:** `push_notif`/`push_global_notif` (`utils.py:743, 776`) chỉ ghi bảng `Notification`. File `routes/email_service.py` tồn tại (SMTP qua smtplib, đọc config `MAIL_*`) nhưng **không được đăng ký hay gọi ở bất kỳ đâu** — không có trong `register_blueprint` (`app.py:396-404`), không module nào import. `.env.example` đã có sẵn khối cấu hình `MAIL_*`.
**Giải pháp đề xuất:**
- Chuyển `routes/email_service.py` thành service module (vd `services/email_notifier.py`) — đặt nhầm trong `routes/` gây hiểu nhầm là có route.
- Móc vào `push_notif` làm kênh thứ hai (gửi khi cấu hình MAIL_SERVER tồn tại, fail-safe không chặn luồng chính). Sự kiện ưu tiên: giao việc mới, trả lại bổ sung, sắp/quá hạn.

### 3.4. "Trợ lý AI" đang là heuristic — cấu hình LLM trong `.env` là cấu hình chết
**Hiện trạng:** `task_import_ai.py` (107KB) là engine scoring nội bộ (token overlap, lịch sử giao việc, tải công việc) — chạy tốt, không tốn phí. Nhưng `.env.example` khai báo `AI_ASSISTANT_PROVIDER=deepseek`, `DEEPSEEK_API_KEY` trong khi **toàn repo không có mã gọi LLM nào**.
**Giải pháp đề xuất (chọn 1 trong 2):**
- (a) Nếu có kế hoạch dùng LLM: bọc sau interface đề xuất hiện có (`_suggest_assignment`, `_assignment_alternatives` trong `task_import_ai.py`) — provider đọc từ env, fallback về engine hiện tại khi không cấu hình. Ứng dụng tốt nhất: gợi ý gán việc từ đề cương và tóm tắt văn bản đến.
- (b) Nếu chưa làm: **dọn khối `AI_ASSISTANT_*`/`DEEPSEEK_*` khỏi `.env.example`** để không gây hiểu nhầm cho người triển khai.

### 3.5. Thiếu tìm kiếm toàn cục và báo cáo định kỳ
**Hiện trạng:** Tìm kiếm phân tán theo từng màn hình; chưa có báo cáo tuần/tháng tổng hợp cho lãnh đạo.
**Giải pháp đề xuất:**
- Endpoint tìm kiếm toàn cục (task / văn bản thư viện / danh bạ / bản tin), lọc không dấu bằng `remove_accents` sẵn có (`utils.py:56`).
- Báo cáo định kỳ xuất Excel: tổng hợp theo đơn vị × trạng thái × khoảng thời gian; có thể gắn vào chính lịch APScheduler của mục 3.1.

### 3.6. Tính năng hệ thống cập nhật qua web (git pull / reset DB) — nên cân nhắc thu hẹp
**Hiện trạng:** Admin có thể git-pull, reset DB, backup DB từ trình duyệt (`routes/admin.py:1360-1549`), đã chặn mặc định bằng cờ env (`WEB_GIT_PULL_ENABLED`, `ADMIN_DB_RESET_ENABLED` — `config.py:84-87`). Đây là bề mặt tấn công lớn nếu cờ bị bật nhầm trên production.
**Giải pháp đề xuất:** giữ cờ off mặc định (đã đúng), thêm bước re-auth bắt buộc + xác nhận gõ tên hệ thống trước các thao tác này, log vào `PermissionLog`.

---

## 4. VẤN ĐỀ BẢO MẬT CẦN XỬ LÝ SỚM

| # | Phát hiện | Bằng chứng | Giải pháp | Ưu tiên |
|---|-----------|------------|-----------|---------|
| B1 | **API vệ tinh cho phép GHI/XÓA DB không cần đăng nhập**: `save_custom_satellite_point`, `delete_custom_satellite_point`, `get_custom_satellite_points`, `resolve_maps_url` nằm trong `public_endpoints` của `check_auth` | `app.py` (khối `public_endpoints` trong `check_auth`), `routes/api.py:269, 299, 349, 439` | Đưa các endpoint ghi/xóa khỏi `public_endpoints`; yêu cầu session + quyền; nếu bản đồ phải public thì giới hạn quyền đọc cho GET, bắt CSRF token cho POST | **P0** |
| B2 | **`db.create_all()` gọi trong request handler** — đa luồng race, tự tạo bảng ngoài kiểm soát | `routes/api.py:302, 353` | Chuyển vào `init_db()` lúc khởi động (`app.py:378`) | **P0** |
| B3 | **Exception trả nguyên văn `str(e)` ra client** — lộ cấu trúc nội bộ (đường dẫn, SQL) | `routes/api.py:345, 374` và nhiều handler try/except tương tự | Trả thông báo chung + log chi tiết server-side | P1 |
| B4 | **CSP còn `'unsafe-inline' 'unsafe-eval'`** và 29 template chứa `<script>` inline, 7 chỗ dùng `|safe` | `app.py:317`, `templates/*.html` | Lộ trình tách JS ra `static/js` → bật nonce CSP (xem mục 5.E) | P1 |
| B5 | `.freebuff/desktop-v2.db` (+ shm/wal) **đang được commit vào git** | `git ls-files` | Rà nội dung nhạy cảm, thêm `.freebuff/` vào `.gitignore`, cân nhắc xóa khỏi lịch sử nếu chứa dữ liệu thật | P1 |
| B6 | Rate-limit chỉ in-memory: mất khi restart, không chia sẻ giữa các worker Passenger; `/login` bị loại khỏi rate-limit (chỉ dựa lockout DB) | `app.py` (`rate_limit_store`) | Chấp nhận có ghi chú, hoặc chuyển trạng thái lockout (đã có trong DB) làm nguồn duy nhất; cân nhắc thêm mốc IP cho login | P2 |
| B7 | Helper `check_csrf_token` trong `utils.py:15` so sánh `==` thường (app.py đã dùng `compare_digest` đúng) — tránh dùng nhầm | `utils.py:15-22` | Xóa hoặc chuyển sang `secrets.compare_digest` | P2 |
| B8 | Script nhạy cảm nằm ở root repo: `reset_admin.py`, `reset_user_password.py`, `Reset_Database.bat` | root | Di chuyển vào `scripts/` + ghi log thao tác + yêu cầu cờ xác nhận | P2 |

**Điểm cộng bảo mật cần nói rõ:** các cơ chế khóa đăng nhập, CSRF, headers, phân quyền, re-auth hiện tại đã **đầy đặn hơn đáng kể** so với chuẩn một ứng dụng Flask nội bộ — phần trên là vá các điểm hở cục bộ, không phải xây lại từ đầu.

---

## 5. VẤN ĐỀ KIẾN TRÚC & BẢO TRÌ

### 5.A. File quá lớn (rủi ro bảo trì số 1)
- `routes/tasks.py`: **11.213 dòng**, 140+ hàm, 31 route decorator — mọi hình thái OUTLINE/FILE/FORM/drafts/google-form/export đều dồn một chỗ.
- `utils.py`: 1.587 dòng, 55 hàm trộn 6 chủ đề (auth/CSRF, migration, permission, unit matching, Excel formatting, notification).
- `routes/admin.py`: 1.955 dòng; `task_import_ai.py`: ~107KB.

**Giải pháp:** tách `routes/tasks.py` thành package `routes/tasks/` theo miền — `drafts.py`, `outline.py`, `google_form.py`, `assignments.py`, `submissions.py`, `exports.py`, `views.py` — cùng blueprint `tasks_bp`, **giữ nguyên toàn bộ URL**. Logic nghiệp vụ chuyển vào `services/task_*`, kế thừa lớp đã tách sẵn (và đã có test): `task_policies.py`, `task_read_models.py`, `task_workspace.py`, `task_page_builders.py`. Chuyển hàm trong `utils.py` về đúng nhà: quyền → `permissions.py` (đã có), migration → module riêng, unit matching → `category_helpers.py` (đã có); giữ `utils.py` re-export để không gãy import. Mục tiêu: không file nào quá ~800 dòng.

### 5.B. Migration tự viết trong code ứng dụng
`apply_migrations` (`utils.py:384-697`, ~314 dòng ALTER TABLE/ADD COLUMN thủ công) + `migrate.py` + `_repair_task_item_fk_constraints` (`utils.py:309`). Không có versioning chuẩn, khó biết DB nào đã ở bước nào, rủi ro khi chạy trên MySQL production.
**Giải pháp:** đưa **Alembic** vào làm chuẩn (hỗ trợ cả SQLite/MySQL), baseline từ schema hiện tại; giữ `apply_migrations` làm lớp bootstrap một lần. Mọi thay đổi schema tiếp theo đi qua migration có đánh số — khớp nguyên tắc "không gãy host đang chạy" của `docs/lo-trinh-trien-khai-de-an-2026.md`.

### 5.C. Lạm dụng cột Text chứa JSON
Khoảng 14 cột `*_json` trên `Task`/`TaskItem`/`TaskSubmission` (`assignment_scope_json`, `viewer_scope_json`, `report_schema_json`, `report_period_json`…) — không query/index/thống kê được, chính `docs/de-an-cai-to-kien-truc-2026.md` đã thừa nhận ("Một số dữ liệu mở rộng vẫn nằm trong JSON nên khó kiểm soát quy tắc nghiệp vụ dài hạn").
**Giải pháp:** cuốn chiếu — cột nào cần lọc/thống kê (scope phân quyền, chu kỳ báo cáo) tách thành bảng quan hệ qua `migrate.py` backfill; giữ JSON cho cấu hình hiển thị thuần túy.

### 5.D. Model cũ mới tồn tại song song
`Category` được chú thích "Thay thế MasterData, LibraryField, ContactGroup, ProfessionalUnit, ContactRole" (`models.py:48-52`) nhưng các model cũ vẫn còn; `NewsDoc`/`DocumentLib` song song `NotificationDoc` ("gộp từ Bảng tin và Thư viện" — `models.py:513`); `Contact` cũ bên cạnh hệ đơn vị mới.
**Giải pháp:** kiểm đếm chỗ còn dùng (grep từng model), đặt cờ deprecated, xóa sau một chu kỳ chuyển đổi có test hồi quy.

### 5.E. Template khổng lồ, JS inline
`martyr_adn_map.html` 5.167 dòng, `tasks_rebuild.html` 3.434 dòng, `task_detail_rebuild.html` 2.559 dòng; 29/37 template nhúng `<script>` inline; nhiều cặp desktop/mobile trùng lặp logic (`base.html` 1.444 vs `base_mobile.html` 771; `roles`/`roles_mobile`, `contacts`/`contacts_mobile`…).
**Giải pháp:** chuyển JS inline ra `static/js/*.js` (cache được, gỡ dần `unsafe-inline` khỏi CSP — mục B4); ghép cặp desktop/mobile bằng Jinja macro + responsive CSS — đúng hướng `docs/tong-ra-soat-don-gian-hoa-2026.md` đã nêu.

### 5.F. Hiệu năng
- **Thiếu index trên cột truy vấn nóng:** `Task.deadline`, trạng thái task; `TaskAssignment(status)`; `Notification(user_id, is_read)`; `TaskSubmission(status)`. Hiện chỉ `task_id`/`user_id` là có index. → Thêm composite index `(status, deadline)`, `(task_id, status)`… qua migration.
- **Tác vụ nặng chạy đồng bộ trong request:** parse docx/pdf (`/tasks/outline-parse`), xuất Word/Excel, Google Forms sync — gây nghẽn worker Passenger khi file lớn. → Ngắn hạn: chuyển sync Google Forms sang APScheduler job; dài hạn: hàng đợi tác vụ (RQ/Celery) cho xuất file.

### 5.G. Quy trình CI/CD
`.github/workflows/deploy.yml` **chỉ checkout + FTP push thẳng lên host khi push `main` — 205 test không hề được chạy**. Deploy cũng có thể kích hoạt qua nút git-pull trong admin.
**Giải pháp:** thêm job test (`python -m unittest discover tests`) làm điều kiện bắt buộc trước bước FTP; cân nhắc thêm `ruff` lint. Đây là thay đổi rẻ nhất, lợi ích lớn nhất về an toàn vận hành.

---

## 6. LỘ TRÌNH ĐỀ XUẤT

Nguyên tắc: cuốn chiếu theo pha, mỗi pha chạy độc lập, không viết lại toàn bộ — nhất quán với `docs/lo-trinh-trien-khai-de-an-2026.md`.

### Pha 0 — An toàn ngay (1–2 ngày)
1. Chặn ghi/xóa API vệ tinh không đăng nhập (B1) + thêm test hồi quy.
2. Bỏ `db.create_all()` trong route, chuyển về khởi động (B2).
3. Sửa trả lỗi `str(e)` ra client (B3).
4. Thêm bước chạy 205 test vào CI trước deploy (5.G).
5. Đưa `.freebuff/` vào `.gitignore` (B5).

### Pha 1 — Vận hành (1–2 tuần)
1. Deadline watchdog bằng APScheduler + dedupe thông báo (3.1).
2. Dashboard "sắp/quá hạn" cho lãnh đạo (3.1).
3. Tích hợp email vào `push_notif` (3.3).
4. Thêm index hiệu năng (5.F).

### Pha 2 — Tái cấu trúc (2–3 tuần)
1. Tách `routes/tasks.py` → `routes/tasks/` package, giữ nguyên URL (5.A).
2. Dọn `utils.py` theo chủ đề, re-export tương thích (5.A).
3. Lưới an toàn: chạy đủ 205 test + bổ sung test route-level cho các endpoint tách ra.

### Pha 3 — Tính năng (1–2 tuần)
1. Tổng hợp số liệu chế độ FORM + khóa sổ chu kỳ (3.2).
2. Tìm kiếm toàn cục không dấu (3.5).
3. Báo cáo tuần/tháng xuất Excel (3.5).

### Pha 4 — Dài hạn (cuốn chiếu)
1. Alembic thay migration tự viết (5.B).
2. Tách cột JSON cần query thành bảng (5.C); dọn model deprecated (5.D).
3. Tách JS khỏi template + CSP nonce (5.E, B4); gộp template desktop/mobile (5.E).
4. Tùy chọn: LLM provider cho trợ lý gán việc hoặc dọn cấu hình chết trong `.env.example` (3.4).
5. Hàng đợi tác vụ cho xuất file/sync (5.F); giai đoạn 2 Zalo OA (3.1).

---

## 7. CÁCH KIỂM CHỨNG TỪNG PHA

- Mọi pha: `python3 -m unittest discover tests -v` (205 test) xanh trước và sau.
- Pha 0: POST `/api/custom-satellite-points` khi chưa đăng nhập → phải bị chặn; kiểm tra CI chạy test thật.
- Pha 1: tạo task có deadline gần ngưỡng → xác nhận thông báo sinh đúng, không lặp khi watchdog chạy lại.
- Pha 2: `tests/test_task_blueprint_routes.py` + `test_task_blueprints.py` làm lưới hồi quy; so sánh đáp ứng các URL `/tasks/*` trước/sau khi tách.
- Thay đổi schema luôn qua `python3 migrate.py --dry-run` trước (quy trình README đã có), không chạm trực tiếp DB production.

---

## PHỤ LỤC — THỐNG KÊ KHẢO SÁT

| Hạng mục | Số liệu |
|----------|---------|
| Blueprint | 9 (auth, admin, portal, tasks, api, shortlink, health, outline, google_auth) |
| Route functions | 527+ (theo tài liệu nội bộ; riêng `routes/tasks.py` 31 route decorator, 140+ hàm) |
| Model SQLAlchemy | 37 |
| Template | 37 file, ~23.600 dòng; lớn nhất `martyr_adn_map.html` 5.167 dòng |
| Test | 205 test / 26 file |
| File lớn nhất | `routes/tasks.py` 11.213 dòng; `task_import_ai.py` ~107KB; `utils.py` 1.587 dòng/55 hàm |
| Cột JSON trong model | ~14 cột `*_json` |
| Template nhúng JS inline | 29/37; dùng `|safe`: 7 chỗ / 3 file |
| Phụ thuộc khai báo nhưng chưa dùng | APScheduler (không có code), Zalo (chỉ `.env.example`), DeepSeek AI (chỉ `.env.example`) |

*Tài liệu liên quan:* `docs/de-an-cai-to-kien-truc-2026.md`, `docs/lo-trinh-trien-khai-de-an-2026.md`, `docs/tong-ra-soat-don-gian-hoa-2026.md`, `THIET_KE_CHUC_NANG_TASK_CUOI.md`, `CHANGELOG.md`.
