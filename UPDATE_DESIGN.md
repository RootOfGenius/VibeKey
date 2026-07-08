# Co Che Cap Nhat Data

VibeKey du kien duoc build thanh file `.exe` va upload len GitHub Release/artifact.
Vi vay updater trong app khong nen cap nhat/de len file runtime nhu:

- `audition_chat_replace.py`
- file `.exe`
- source code khac

Updater chi nen cap nhat data:

- `audition_emoji_replace.json`
- `audition_stickers/**`
- co the cap nhat `app_metadata.json` neu chi thay `data_version`/URL update

Khong duoc de len:

- `audition_emoji_custom.json`

Day la mapping rieng cua nguoi dung.

## Version

Nen tach 2 loai version:

- `version`: version cua app/exe.
- `data_version`: version cua bo sticker/mapping.

Vi du trong `app_metadata.json`:

```json
{
  "version": "0.1.0",
  "data_version": "2026.07.09.1"
}
```

## Manifest Remote

App tai manifest tu GitHub raw URL:

```text
https://raw.githubusercontent.com/YOUR_NAME/YOUR_REPO/main/update_manifest.json
```

Manifest chi mo ta data update:

```json
{
  "latest_data_version": "2026.07.09.2",
  "data_zip_url": "https://github.com/YOUR_NAME/YOUR_REPO/releases/download/data-2026.07.09.2/vibekey-data.zip",
  "reload_required": true,
  "restart_required": false,
  "allowed_paths": [
    "audition_emoji_replace.json",
    "audition_stickers/"
  ]
}
```

## Luong Update

1. App doc `app_metadata.json`.
2. Neu `update.enabled = true`, app tai remote manifest.
3. So sanh `latest_data_version` voi `data_version` local.
4. Neu remote moi hon:
   - tai `data_zip_url` ve thu muc tam,
   - giai nen vao thu muc tam,
   - chi copy cac path nam trong `allowed_paths`,
   - backup data cu truoc khi copy,
   - khong copy `audition_emoji_custom.json`,
   - sau khi copy xong, reload JSON/sticker trong app.

## Goi ZIP Data

ZIP data nen co cau truc:

```text
audition_emoji_replace.json
audition_stickers/
  emoji_basic/
    01.png
    ...
  emoji_gau_chat/
    01.png
    ...
```

Neu update co thay doi file `.exe`, nen phat hanh app release moi thay vi dung data updater.
