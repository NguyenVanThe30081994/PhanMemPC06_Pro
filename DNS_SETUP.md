# HƯỚNG DẪN TRỎ DOMAIN VÀ ĐẨY CODE LÊN HOSTING (dean06tuyenquang.id.vn)

Quá trình chia làm 3 Giai đoạn cốt lõi:

## GIAI ĐOẠN 1: Trỏ Tên Miền (DNS) vào Hosting/VPS
Để tên miền `dean06tuyenquang.id.vn` biết đường tìm về máy chủ Hosting của bạn:
1. Đăng nhập vào trang quản lý Tên Miền (nơi bạn mua `dean06tuyenquang.id.vn` - VD: iNET, Tenten, Mắt Bão).
2. Tạo 2 bản ghi (Record) với nội dung sau:
   - Bản ghi 1:
     - Biểu tượng/Tên Host: `@` (hoặc để trống)
     - Loại Record: `A` (hoặc A Record)
     - Giá trị: Điền **Địa chỉ IP của Hosting/VPS** (VD: 103.xxx.yyy.zzz)
   - Bản ghi 2:
     - Biểu tượng/Tên Host: `www`
     - Loại Record: `CNAME`
     - Giá trị: Học sang `dean06tuyenquang.id.vn` hoặc nhập trùng dãy số `[IP của Hosting]`.
3. Chờ đợi từ 5 phút - 1 tiếng để DNS toàn cầu lan rộng (Ping thử bằng lệnh `ping dean06tuyenquang.id.vn`).

--- 

## GIAI ĐOẠN 2: Dọn đường Code Local và đẩy lên GitHub (Tùy chọn Chuẩn nhất)
Nên dùng Github làm trạm trung chuyển (Tuyệt đối không nên kéo thả File Zip bằng tay vì mỗi lần sửa code sẽ phải lặp lại).

1. Mở thư mục `PhanMemPC06_Pro` ở máy tính lên (chuột phải > Open Terminal / Git Bash).
2. Chạy nhanh lệnh này để đồng bộ và đưa Source lên Trạm mây cá nhân:
   ```bash
   git init
   git add .
   git commit -m "Khoi tao he thong PC06 Online"
   git branch -M main
   # Thay dòng chữ sau bằng tên kho Repo GitHub của bạn
   git remote add origin https://github.com/YourName/PC06_tuyenquang.git
   git push -u origin main
   ```

## GIAI ĐOẠN 3: Kéo Code về Hosting & Bấm nút Chạy (Deploy)
Lúc này bạn sử dụng phần mềm MobaXTerm hoặc PuTTY kết nối vào con Hosting (nhớ là nó chạy Ubuntu/Linux).

1. **Chuẩn bị hạ tầng Server (Chỉ chạy 1 lần duy nhất):**
   Nếu Server của bạn mới toanh, hãy chạy lệnh này để tự động cài đặt Docker và Nginx:
   ```bash
   cd /home/
   # Dùng git kéo code ban đầu (thay YourName bằng Github của bạn)
   git clone https://github.com/YourName/PC06_tuyenquang.git
   cd PC06_tuyenquang
   chmod +x setup_server.sh
   # Chạy script cài đặt (Nhập mật khẩu sudo nếu có)
   sudo ./setup_server.sh
   ```

2. **Chạy hệ thống (Deploy):**
   Sau khi cài đặt xong, bạn chỉ cần chạy lệnh này để kích hoạt Web:
   ```bash
   chmod +x deploy.sh
   ./deploy.sh
   ```

3. **Cập nhật tính năng (Sửa code):**
   Sau này mỗi khi tôi sửa code cho bạn ở Local, bạn chỉ cần vào Hosting và gõ:
   ```bash
   ./deploy.sh
   ```
   Hệ thống sẽ tự động lấy code mới, xây dựng lại và khởi động lại Nginx cho bạn.

🎉 Xin chức mừng! Giờ hãy gõ `http://dean06tuyenquang.id.vn` trên điện thoại/laptop để xem thành quả!
