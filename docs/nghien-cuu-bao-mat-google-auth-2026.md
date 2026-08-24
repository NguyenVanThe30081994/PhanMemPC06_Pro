# Nghiên cứu bảo mật đăng nhập bằng Google Auth

Ngày cập nhật: `22/08/2026`
Phạm vi: luồng **OAuth 2.0 Authorization Code + PKCE** tại `routes/google_auth.py`, tích hợp phiên đăng nhập tại `routes/auth.py`, cấu hình `config.py`, kiểm thử `tests/test_google_oauth.py`.

---

## 1. Tóm tắt điều hành

- Luồng Google OAuth hiện có nền tảng **tốt**: đã dùng PKCE S256, state ký HMAC chống CSRF, không tự tạo tài khoản mới (email phải khớp tài khoản PC06), có giới hạn miền email, chống session fixation và khóa đăng nhập theo username/IP.
- Phát hiện **2 lỗ hổng mức cao cần khắc phục ngay**: (H1) không kiểm tra `email_verified` trước khi ghép tài khoản; (H2) state không có thời hạn sử dụng.
- Kèm **3 điểm siết trung bình**: ghim `redirect_uri` thay vì suy từ Host header, bổ sung log bảo mật cho các nhánh từ chối, rate-limit riêng cho callback vô danh.
- Đề xuất 3 đợt cải tiến như §4, tổng cộng ~1 ngày công, không thêm dependency, không đổi schema DB.

## 2. Hiện trạng kỹ thuật

```
GET /auth/google          → sinh state + code_verifier (PKCE), lưu session, redirect Google
GET /auth/google/callback → kiểm state → trao đổi code lấy access_token
                          → GET userinfo lấy email → tìm User theo email → _build_login_session
```

| Thành phần | Hiện trạng | Đánh giá |
|---|---|---|
| Flow | Authorization Code + PKCE (`code_challenge_method=S256`) | ✅ Chuẩn hiện đại |
| Chống CSRF OAuth | `state = raw_state.HMAC-SHA256(secret_key)`; đối chiếu cả session lẫn chữ ký | ✅ Tốt |
| Dùng một lần | Pop state/verifier khỏi session ngay sau callback | ✅ Tốt |
| Ghép tài khoản | `User.query.filter_by(email=email)` — **không** tạo user mới | ✅ Đúng mô hình nội bộ |
| Giới hạn miền | `GOOGLE_OAUTH_ALLOWED_DOMAINS` so đuôi email | ✅ Có |
| Khóa đăng nhập | `_get_login_lock_seconds(username, ip)` áp cho Google login | ✅ Đồng bộ mật khẩu |
| Session fixation | `_build_login_session()` gọi `session.clear()` + rotate CSRF token (routes/auth.py:342–344) | ✅ Tốt |
| Cookie | `HttpOnly=True`, `SameSite=Lax`, `Secure` tự bật khi `FLASK_ENV=production` (config.py:46) | ✅ Đạt |
| Timeout mạng | 20s cho token/userinfo | ✅ Có |
| Kiểm thử | 6 test: disabled, redirect, state giả, happy path, email lạ, miền chặn (tests/test_google_oauth.py) | ⚠️ Thiếu ca `email_verified=false`, state hết hạn |

## 3. Khoảng trống bảo mật phát hiện

### Mức cao
| # | Vấn đề | Vị trí | Rủi ro |
|---|---|---|---|
| H1 | **Không kiểm tra `email_verified`** trong userinfo trước khi ghép tài khoản | routes/google_auth.py:172–189 | Nếu Google trả về email chưa xác minh (một số loại tài khoản/workspace), kẻ xấu đăng ký email đó tại IdP rồi vào thẳng tài khoản PC06 trùng email. Chuẩn OIDC bắt buộc chỉ ghép khi `email_verified=true`. |
| H2 | **State không có hạn dùng** — chỉ bị pop khi dùng; session để lâu thì state cũ vẫn hợp lệ mãi | routes/google_auth.py:84–89, 117–126 | Replay state cũ trong session bị chiếm/xem lại; chuẩn khuyến nghị state sống ≤ vài phút. |

### Mức trung
| # | Vấn đề | Vị trí | Rủi ro |
|---|---|---|---|
| M1 | `redirect_uri` **tự suy từ `request.host`** khi không cấu hình `GOOGLE_OAUTH_REDIRECT_URI` | routes/google_auth.py:40–43 | Phụ thuộc Host header (host-header injection); lệch scheme http/https khi đứng sau proxy không có ProxyFix. Rủi ro thấp vì Google ép redirect_uri phải đăng ký trước, nhưng production nên ghim cấu hình. |
| M2 | Các nhánh **từ chối không ghi log bảo mật**: state sai, miền chặn, email không khớp, token lỗi | routes/google_auth.py:120–201 | Không truy vết được nỗ lực tấn công/lỗi cấu hình; chỉ có log khi bị khóa hoặc thành công. |
| M3 | `/auth/google/callback` nhận request **vô danh không tốn phí gì** (state sai chỉ flash + redirect) | routes/google_auth.py:108–131 | Có thể bị dội request liên tục; chưa có throttle theo IP độc lập với lockout username. |

### Mức thấp / ghi chú thiết kế
- **L1**: khi có `allowed_domains`, có thể thêm tham số `hd=` vào URL ủy quyền để Google lọc sẵn tài khoản Workspace (giảm nhầm lẫn người dùng).
- **L2**: thông báo lỗi phân biệt "email chưa khai báo" với "miền không cho phép" → tiết lộ nhẹ trạng thái tài khoản. Chấp nhận được trong hệ thống nội bộ; nếu muốn chặt hơn thì chung chung hóa thông báo.
- **L3**: không dùng `nonce`/không tự parse `id_token` là **đúng thiết kế** vì hệ thống đi qua token endpoint chính thức và gọi userinfo bằng access_token — không có vectơ giả mạo token cục bộ.
- **L4**: chưa có cơ chế quản trị **tắt/bật Google login theo từng user** — hiện mọi user có email đều dùng được; nếu cần siết thêm có thể bổ sung cờ.

## 4. Đề xuất hoàn thiện — lộ trình 3 đợt

### Đợt 1 — Chốt lỗ hổng cao (ưu tiên triển khai ngay, ~2 giờ)
| # | Việc | File | Tiêu chí nghiệm thu |
|---|---|---|---|
| 1.1 | Kiểm tra `google_info.get('email_verified') is True` trước khi tra User; từ chối kèm thông báo rõ ràng | routes/google_auth.py:172 | userinfo `email_verified=false` → không đăng nhập được; test mới phủ |
| 1.2 | State gắn timestamp: `raw_state = f"{random}.{int(time.time())}"`; callback từ chối state quá 10 phút | routes/google_auth.py | State cũ >10 phút → báo "Phiên đã hết hạn"; test mới phủ |

### Đợt 2 — Siết trung bình (~3 giờ)
| # | Việc | File | Tiêu chí nghiệm thu |
|---|---|---|---|
| 2.1 | Production bắt buộc `GOOGLE_OAUTH_REDIRECT_URI`: nếu `FLASK_ENV=production` mà trống → log warning + từ chối khởi động tính năng (hoặc fallback ghim theo `SERVER_NAME`) | routes/google_auth.py, config.py | Không còn phụ thuộc Host header khi deploy thật |
| 2.2 | Thêm `log_security_event('oauth_rejected', reason=...)` cho 5 nhánh: state sai/hết hạn, thiếu code, token lỗi, miền chặn, email chưa xác minh/không khớp | routes/google_auth.py | Toàn bộ nhánh từ chối để lại dấu vết trong SecurityLog |
| 2.3 | Throttle callback theo IP: tái dùng `_get_security_state('ip', …)` — quá N lần state-sai/phút thì khóa ngắn | routes/google_auth.py + routes/auth.py | Test: spam callback sai state → bị khóa tạm |

### Đợt 3 — Nâng cao (tùy chọn, làm khi có nhu cầu)
| # | Việc | Ghi chú |
|---|---|---|
| 3.1 | Thêm `hd=` khi có allowed_domains | UX, giảm chọn nhầm tài khoản cá nhân |
| 3.2 | Cờ bật/tắt Google login theo user (`User.allow_google_login`) + giao diện quản trị | Schema + migrate.py theo quy ước hiện hành |
| 3.3 | Bước xác minh thứ hai cho vai trò nhạy cảm: sau Google login vẫn phải qua `/reauth` khi vào khu vực quản trị | Tận dụng cơ chế reauth sẵn có |
| 3.4 | Cảnh báo đăng nhập Google từ IP/thiết bị lạ | `_register_trusted_device` đã có nền |

### Bổ sung kiểm thử
Mở rộng `tests/test_google_oauth.py`:
1. userinfo `email_verified=False` → bị từ chối (Đợt 1.1).
2. State khởi tạo "giả mạo thời gian" quá hạn → bị từ chối (Đợt 1.2).
3. Nhánh miền chặn có log security event (Đợt 2.2).

## 5. Tiêu chí nghiệm thu tổng

- [ ] `email_verified=false` không thể đăng nhập dù email khớp tài khoản.
- [ ] State hết hạn sau 10 phút; state dùng lại lần thứ hai bị từ chối.
- [ ] Mọi nhánh từ chối của callback ghi được security event kèm lý do.
- [ ] Không phụ thuộc Host header cho redirect_uri trong môi trường production.
- [ ] Toàn bộ suite hiện có (≥204 test) + test mới vẫn xanh; không thêm dependency mới.

## 6. Rủi ro & tương thích

- Kiểm tra `email_verified`: Google gần như luôn trả `true` cho tài khoản đang dùng — rủi ro ảnh hưởng người dùng thật rất thấp, nhưng cần thông báo lỗi thân thiện và hướng dẫn xác minh email trên Google.
- State có hạn dùng: ai mở trang đăng nhập rồi để quá 10 phút mới bấm đăng nhập Google sẽ phải thử lại — hành vi chấp nhận được (bản thân state cũng single-use).
- Không đổi bảng dữ liệu trong Đợt 1–2; Đợt 3.2 nếu làm sẽ đi qua `migrate.py` theo quy ước.
