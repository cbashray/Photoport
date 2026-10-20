# Google Photos API Feasibility Report — PhotoPort

**Last Updated:** October 2026  
**Status:** VIABLE with documented limitations

---

## 1. Can a Desktop Application Upload Media to Google Photos?

**YES.** The Google Photos Library API supports uploading new media items into a user's
personal Google Photos library. Desktop applications can use the **OAuth 2.0 Installed
Application (Desktop)** flow via `InstalledAppFlow.run_local_server()`.

---

## 2. Supported OAuth Scopes

| Scope | Status | Purpose |
|-------|--------|---------|
| `photoslibrary.appendonly` | **Active** | Upload media, create albums, add items to app-created albums |
| `photoslibrary.readonly.appcreateddata` | **Active** | Read/list media items and albums created by the app |
| `photoslibrary` | **REMOVED** (March 2025) | Former broad read/write — no longer functional |
| `photoslibrary.readonly` | **REMOVED** (March 2025) | Former broad read — no longer functional |
| `photoslibrary.sharing` | **REMOVED** (March 2025) | Former sharing scope — no longer functional |

**PhotoPort will use:**
- `photoslibrary.appendonly` — for uploading media and creating albums
- `photoslibrary.readonly.appcreateddata` — for verifying uploaded items
- `drive.readonly` — for checking storage quota (via Google Drive API)

---

## 3. Upload Workflow

The upload is a **two-step process**:

### Step 1: Upload Raw Bytes
```
POST https://photoslibrary.googleapis.com/v1/uploads
Headers:
  Authorization: Bearer {access_token}
  Content-type: application/octet-stream
  X-Goog-Upload-Content-Type: {mime_type}
  X-Goog-Upload-Protocol: raw
Body: raw file bytes
Response: upload token (plain text string)
```

### Step 2: Create Media Item via `batchCreate`
```
POST https://photoslibrary.googleapis.com/v1/mediaItems:batchCreate
Body:
{
  "albumId": "optional_album_id",
  "newMediaItems": [{
    "description": "optional description (max 1000 chars)",
    "simpleMediaItem": {
      "uploadToken": "token_from_step_1",
      "fileName": "original_filename.jpg"
    }
  }]
}
```

**Upload tokens expire after a period** — the application must call `batchCreate`
promptly after uploading bytes.

---

## 4. Supported File Types and Size Limits

### Photos
| Formats | Max Size |
|---------|----------|
| AVIF, BMP, GIF, HEIC, ICO, JPG/JPEG, PNG, TIFF, WEBP, select RAW | **200 MB** |

### Videos
| Formats | Max Size |
|---------|----------|
| 3GP, 3G2, ASF, AVI, DIVX, M2T, M2TS, M4V, MKV, MMV, MOD, MOV, MP4, MPG, MTS, TOD, WMV | **20 GB** |

---

## 5. Original Quality Preservation

**All media uploaded via the API is stored at original quality.** Uploads count against
the user's Google Account storage quota.

- The API stores the original bytes as uploaded.
- Google Photos may generate its own thumbnails and derivatives but preserves the original.
- EXIF metadata embedded in files is preserved and used by Google Photos (e.g., `DateTimeOriginal`).
- The API itself does not provide byte-level download verification of the uploaded file.

> [!IMPORTANT]
> If the Takeout archive contains "Storage Saver" quality files (previously called
> "High Quality"), those are already compressed. PhotoPort preserves whatever is in the
> archive but cannot recover original camera files from pre-compressed exports.

---

## 6. Metadata Capabilities

| Metadata | Support | Method |
|----------|---------|--------|
| **File name** | ✅ Supported | `simpleMediaItem.fileName` in `batchCreate` |
| **Description** | ✅ Supported | `description` field in `batchCreate` (max 1000 chars) |
| **Capture date/time** | ⚠️ Indirect | Google reads EXIF `DateTimeOriginal` from the file bytes |
| **GPS/Location** | ⚠️ Indirect | Google reads EXIF GPS tags from the file bytes |
| **Album membership** | ✅ Supported | Via `albumId` in `batchCreate` or `batchAddMediaItems` |
| **Arbitrary creation time override** | ❌ Not supported | Cannot set via API; must be in EXIF |

### EXIF Timestamp Strategy
For photos lacking EXIF data but having timestamps in Takeout JSON sidecars, PhotoPort
can **optionally** inject EXIF `DateTimeOriginal` before upload using `piexif` or similar.
This is the only documented method to set correct dates. This modification will be:
- Opt-in (configurable)
- Logged
- Applied to a temporary copy, never the source file
- Documented as a metadata-only change that does not alter image quality

---

## 7. Album Handling

| Capability | Status |
|------------|--------|
| Create new albums | ✅ Supported |
| Add uploaded items to app-created albums | ✅ Supported |
| Add items to user's pre-existing albums | ❌ NOT supported |
| Recreate album titles from Takeout | ✅ Supported |
| Shared albums | ❌ Cannot recreate sharing settings |
| Album descriptions | ❌ Not supported by API |
| Album cover photo | ❌ Not settable via API |
| Nested albums/folders | ❌ Google Photos has no folder hierarchy |

> [!WARNING]
> Albums created by PhotoPort are "app-created albums." They appear in the user's Google
> Photos but cannot be modified by other applications. The user can interact with them
> normally through the Google Photos UI.

---

## 8. Storage Quota Checking

The Google Photos API **does not** provide a storage quota endpoint.

**Workaround:** Use the Google Drive API `about.get` endpoint:
```
GET https://www.googleapis.com/drive/v3/about?fields=storageQuota
```
Response:
```json
{
  "storageQuota": {
    "limit": "214748364800",
    "usage": "53687091200",
    "usageInDrive": "10737418240",
    "usageInDriveTrash": "0"
  }
}
```

This returns **total** Google account storage (shared across Drive, Gmail, and Photos).
The `usage` figure is the combined total. Available space = `limit` - `usage`.

**Requires scope:** `drive.readonly`

---

## 9. API Quotas and Rate Limits

| Quota | Limit |
|-------|-------|
| Library API requests per project per day | **10,000** |
| Photo bytes read requests per project per day | **75,000** |
| batchCreate items per request | **50** |

### Implications for 45 GB Migration
- Assuming ~15,000 photos/videos: requires ~15,000 upload requests + ~300 batchCreate requests
- At 10,000 requests/day, a large migration may span **2+ days**
- PhotoPort must implement daily quota tracking and graceful pausing

> [!IMPORTANT]
> The upload bytes endpoint (`/v1/uploads`) may be counted separately from Library API
> requests. Exact quota treatment should be validated during integration testing. If both
> count toward the 10,000/day limit, a 15,000-item migration requires ~2 days minimum.

---

## 10. Developer Setup Requirements

| Requirement | Details |
|-------------|---------|
| Google Cloud Project | Required — create at console.cloud.google.com |
| Photos Library API | Must be enabled in the project |
| Google Drive API | Must be enabled (for storage quota checks) |
| OAuth Consent Screen | Must be configured (External, Testing mode) |
| OAuth Client ID | Desktop Application type |
| `credentials.json` | Downloaded from Cloud Console, provided to app |
| App Verification | NOT required for personal use (<100 users in Testing mode) |

### Testing Mode Limitations
- Maximum 100 test users can be added manually
- Users see "This app isn't verified" warning during auth
- For personal migration use, this is acceptable
- Publishing to production requires Google verification review

---

## 11. Verification of Uploaded Items

| Method | Feasibility |
|--------|-------------|
| Check `batchCreate` response for `mediaItem.id` | ✅ Yes |
| Read back app-created media via `readonly.appcreateddata` | ✅ Yes |
| Compare file size of uploaded item | ⚠️ Partial — API returns media metadata |
| Byte-for-byte comparison of uploaded file | ❌ Not possible via API |
| Verify EXIF preservation | ⚠️ Limited metadata returned |

PhotoPort will verify uploads by:
1. Checking `batchCreate` response status for each item
2. Confirming returned `mediaItem.id` is non-null
3. Optionally reading back app-created items to confirm existence
4. Recording all results in the migration ledger
5. Flagging items that received ambiguous responses for manual review

---

## 12. Resumable Uploads

The Google Photos upload endpoint supports only the `raw` upload protocol for simple
uploads. **Resumable uploads** (for very large files) use a different protocol:

```
X-Goog-Upload-Protocol: resumable
```

For files > 100 MB (large videos), PhotoPort should use resumable uploads where supported.
This allows recovery from network interruptions without re-uploading the entire file.

---

## 13. Known Limitations Summary

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| Cannot add to pre-existing albums | Albums are recreated, not merged | Document in migration report |
| Cannot set capture date via API | Dates must be in EXIF | Optional EXIF injection from sidecar |
| No storage quota in Photos API | Must use Drive API | Add `drive.readonly` scope |
| 10,000 API requests/day limit | Large migrations span days | Track quota, auto-pause, resume |
| No byte-level download verification | Cannot prove bit-perfect upload | Verify via API response + metadata |
| Cannot recreate shared albums | Sharing settings lost | Document in report |
| "Unverified app" warning | Users see scary consent screen | Document in setup guide |
| Upload tokens expire | Must batchCreate promptly | Upload and create in tight sequence |

---

## 14. Conclusion

The Google Photos Library API **supports the core PhotoPort use case**: uploading original-
quality media from Takeout archives into a personal Google Photos library, with album
recreation and metadata preservation through EXIF data.

The migration is **feasible** with the following caveats:
1. Large migrations (>10,000 items) will require multi-day execution due to API quotas
2. Album recreation creates new app-owned albums, not modifications to existing ones
3. Capture dates require EXIF data in the files (or optional injection from sidecar JSON)
4. Storage must be checked via the Drive API, not Photos API
5. Byte-level upload verification is not possible; verification relies on API responses

**Recommendation:** Proceed with implementation.
