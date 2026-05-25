# THIET KE CHUC NANG TASK CUOI
## Phan he giao viec va quan ly bao cao da hinh thuc

Tai lieu nay la ban thiet ke cuoi cung duoc chot sau khi doi chieu:
- Hien trang code trong repo `PhanMemPC06_Pro`
- Tai lieu tham chieu `/Users/thenhung/Downloads/thiet ke task.md`
- Kinh nghiem thiet ke tu cac mo hinh task pho bien nhu Asana, Jira, monday.com, ClickUp

Muc tieu cua ban thiet ke nay la:
- Don gian hoa tu duy nghiep vu cua phan he `task`
- Giu duoc kha nang mo rong
- Han che tiep tuc chong chat giua `Task`, `child task`, `report schema`, `submission`
- Tao mot lo trinh trien khai thuc te, phu hop voi codebase hien tai

---

## 1. Ket luan thiet ke cuoi

Phan he `task` duoc chot theo huong:

1. `Task` la dot giao viec hoac dot bao cao tong the.
2. Moi `Task` co `task_mode` de xac dinh hinh thai giao viec.
3. Giai doan 1 trien khai day du 2 hinh thai chinh:
   - `OUTLINE`: giao viec theo de cuong, dau muc, noi dung phan ra
   - `FILE`: giao viec yeu cau nop file minh chung hoac van ban tong hop
4. Giai doan 2 mo rong `FORM`:
   - `FORM`: thu thap so lieu, cau hoi dong, bang so lieu dong
5. Khong dung `child Task` de dai dien cho moi dau muc de cuong nua.
6. `child Task` chi duoc phep ton tai neu do la cong viec doc lap thuc su, co vong doi rieng.
7. Don vi nghiep vu can lam viec voi mot mo hinh thong nhat: `Task` -> `Task Item` -> `Assignment` -> `Submission`.

---

## 2. Van de cua hien trang

Hien tai code dang co 2 luong UI chinh:
- `child_tasks`
- `summary_report`

Nhung o tang du lieu, `Task` dang dong thoi ganh qua nhieu vai tro:
- cong viec tong
- cong viec con
- dau muc bao cao
- cau hinh schema nhap lieu
- file dinh kem
- phan quyen nguoi xu ly
- lien ket mau bao cao

He qua:
- Kho mo rong logic
- Kho thong ke dung nghiep vu
- Kho phan biet giua "dau muc" va "cong viec"
- De phat sinh duplicate logic giua giao dien va backend

Vi vay, ban thiet ke cuoi khong tiep tuc to chuc theo "2 luong man hinh", ma to chuc theo "kieu giao viec theo dau ra".

---

## 3. Nguyen tac thiet ke

1. Phan biet ro `dot giao viec`, `dau muc giao viec`, `doi tuong nhan viec`, `ket qua nop`.
2. Moi du lieu chi co mot vai tro chinh.
3. Cho phep mot `Task` giao cho nhieu don vi.
4. Cho phep moi don vi nop nhieu lan, luu lich su, nhung chi co 1 ban nop hien hanh dang hieu luc.
5. Nop file, nop noi dung, nop bieu mau la 3 dang dau ra khac nhau, khong tron chung trong mot schema tam.
6. Phan quyen va co lap du lieu la bat buoc, khong tin tham so client gui len.
7. Uu tien refactor co lo trinh, khong vo lai toan bo phan he trong mot dot.

---

## 4. Pham vi nghiep vu

### 4.1. Hinh thai `OUTLINE`

Ap dung khi:
- Mot van de lon can chia thanh cac muc, tieu muc, de cuong
- Moi don vi duoc giao viet noi dung cho mot hoac nhieu dau muc
- Can tong hop toan van thanh mot bao cao hop nhat

Dac diem:
- `Task` la dot bao cao
- `Task Item` la dau muc de cuong
- `Assignment` xac dinh don vi nao phai lam dau muc nao
- `Submission` luu noi dung bao cao cua tung don vi theo tung dau muc
- Ho tro tong hop theo ma tran `don vi x dau muc`
- Co the xuat Word tong hop

### 4.2. Hinh thai `FILE`

Ap dung khi:
- Giao viec truc tiep cho don vi
- Yeu cau nop file bao cao, cong van, bien ban, file ky so, file tong hop
- Khong can phan ra thanh de cuong

Dac diem:
- `Task` la dot giao viec
- `Task Item` co the bo qua
- `Assignment` la ban giao viec toi tung don vi
- `Submission` luu ghi chu tom tat + file nop + lich su nop
- Ho tro tra lai bo sung, nop lai, thay file

### 4.3. Hinh thai `FORM`

Ap dung khi:
- Thu thap chi tieu, so lieu, lua chon, bang bieu dong
- Can tong hop tu dong ra Excel hoac dashboard

Ket luan trien khai:
- Giu san mo hinh trong thiet ke
- Chua dua vao dot refactor dau tien
- Khi lam pha 2, co the dung lai khung `Task` -> `Assignment` -> `Submission`

---

## 5. Mo hinh du lieu muc tieu

## 5.1. Bang `task`

Vai tro:
- Dai dien cho mot dot giao viec hoac dot bao cao tong

Truong du lieu chot:
- `id`
- `title`
- `description`
- `deadline`
- `status`
- `task_mode`: `OUTLINE`, `FILE`, `FORM`
- `category`
- `domain`
- `priority`
- `author_id`
- `author_name`
- `assignment_scope_json`
- `manager_scope_json`
- `viewer_scope_json`
- `created_at`
- `updated_at`

Ghi chu:
- Truong `workflow_mode` hien tai se duoc thay the logic bang `task_mode`
- Neu can tuong thich tam thoi, co the mapping:
  - `child_tasks` -> `OUTLINE`
  - `summary_report` -> `FILE`

## 5.2. Bang `task_item`

Vai tro:
- Dai dien cho dau muc de cuong hoac muc giao viec con ben trong mot `Task`

Truong du lieu chot:
- `id`
- `task_id`
- `parent_item_id` nullable, de mo rong de cuong nhieu cap
- `item_code`: vi du `1`, `1.1`, `III.2`
- `title`
- `guide_text`
- `sort_order`
- `is_required`
- `output_type`
- `attachment_required`
- `created_at`
- `updated_at`

Quy uoc:
- Trong `OUTLINE`, `task_item` la bat buoc
- Trong `FILE`, co the khong can `task_item`
- Trong `FORM`, `task_item` co the dung de dai dien tung nhom cau hoi neu can

## 5.3. Bang `task_assignment`

Vai tro:
- Dai dien cho viec giao mot `Task` hoac mot `Task Item` cho mot don vi hay mot doi tuong xu ly

Truong du lieu chot:
- `id`
- `task_id`
- `task_item_id` nullable
- `assignee_type`: `unit`, `role`, `user`
- `unit_id` nullable
- `role_id` nullable
- `user_id` nullable
- `title_snapshot`
- `status`: `draft`, `assigned`, `in_progress`, `submitted`, `returned`, `completed`, `overdue`
- `is_required`
- `assigned_at`
- `submitted_at`
- `returned_at`
- `completed_at`
- `last_submission_id` nullable

Ket luan quan trong:
- Tai lieu tham chieu cu de `TaskAssignment` vua la noi dung giao viec vua la nguoi nhan viec
- Ban thiet ke cuoi khong chot huong do
- `TaskAssignment` chi con la lop "giao cho ai", khong dong vai tro "dau muc nghiep vu"

## 5.4. Bang `task_submission`

Vai tro:
- Luu tung lan nop cua don vi

Truong du lieu chot:
- `id`
- `task_id`
- `task_item_id` nullable
- `assignment_id`
- `submitted_by`
- `submission_type`: `OUTLINE`, `FILE`, `FORM`
- `submission_status`: `draft`, `submitted`, `returned`, `approved`
- `narrative_content` nullable
- `payload_json` nullable
- `submitted_at`
- `returned_at`
- `approved_at`
- `created_at`
- `updated_at`

Ghi chu:
- Moi lan nop tao hoac cap nhat 1 ban ghi
- Khuyen nghi luu lich su day du thay vi ghi de toan bo

## 5.5. Bang `task_submission_file`

Vai tro:
- Tach file nop ra khoi `task_submission` de ho tro nhieu file, version, metadata

Truong du lieu chot:
- `id`
- `submission_id`
- `original_name`
- `stored_name`
- `stored_path`
- `file_ext`
- `mime_type`
- `file_size`
- `is_signed`
- `uploaded_at`

Quy tac dat ten:
- `[task_id]_[assignment_id]_[timestamp]_[random].[ext]`

## 5.6. Bang `task_form_field`

Vai tro:
- Cau hinh field dong cho `FORM`

Truong du lieu chot:
- `id`
- `task_id`
- `task_item_id` nullable
- `field_key`
- `field_label`
- `field_type`
- `field_options_json`
- `sort_order`
- `is_required`

## 5.7. Bang `task_comment`

Vai tro:
- Nhat ky trao doi
- Tra lai bo sung
- Ghi chu quan tri

Khuyen nghi:
- Giu bang hien tai
- Bo sung `submission_id` nullable neu can lien ket truc tiep vao lan nop

---

## 6. Quan he du lieu

### 6.1. `OUTLINE`

```text
Task
  -> TaskItem (nhieu dau muc)
    -> TaskAssignment (moi dau muc giao cho nhieu don vi neu can)
      -> TaskSubmission (noi dung nop cua don vi)
        -> TaskSubmissionFile (tep minh chung neu co)
```

### 6.2. `FILE`

```text
Task
  -> TaskAssignment
    -> TaskSubmission
      -> TaskSubmissionFile
```

### 6.3. `FORM`

```text
Task
  -> TaskFormField
  -> TaskAssignment
    -> TaskSubmission(payload_json)
```

---

## 7. Trang thai nghiep vu thong nhat

Trang thai cap `Task`:
- `draft`
- `published`
- `closed`
- `archived`

Trang thai cap `Assignment`:
- `assigned`
- `in_progress`
- `submitted`
- `returned`
- `completed`
- `overdue`

Trang thai cap `Submission`:
- `draft`
- `submitted`
- `returned`
- `approved`

Quy tac:
- `Task` quan ly vong doi dot giao viec
- `Assignment` quan ly tien do don vi thuc hien
- `Submission` quan ly tung lan nop

Khong su dung lai cach tron:
- `Chua tiep nhan`
- `Dang thuc hien`
- `Hoan thanh`
cho tat ca moi tang du lieu neu khong xac dinh ro cap nao dang dung.

---

## 8. Luong xu ly nghiep vu

## 8.1. Luong `OUTLINE`

1. Admin tao `Task`, chon `task_mode = OUTLINE`
2. Admin nhap hoac import de cuong thanh danh sach `TaskItem`
3. Admin gan tung `TaskItem` cho mot hoac nhieu don vi
4. Don vi vao danh sach viec cua minh, thay cac muc duoc giao
5. Don vi nhap noi dung tung muc, co the dinh kem tep minh chung
6. Don vi luu nhap hoac nop chinh thuc
7. Admin xem dashboard ma tran:
   - don vi nao chua nop
   - muc nao chua hoan thanh
   - muc nao nop thieu
8. Admin xuat tong hop:
   - xem online
   - xuat Word tong hop

## 8.2. Luong `FILE`

1. Admin tao `Task`, chon `task_mode = FILE`
2. Admin gan task cho cac don vi
3. Admin cau hinh:
   - co bat buoc file hay khong
   - cho phep dinh dang nao
   - co yeu cau mo ta noi dung hay khong
4. Don vi nop ghi chu tom tat + tep
5. Neu chua dat, admin tra lai bo sung
6. Don vi nop lai
7. Admin dong hoac hoan thanh task

## 8.3. Luong `FORM`

1. Admin tao `Task`, chon `task_mode = FORM`
2. Admin thiet ke cac field dong
3. Don vi nhap lieu
4. He thong validate
5. Admin tong hop Excel, dashboard

---

## 9. Giao dien chot

## 9.1. Trang danh sach task

Khong dung ngon ngu "luong Nhiem vu" va "luong Tong hop" lam trung tam nua.

Thay bang 3 the tao task:
- `Giao viec theo de cuong`
- `Giao viec nop file`
- `Giao viec bieu mau`

Trong giai doan 1:
- Hien 2 the dau
- The `Bieu mau` co the an hoac danh dau "sap mo rong"

## 9.2. Form tao task phia admin

### Buoc 1: Chon kieu giao viec
- `OUTLINE`
- `FILE`
- `FORM`

### Buoc 2: Nhap thong tin chung
- Tieu de
- Mo ta
- Han nop
- Linh vuc
- Do uu tien
- Pham vi duoc xem
- Pham vi duoc quan ly

### Buoc 3A: Cau hinh rieng cho `OUTLINE`
- Nhap de cuong thu cong
- Hoac import file `.docx` / `.txt`
- Sap xep thu tu
- Danh dau muc bat buoc
- Cau hinh co cho phep tep minh chung hay khong

### Buoc 3B: Cau hinh rieng cho `FILE`
- Tiep nhan file bat buoc hoac tuy chon
- Danh sach duoi file cho phep
- File mau dinh kem neu co
- Yeu cau mo ta tom tat

### Buoc 3C: Cau hinh rieng cho `FORM`
- Tao danh sach field dong
- Kieu `text`, `number`, `radio`, `checkbox`, `textarea`, `table`

### Buoc 4: Gan don vi
- Chon theo don vi
- Chon theo vai tro
- Chon theo nguoi dung

## 9.3. Giao dien phia don vi

Frontend render theo `task_mode`.

### `OUTLINE`
- Danh sach dau muc duoc giao
- Moi dau muc co:
  - huong dan
  - o nhap noi dung
  - khu dinh kem file
  - trang thai

### `FILE`
- O mo ta tom tat
- Khu upload file
- Danh sach cac lan nop truoc

### `FORM`
- Renderer dong tu schema field

---

## 10. API muc tieu

## 10.1. Admin

- `POST /api/v1/tasks`
  - Tao dot giao viec

- `POST /api/v1/tasks/{task_id}/items`
  - Tao hoac import danh sach dau muc

- `POST /api/v1/tasks/{task_id}/assignments`
  - Tao danh sach assignment cho don vi, vai tro, nguoi dung

- `PATCH /api/v1/tasks/{task_id}`
  - Sua task

- `POST /api/v1/tasks/{task_id}/publish`
  - Phat hanh task

- `POST /api/v1/tasks/{task_id}/close`
  - Dong task

## 10.2. Don vi nhan viec

- `GET /api/v1/my-assignments`
  - Lay danh sach viec cua nguoi dung hoac don vi

- `GET /api/v1/assignments/{assignment_id}`
  - Lay chi tiet assignment

- `POST /api/v1/assignments/{assignment_id}/draft`
  - Luu nhap

- `POST /api/v1/assignments/{assignment_id}/submit`
  - Nop chinh thuc

- `POST /api/v1/assignments/{assignment_id}/resubmit`
  - Nop lai sau khi bi tra

## 10.3. Giam sat va tong hop

- `GET /api/v1/tasks/{task_id}/progress`
  - Tong hop tien do

- `GET /api/v1/tasks/{task_id}/outline-matrix`
  - Ma tran `don vi x dau muc`

- `GET /api/v1/tasks/{task_id}/export-form.xlsx`
  - Xuat du lieu `FORM`

- `POST /api/v1/tasks/{task_id}/merge-outline`
  - Tron noi dung `OUTLINE` thanh van ban tong hop

---

## 11. Mapping tu code hien tai sang mo hinh moi

## 11.1. Mapping logic tam thoi

- `workflow_mode = child_tasks` -> `task_mode = OUTLINE`
- `workflow_mode = summary_report` -> `task_mode = FILE`

## 11.2. Cac thanh phan nen giu

- `Task`
- `TaskAssignment`
- `TaskSubmission`
- `TaskComment`
- Co che phan quyen `assignment_scope_json`, `viewer_scope_json`, `manager_scope_json`

## 11.3. Cac thanh phan can doi vai tro

- `TaskItem`
  - Hien tai chua la dau muc trung tam
  - Can chuyen thanh thuc the dau muc de cuong that su

- `TaskParticipant`
  - Hien tai de trung lap vai tro voi `TaskAssignment`
  - De nghi giam vai tro hoac loai bo dan trong pha refactor

- `TaskReportLink`
  - Chi giu neu can lien ket thuc su voi he thong bao cao mau
  - Khong de no tro thanh duong re bat buoc cua phan he task

## 11.4. Cac doan logic can bo refactor

- Tao `child Task` hang loat tu outline
- Dung `report_schema_json` nhu mot cach chua du lieu tong hop cho tat ca cac dang task
- Dung `result_file` tren `TaskAssignment` lam noi luu file duy nhat

---

## 12. Lo trinh trien khai

## Pha 1: On dinh mo hinh `OUTLINE` va `FILE`

Muc tieu:
- Chot nghiep vu chinh
- Giam do phuc tap hien tai

Cong viec:
1. Them `task_mode`
2. Chinh UI tao task theo `OUTLINE` / `FILE`
3. Refactor `TaskItem` thanh dau muc de cuong that su
4. Them `task_item_id` vao `TaskAssignment` neu chua co dung nghia
5. Tach file nop sang bang file rieng hoac toi thieu tach service luu file
6. Chuyen dashboard child task thanh dashboard outline
7. Giu compatibility doc du lieu cu

## Pha 2: Hoan thien tong hop va xuat bao cao

Cong viec:
1. Ma tran tien do `don vi x dau muc`
2. Xuat Word tong hop
3. Tra lai bo sung
4. Lich su nop

## Pha 3: Mo rong `FORM`

Cong viec:
1. Form builder
2. Dynamic renderer
3. Export Excel
4. Dashboard tong hop

---

## 13. Bao mat va phan quyen

1. Khong nhan `unit_id` tu client de quyet dinh quyen truy cap.
2. Moi API don vi phai doi chieu tu `session` hoac token dang nhap.
3. Moi truy van chi tiet assignment phai kiem tra nguoi dung co nam trong pham vi assignment hay khong.
4. Download file phai qua endpoint co kiem tra quyen, khong expose duong dan vat ly.
5. File upload phai:
   - sanitize ten file
   - doi ten khi luu
   - gioi han duoi file
   - gioi han dung luong
   - co the bo sung scan virus neu ha tang cho phep

---

## 14. Tieu chi nghiem thu

Mot task `OUTLINE` dat khi:
- Admin tao duoc dot giao viec
- Import hoac nhap duoc de cuong
- Gan tung dau muc cho don vi
- Don vi nop noi dung theo tung muc
- Admin xem duoc ma tran tien do
- Admin xuat duoc van ban tong hop

Mot task `FILE` dat khi:
- Admin tao duoc task nop file
- Don vi nop duoc mo ta + tep
- He thong validate duoi file
- Admin tra lai bo sung duoc
- Don vi nop lai duoc
- He thong luu duoc lich su lan nop

Mot task `FORM` dat khi:
- Admin tao duoc field dong
- Don vi nhap duoc
- Du lieu tong hop xuat Excel duoc

---

## 15. Quyet dinh chot de trien khai

1. Chot mo hinh nghiep vu theo `task_mode`, khong theo `workflow_mode`.
2. Chot `TaskItem` la dau muc de cuong trung tam.
3. Chot `TaskAssignment` chi dong vai tro "giao cho ai".
4. Chot `TaskSubmission` la don vi nop bai va luu lich su nop.
5. Chot giai doan 1 chi trien khai day du `OUTLINE` va `FILE`.
6. Chot `FORM` la pha 2, nhung duoc du tru trong thiet ke ngay tu dau.
7. Chot huong refactor de tuong thich voi du lieu va code cu, khong viet moi hoan toan.

---

## 16. Kien nghi trien khai ky thuat

De giam rui ro, nen lam theo thu tu:

1. Them truong va service moi nhung chua xoa logic cu.
2. Mapping UI cu sang `task_mode`.
3. Refactor backend submit theo tang `assignment/submission`.
4. Chuyen dan dashboard tu `child task` sang `outline item`.
5. Sau khi du lieu moi on dinh moi tinh toi viec don dep bang va logic cu.

Tai lieu nay la ban thiet ke cuoi de doi phat trien bam vao khi thuc hien refactor va mo rong phan he `task`.
