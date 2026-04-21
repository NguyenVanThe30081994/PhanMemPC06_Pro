-- Add missing columns to report_template_v3
ALTER TABLE report_template_v3 ADD COLUMN template_code VARCHAR(50);
ALTER TABLE report_template_v3 ADD COLUMN updated_at TIMESTAMP;

-- Add missing table report_template_field_v3
CREATE TABLE IF NOT EXISTS report_template_field_v3 (
    id INTEGER PRIMARY KEY,
    template_id INTEGER REFERENCES report_template_v3(id),
    field_code VARCHAR(100) NOT NULL,
    field_name VARCHAR(255),
    header_path TEXT,
    column_index INTEGER,
    data_type VARCHAR(20) DEFAULT 'text',
    editable BOOLEAN DEFAULT 1,
    required BOOLEAN DEFAULT 0,
    default_value TEXT,
    validation_rules TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Add missing columns to report_version_v3
ALTER TABLE report_version_v3 ADD COLUMN schema_json TEXT;
ALTER TABLE report_version_v3 ADD COLUMN excel_blob BLOB;
ALTER TABLE report_version_v3 ADD COLUMN header_row_count INTEGER DEFAULT 3;
ALTER TABLE report_version_v3 ADD COLUMN created_by VARCHAR(100);
ALTER TABLE report_version_v3 ADD COLUMN is_published BOOLEAN DEFAULT 0;

-- Add missing columns to report_submission_v3
ALTER TABLE report_submission_v3 ADD COLUMN unit_id VARCHAR(100) NOT NULL DEFAULT '';
ALTER TABLE report_submission_v3 ADD COLUMN period_id VARCHAR(50);
ALTER TABLE report_submission_v3 ADD COLUMN submitted_at TIMESTAMP;

-- Add missing columns to report_value_v3
ALTER TABLE report_value_v3 ADD COLUMN field_id INTEGER;
ALTER TABLE report_value_v3 ADD COLUMN field_code VARCHAR(100);

-- Create audit table if not exists
CREATE TABLE IF NOT EXISTS report_audit_v3 (
    id INTEGER PRIMARY KEY,
    submission_id INTEGER REFERENCES report_submission_v3(id),
    user_id INTEGER REFERENCES user(id),
    field_code VARCHAR(100),
    old_value TEXT,
    new_value TEXT,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_field_template ON report_template_field_v3(template_id);
CREATE INDEX IF NOT EXISTS idx_version_template ON report_version_v3(template_id);
CREATE INDEX IF NOT EXISTS idx_submission_version ON report_submission_v3(version_id);
CREATE INDEX IF NOT EXISTS idx_submission_unit ON report_submission_v3(unit_id);
CREATE INDEX IF NOT EXISTS idx_value_submission ON report_value_v3(submission_id);
CREATE INDEX IF NOT EXISTS idx_audit_submission ON report_audit_v3(submission_id);
