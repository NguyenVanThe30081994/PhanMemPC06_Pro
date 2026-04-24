# Fix Summary: is_latest Column Missing Error

**Date**: 2026-04-23
**Error**: `sqlite3.OperationalError: no such column: report_data.is_latest`
**Status**: ✅ Code Fixed + Migration Script Ready

---

## 🔴 Root Cause

1. **Code was updated** in previous session to add `is_latest` column logic
2. **Production database NOT migrated** - still has old schema without `is_latest` column
3. **Previous fallback FAILED** - try/except was at wrong location (filter build vs query execution)

---

## ✅ What Was Fixed

### 1. Improved Fallback Logic in `routes/forms.py`

**Location**: Line 390-419 in `stats()` function

**Changes**:
- Moved try/except from filter-building to query execution (`.all()`)
- Created helper function `_build_v1_raw_query(use_is_latest=True)`
- Catches `OperationalError` when column doesn't exist
- Automatically falls back to query without `is_latest` filter
- Logs warning message for debugging

**Result**: 
- ✅ Page will work even if database not migrated yet
- ⚠️ May show duplicate/old data until migration is run

### 2. Created Migration Script

**File**: `migrate_add_is_latest.py`

**Features**:
- ✅ Checks if column already exists (idempotent)
- ✅ Adds `is_latest BOOLEAN DEFAULT 1` column
- ✅ Sets all existing records to `is_latest=1`
- ✅ Verifies migration success
- ✅ Detailed error messages
- ✅ Safe to run multiple times

### 3. Created Migration Instructions

**File**: `MIGRATION_INSTRUCTIONS.md`

Complete step-by-step guide in Vietnamese for running migration on production server.

---

## 📋 Action Items for Production

### CRITICAL - Must Do:

1. **Upload migration script to server**
   ```bash
   scp migrate_add_is_latest.py dea35688@pc06tuyenquang.net:/home/dea35688/domains/pc06tuyenquang.net/public_html/PhanMemPC06_Pro/
   ```

2. **SSH into server**
   ```bash
   ssh dea35688@pc06tuyenquang.net
   cd /home/dea35688/domains/pc06tuyenquang.net/public_html/PhanMemPC06_Pro/
   ```

3. **Run migration**
   ```bash
   python3 migrate_add_is_latest.py
   ```

4. **Restart application**
   ```bash
   touch tmp/restart.txt  # if using Passenger
   # OR
   sudo systemctl restart pc06_app  # if using systemd
   ```

5. **Verify fix**
   - Visit `/stats?rid=1`
   - Check logs for errors
   - Confirm no more `is_latest` errors

---

## 🔍 Technical Details

### Why Previous Fallback Failed

**Old Code** (lines 395-400):
```python
try:
    raw_query = raw_query.filter(ReportData.is_latest == True)
except:
    pass
```

**Problem**: SQLAlchemy builds the filter expression without checking if column exists. The error only happens when `.all()` executes the SQL.

**New Code** (lines 390-419):
```python
def _build_v1_raw_query(use_is_latest=True):
    q = (db.session.query(ReportData, User)
           .join(User, ReportData.user_id == User.id)
           .filter(ReportData.report_id == rid)
           .order_by(User.unit_area))
    if use_is_latest:
        q = q.filter(ReportData.is_latest == True)
    if not is_lead:
        q = q.filter(User.unit_area == user_unit)
    return q

try:
    raw = _build_v1_raw_query(use_is_latest=True).all()
except Exception as _exc:
    if 'is_latest' in str(_exc).lower() or 'no such column' in str(_exc).lower():
        db.session.rollback()
        logging.warning("ReportData.is_latest column missing — falling back")
        raw = _build_v1_raw_query(use_is_latest=False).all()
    else:
        raise
```

**Solution**: Wrap the `.all()` execution and catch the actual SQLite error.

---

## 📊 Migration SQL

```sql
-- Check if column exists
PRAGMA table_info(report_data);

-- Add column
ALTER TABLE report_data ADD COLUMN is_latest BOOLEAN DEFAULT 1;

-- Set existing records
UPDATE report_data SET is_latest = 1 WHERE is_latest IS NULL;
```

---

## ✅ Verification Checklist

After running migration:

- [ ] No more `sqlite3.OperationalError: no such column: report_data.is_latest` in logs
- [ ] Stats page loads without errors
- [ ] Only latest submissions shown in stats (no duplicates)
- [ ] New submissions properly mark old ones as `is_latest=False`
- [ ] Export functionality works correctly

---

## 🆘 If Migration Fails

1. **Check database file location**
   ```bash
   find /home/dea35688/domains/pc06tuyenquang.net/public_html/PhanMemPC06_Pro/ -name "*.db"
   ```

2. **Check permissions**
   ```bash
   ls -la *.db
   chmod 664 pc06_system.db  # if needed
   ```

3. **Manual migration** (if script fails)
   ```bash
   sqlite3 pc06_system.db
   > ALTER TABLE report_data ADD COLUMN is_latest BOOLEAN DEFAULT 1;
   > UPDATE report_data SET is_latest = 1;
   > .quit
   ```

4. **Fallback**: Code will still work (with degraded functionality) thanks to the improved fallback logic

---

## 📝 Notes

- Migration is **backward compatible** - old code will still work after migration
- Fallback code ensures **zero downtime** during migration
- Script is **idempotent** - safe to run multiple times
- All existing records will be marked as `is_latest=1` by default
