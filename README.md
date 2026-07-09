# VibeKey

VibeKey là công cụ nhỏ giúp đổi phím tắt emoji trong Audition sang mã sticker tương ứng.

Ví dụ:

```text
;haha → &^_^&
```

## Tính năng

- Tự động thay phím tắt emoji trong ô chat Audition.
- Hỗ trợ nhiều bộ sticker.
- Xem trước sticker kèm key tương ứng.
- Cho phép tự thêm mapping riêng.
- Có thể cập nhật dữ liệu sticker/mapping mới từ GitHub.

## Cách sử dụng

1. Mở Audition.
2. Chạy `VibeKey.exe` bằng quyền Administrator.
3. Chọn bộ sticker ưu tiên nếu muốn.
4. Gõ key trong ô chat Audition, ví dụ:

```text
;haha
```

VibeKey sẽ tự đổi sang mã sticker tương ứng.

## Thêm mapping riêng

Ở phần tùy chỉnh, nhập:

- `Key`: phím tắt bạn muốn gõ, ví dụ `;cuoi`
- `Giá trị`: mã sticker muốn thay, ví dụ `&^_^&`

Sau đó bấm `Thêm custom`.

Mapping tự thêm sẽ được lưu riêng và không bị mất khi cập nhật dữ liệu.

## Cập nhật dữ liệu

Nếu có dữ liệu mới, VibeKey sẽ hiển thị nút `Update`.

Bấm `Update` để tải bộ sticker/mapping mới nhất. Dữ liệu custom của bạn vẫn được giữ lại.

## Lưu ý

- Nếu app báo chưa kết nối được game, hãy chuột phải vào `VibeKey.exe` và chọn `Run as administrator`.
- App chỉ hỗ trợ bản Audition có địa chỉ chat tương thích.
- Không cần cài Git hay Python nếu bạn dùng bản `.exe`.

## Dành cho người đóng góp data

Nếu bạn sửa sticker hoặc mapping bằng source, hãy bật hook trước khi commit:

```powershell
.\install_hooks.ps1
```

Hook này sẽ tự cập nhật `data_version` khi bạn commit thay đổi trong `audition_emoji_replace.json` hoặc `audition_stickers/`.
