# Nghiên cứu bổ sung cơ chế bảo mật cho triển khai cPanel

Ngày cập nhật: `22/08/2026`
Bối cảnh: **cPanel shared hosting** (Apache + Passenger), ứng dụng đặt tại
`~/domains/<domain>/public_html/PhanMemPC06_Pro`, MySQL qua `DATABASE_URL`,
không chạy local. Phạm vi: hạ tầng triển khai, phiên bản web, dữ liệu tệp,
Google OAuth trên proxy, vá nốt các lỗ hổng đã phát hiện nhưng còn mở.
Kế thừa: `docs/BAO_CAO_DANH_GIA_TOAN_DIEN_2026-08.md` (mục B1–B8),
`docs/nghien-cuu-bao-mat-google-auth-2026.md`.

---

## 1. Tóm tắt điều hành

- Nền tảng bảo mật của hệ thống **đã đầy đủ hơn mặt bằng chung**: CSRF toàn cục,
  security headers + HSTS, khóa đăng nhập lũy tiến, thiết bị tin cậy, re-auth,
  phân quyền view/process/exec. Các phát hiện B1 (API vệ tinh ghi/xóa công khai)
  và B2 (`db.create_all` trong request) **đã được vá**, có chú thích tại chỗ.
- Nghiên cứu lần này phát hiện **4 vấn đề mới gắn trực tiếp với bối cảnh cPanel**
  (C1–C4 §3): hai bản `get_client_ip` không nhất quán (bản trong `utils.py` tin
  mù `X-Forwarded-For`), chưa ép HTTPS ở tầng ứng dụng, thiếu `.htaccess` chặn
  tệp nhạy cảm khi app nằm trong `public_html`, và `redirect_uri` của Google
  OAuth sinh theo scheme sai sau proxy.
- Đồng thời xác nhận **B3, B6, B7, B8 trong báo cáo 14/08 vẫn còn mở** — đưa vào
  cùng lộ trình xử lý.
- Đề xuất 3 đợt: **Đợt A** vá điểm hở (cao), **Đợt B** củng cố hạ tầng cPanel,
  **Đợt C** nâng dài hạn. Không thêm dependency bắt buộc, không đổi schema.

## 2. Hiện trạng bảo mật đối chiếu bối cảnh cPanel

### 2.1 Những gì đã vững (giữ nguyên, không làm lại)
| Cơ chế | Vị trí |
|---|---|
| CSRF token toàn cục + Origin/Referer + `compare_digest` | app.py:541–569 |
| Security headers (CSP/HSTS/XFO/nosniff/Referrer/Permissions) | app.py:301–340, .htaccess:8–16 |
| Khóa đăng nhập lũy tiến theo username + IP, delay chống brute-force | routes/auth.py:209–327 |
| Thiết bị tin cậy + cảnh báo đăng nhập lạ, session binding | routes/auth.py:126–176 |
| Re-auth cho khu vực nhạy cảm | /reauth |
| Phân quyền view/process/exec + delegation | permissions.py, docs/ma-tran-quyen-chuan-2026.md |
| Secret key tự sinh lưu 0600 ngoài code | security_utils/runtime_security.py:21–48 |
| Trusted-proxy IP chuẩn CIDR | security_utils/runtime_security.py:165 |
| Whitelist endpoint công khai đã thu hẹp (B1 ✅) | app.py:433–449 |
| `db.create_all()` chỉ chạy lúc khởi động (B2 ✅) | app.py:402 |

### 2.2 Rủi ro đặc thù shared hosting/cPanel cần lưu ý nền
1. **App nằm bên trong `public_html`**: mọi tệp dự án (`.env`, `backups/`,
   `logs/`, `tmp/`, DB SQLite nếu lỡ dùng…) cùng máy chủ web. Passenger định tuyến
   mọi URL qua WSGI nên hiện không đọc trộm được qua HTTP, nhưng chỉ cần đổi cấu
   hình (tắt Passenger, phục vụ static trực tiếp) là lộ ngay.
2. **Proxy Apache phía trước**: Flask nhìn thấy `REMOTE_ADDR=127.0.0.1`; mọi logic
   dựa IP phải đi qua header chuyển tiếp có kiểm soát (`TRUSTED_PROXY_CIDRS`,
   mặc định bao gồm loopback/private — khớp cPanel).
3. **Passenger chạy nhiều process worker**: state in-memory không chia sẻ giữa các
   process (rate-limit, scheduler).
4. **Python hệ thống cũ (3.6)**: phải chạy qua venv "Setup Python App" ≥ 3.9 như
   DEPLOY_CPANEL.md đã hướng dẫn; vá phụ thuộc phải vào đúng venv này.

## 3. Phát hiện mới (không trùng lặp các mục đã vá)

### C1 — Hai bản `get_client_ip` không nhất quán (cao)
- `utils.py:35–43`: lấy thẳng phần tử đầu của `X-Forwarded-For` — **tin mù header
  do client gửi** → giả IP để né khóa đăng nhập theo IP và làm sai nhật ký.
- `security_utils/security_helpers.py:11–18`: bản đúng — chỉ nhận XFF khi
  `remote_addr` thuộc `TRUSTED_PROXY_CIDRs`.
- Hiện `routes/auth.py` và `routes/google_auth.py` dùng bản đúng; bản sai còn lại
  trong `utils.py` (dùng bởi `log_security_event` của utils) và có thể bị import
  nhầm khi viết mã mới.

### C2 — Chưa ép HTTPS ở tầng ứng dụng (cao)
- `SESSION_COOKIE_SECURE` chỉ bật khi `FLASK_ENV=production` (config.py:46) —
  nếu quên đặt biến này trên host, cookie phiên gửi cả qua HTTP.
- Không có redirect `http://` → `https://` trong app; `.htaccess` cũng chưa có
  RewriteRule. Người dùng gõ domain không https vẫn dùng được phiên không mã hóa
  (trừ khi hosting tự ép).

### C3 — Thiếu `.htaccess` chặn tệp nhạy cảm (trung bình–cao)
`.htaccess` hiện chỉ có headers + `Options -Indexes` (17 dòng). Chưa deny:
`.env`, `.git*`, `backups/`, `logs/`, `tmp/`, `*.db`, `*.sql`, `*.bat`,
`requirements.txt`, `passenger_wsgi.py`, thư mục test/scripts. Đây là phòng thủ
sâu cho rủi ro §2.2.1.

### C4 — Google OAuth sinh `redirect_uri` theo scheme sai sau proxy (trung bình)
`routes/google_auth.py:40–43` dùng `request.is_secure` trực tiếp, không đi qua
helper `_request_is_secure()` đã xử lý `X-Forwarded-Proto` (app.py:246–249). Sau
Apache/cPanel, nếu header proto không được Flask tự hiểu, redirect_uri sinh ra
`http://…` trong khi site thật chạy HTTPS → lệch với URL đăng ký trên Google
Console, đăng nhập Google lỗi hoặc quay về callback không mã hóa. Khớp với đề
xuất M1 trong `docs/nghien-cuu-bao-mat-google-auth-2026.md`.

### C5 — Watchdog/scheduler nhân bản theo process Passenger (thấp)
Guard chống khởi động kép trong `services/task_scheduler.py` là **per-process**
(`app.extensions`). Passenger nhiều process → mỗi process một watchdog; dedupe
thông báo của `deadline_watchdog` (marker theo user+task+ngưỡng) giúp không spam
nhưng vẫn lãng phí tài nguyên và log khó đoán. Ghi chú cấu hình hoặc chọn 1 process.

## 4. Các mục B3/B6/B7/B8 của báo cáo 14/08 — kiểm chứng còn mở

| # | Nội dung | Trạng thái kiểm chứng 22/08 |
|---|---|---|
| B3 | `str(exc)` trả nguyên văn ra client | ⛔ Vẫn mở — routes/api.py:276, 310, 364 (+ cần rà handler khác) |
| B4 | CSP `'unsafe-inline' 'unsafe-eval'` do JS inline | ⏳ Mở (phải tách JS mới gỡ được — dài hạn) |
| B6 | Rate-limit in-memory, mất khi restart, không chia sẻ giữa process | ⏳ Mở (chấp nhận có giám sát, hoặc chuyển mốc IP vào DB như lockout) |
| B7 | `utils.check_csrf_token` so sánh `==` | ⛔ Vẫn mở — utils.py:15–22 |
| B8 | Script nhạy cảm ở gốc repo | ⛔ Vẫn mở — reset_admin.py, reset_user_password.py, reset_categories.py, Reset_Database.bat, migrate_sqlite_to_external_db.py |

---

## 5. Lộ trình đề xuất

### Đợt A — Vá điểm hở đang mở (ưu tiên cao nhất, ~1 ngày) — ✅ ĐÃ TRIỂN KHAI 22/08/2026
| # | Việc | File | Trạng thái |
|---|---|---|---|
| A1 | Thống nhất `get_client_ip` về bản trusted-CIDR: `utils.get_client_ip` gọi `security_utils.extract_client_ip` | utils.py:35 | ✅ Xong |
| A2 | Ép HTTPS: before_request `force_https_redirect` (cờ `PC06_FORCE_HTTPS`, mặc định theo `FLASK_ENV=production`) + RewriteRule trong `.htaccess`; miễn health check | app.py, config.py, .htaccess | ✅ Xong |
| A3 | Sửa B3: trả thông báo chung + log server-side. Lưu ý: 3 chỗ `str(exc)` cũ tại routes/api.py:276/310/364 thực ra là **thông báo hướng dẫn đã soạn sẵn** (RuntimeError curated) nên giữ nguyên; đã sửa các chỗ trả exception thô thật: routes/outline.py:98,118 · routes/portal.py:1105 · routes/shortlink.py:231 | routes/* | ✅ Xong |
| A4 | Sửa B7: `check_csrf_token` dùng `secrets.compare_digest` | utils.py:15 | ✅ Xong |
| A5 | Sửa B8: dời 5 script quản trị vào `scripts/admin/`, bắt buộc `PC06_CONFIRM=YES` qua `_admin_script_guard.py`; cập nhật HUONG_DAN_TRIEN_KHAI.md + docs/reporty-mysql-cutover.md | scripts/admin/ | ✅ Xong |

Test mới: `tests/test_runtime_hardening.py` (11 test — IP trusted-proxy, ép HTTPS, so sánh CSRF). Suite: 215 test OK.

### Đợt B — Củng cố hạ tầng cPanel (~1 ngày + vận hành) — ✅ ĐÃ TRIỂN KHAI 22/08/2026
| # | Việc | Trạng thái |
|---|---|---|
| B1' | `.htaccess` deny tệp/thư mục nhạy cảm | ✅ Xong — FilesMatch mở rộng (`.env*`, `.secret_key`, `*.sqlite`, `*.sh`…) + RewriteRule `[F]` pattern **tương đối**, khớp cả root lẫn thư mục con (thay RedirectMatch ghim cứng prefix) |
| B2' | Ghim `GOOGLE_OAUTH_REDIRECT_URI`; `_oauth_config` nhận biết `X-Forwarded-Proto/Ssl` khi tự suy + warning; mẫu cấu hình trong `.env.example` | ✅ Xong (routes/google_auth.py, .env.example); trên host cần điền giá trị thật theo checklist |
| B3' | Checklist kiểm chứng server (.env 600, FLASK_ENV, DATA_DIR ngoài webroot, MySQL host-local, AutoSSL trước khi ép HTTPS) | ✅ Xong — mục "🔒 CHECKLIST BẢO MẬT TRÊN HOST" trong DEPLOY_CPANEL.md |
| B4' | Cron backup MySQL hằng đêm ngoài webroot, giữ 14 ngày + quy trình khôi phục quý | ✅ Xong — `scripts/admin/backup_mysql.sh` + hướng dẫn cron trong DEPLOY_CPANEL.md |
| B5' | Watchdog đa process Passenger | ✅ Xong — ghi chú giữ 1–2 process hoặc `PC06_TASK_SCHEDULER=0` cho bản sao phụ trong DEPLOY_CPANEL.md |
| B6' | ModSecurity của cPanel | ✅ Đã hướng dẫn bật trong checklist (thao tác trên UI hosting) |

Test mới: `test_redirect_uri_infers_https_behind_proxy` trong tests/test_google_oauth.py. Suite: 216 test OK.
Cần làm trên host thật (không thể tự động): chạy checklist mục 🔒 trong DEPLOY_CPANEL.md và gắn cron backup.

### Đợt C — Nâng dài hạn (cuốn chiếu) — ✅ TRIỂN KHAI 22/08/2026 (trừ C1-full)
| # | Việc | Trạng thái |
|---|---|---|
| C1 | Tách JS inline → CSP bỏ `unsafe-inline/eval` | ⏳ Dời lại — cần refactor 29 template (~23.600 dòng), làm cuốn chiếu theo §5.E báo cáo 14/08. **Đã siết CSP bước gần**: thêm `form-action 'self'` (cùng frame-ancestors/base-uri/object-src có từ trước) |
| C2 | Rate-limit vào DB | ⚖️ **Quyết định: chấp nhận in-memory cho cap chung/API** — các giới hạn bảo mật trọng yếu (khóa đăng nhập) đã DB-backed an toàn đa process; DB counter mỗi request gây chi phí trên shared hosting. Khớp khuyến nghị "chấp nhận có ghi chú" của B6 gốc |
| C3 | 2FA TOTP cho user | ✅ Xong — pyotp; secret mã hóa Fernet; luồng đăng nhập 2 bước; trang thiết lập QR tại `/security/two-factor` (yêu cầu re-auth); tắt phải mật khẩu; test `tests/test_totp_2fa.py` |
| C4 | Chu kỳ vá phụ thuộc | ✅ Xong — `scripts/admin/monthly_security_maintenance.sh` (pip outdated + pip-audit, chỉ báo cáo) + cron mẫu trong DEPLOY_CPANEL.md |
| C5 | Giám sát sự kiện bảo mật + retention | ✅ Xong — tab "Bảo mật 7 ngày" trong `/admin/logs`: tổng hợp theo loại/IP, 20 bản ghi mới nhất; dọn log theo khoảng thời gian đã có sẵn tại cùng trang |

Suite: **222 test OK**. Lưu ý vận hành: sau khi deploy, chạy lại `pip install -r requirements.txt` trong venv cPanel (có thêm `pyotp==2.9.0`) rồi restart Passenger; migration 2 cột `user.totp_*` tự chạy lúc khởi động qua `apply_migrations`.

## 6. Tiêu chí nghiệm thu tổng

- [x] Header `X-Forwarded-For` giả từ client không thay đổi được IP ghi nhận ở mọi đường (login, lockout, log). *(Đợt A — 22/08/2026)*
- [x] Truy cập `http://domain` luôn 308 sang `https://`; cookie phiên có cờ Secure khi `FLASK_ENV=production`. *(Đợt A)*
- [x] `.htaccess` chặn truy cập web tới tệp nhạy cảm (`.env`, `*.sql`, `backups/`, `logs/`…) — pattern tương đối, khớp mọi vị trí cài. *(Đợt B1')*
- [x] Google OAuth tự suy redirect_uri nhận biết `X-Forwarded-Proto`; mẫu ghim URI trong `.env.example` + checklist deploy. *(Đợt B2')* — trên host cần điền giá trị thật
- [x] Response lỗi API không lộ chi tiết exception nội bộ. *(Đợt A)*
- [x] Cron backup MySQL ngoài webroot + quy trình khôi phục; checklist server và ghi chú watchdog/ModSecurity trong DEPLOY_CPANEL.md. *(Đợt B3'–B6')*
- [x] Toàn bộ suite test xanh sau từng đợt (216 test). *(Đợt A)*

## 7. Rủi ro & tương thích

- A2 ép HTTPS: phải bật AutoSSL/Let's Encrypt cho domain **trước** khi bật cờ, kèm ngoại lệ cho health endpoint nếu monitoring nội bộ gọi qua HTTP.
- B1' deny `.htaccess`: một số host đặt DocumentRoot khác cấu trúc mẫu — cần thử nghiệm trên staging path trước.
- A1 đổi hành vi IP: các bản ghi lockout cũ theo IP naive sẽ không khớp — chấp nhận (tự hết hạn theo cửa sổ khóa).
- Không thay đổi schema DB trong cả ba đợt; script di dời (A5) chỉ ảnh hưởng thao tác dòng lệnh của quản trị.
