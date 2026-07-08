# VibeKey

VibeKey la tool nho cho Audition, tu dong doi phim tat emoji trong o chat sang ma sticker tuong ung.

Vi du:

```text
;haha -> &^_^&
```

## Chay App Tu Source

Mo PowerShell bang quyen Administrator:

```powershell
cd E:\DragonBankin\VibeKey
python audition_chat_replace.py
```

Khi build thanh `.exe`, nguoi dung chi can chay file exe bang quyen Administrator.

## Cau Truc Data

Mapping chinh nam trong:

```text
audition_emoji_replace.json
```

Moi pack co dang:

```json
{
  "emoji_basic": {
    "label": "Emoji co ban",
    "data": {
      ";haha": "&^_^&"
    }
  }
}
```

Mapping nguoi dung tu them se duoc ghi vao:

```text
audition_emoji_custom.json
```

File nay duoc ignore khoi Git de tranh ghi de du lieu rieng cua nguoi dung.

## Metadata

Ten app, mo ta, app version, data version va icon nam trong:

```text
app_metadata.json
```

`version` la version cua app/exe.
`data_version` la version cua bo sticker/mapping.

## Sticker

Icon sticker nam trong:

```text
audition_stickers/<pack_key>/
```

Ten file icon theo thu tu:

```text
01.png, 02.png, ... 40.png
```

Thu tu icon tuong ung voi thu tu key trong `data`.

## Update

Updater trong app chi nen cap nhat data:

- `audition_emoji_replace.json`
- `audition_stickers/**`

Khong nen dung updater data de thay file `.py` hoac `.exe`.
Neu app/exe thay doi, hay phat hanh GitHub Release moi.
