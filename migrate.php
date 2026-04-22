<?php
/**
 * Migration script cho V3 schema - chạy qua web
 * URL: https://pc06tuyenquang.net/migrate.php
 */
header('Content-Type: text/plain; charset=utf-8');

$db_file = __DIR__ . '/pc06_system.db';
if (!file_exists($db_file)) {
    die("Khong tim thay database: $db_file\n");
}

echo "Database: $db_file\n";

try {
    $db = new PDO("sqlite:$db_file");
    $db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    
    // Check table structure
    $tables = ['report_template_v3', 'report_template_field_v3', 'report_version_v3', 
               'report_submission_v3', 'report_value_v3', 'report_audit_v3'];
    
    foreach ($tables as $table) {
        echo "\n=== $table ===\n";
        
        // Create table if not exists
        if ($table === 'report_template_field_v3') {
            $db->exec("
                CREATE TABLE IF NOT EXISTS report_template_field_v3 (
                    id INTEGER PRIMARY KEY,
                    template_id INTEGER,
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
                )
            ");
            echo "Created $table\n";
        }
        elseif ($table === 'report_audit_v3') {
            $db->exec("
                CREATE TABLE IF NOT EXISTS report_audit_v3 (
                    id INTEGER PRIMARY KEY,
                    submission_id INTEGER,
                    user_id INTEGER,
                    field_code VARCHAR(100),
                    old_value TEXT,
                    new_value TEXT,
                    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ");
            echo "Created $table\n";
        }
        else {
            // Get current columns
            $stmt = $db->query("PRAGMA table_info($table)");
            $cols = $stmt->fetchAll(PDO::FETCH_COLUMN, 1);
            echo "Current columns: " . implode(', ', $cols) . "\n";
            
            // Add missing columns based on table
            $add_cols = [];
            if ($table === 'report_template_v3') {
                $add_cols = [
                    'template_code' => 'VARCHAR(50)',
                    'updated_at' => 'TIMESTAMP'
                ];
            }
            elseif ($table === 'report_version_v3') {
                $add_cols = [
                    'schema_json' => 'TEXT',
                    'excel_blob' => 'BLOB',
                    'header_row_count' => 'INTEGER DEFAULT 3',
                    'created_by' => 'VARCHAR(100)',
                    'is_published' => 'BOOLEAN DEFAULT 0'
                ];
            }
            elseif ($table === 'report_submission_v3') {
                $add_cols = [
                    'unit_id' => 'VARCHAR(100)',
                    'period_id' => 'VARCHAR(50)',
                    'submitted_at' => 'TIMESTAMP'
                ];
            }
            elseif ($table === 'report_value_v3') {
                $add_cols = [
                    'field_id' => 'INTEGER',
                    'field_code' => 'VARCHAR(100)'
                ];
            }
            
            foreach ($add_cols as $col => $type) {
                if (!in_array($col, $cols)) {
                    $db->exec("ALTER TABLE $table ADD COLUMN $col $type");
                    echo "Added column: $col\n";
                }
            }
        }
    }
    
    echo "\n=== Migration Complete ===\n";
    
    // Verify
    $stmt = $db->query("PRAGMA table_info(report_template_v3)");
    $cols = $stmt->fetchAll(PDO::FETCH_COLUMN, 1);
    echo "report_template_v3 columns: " . implode(', ', $cols) . "\n";
    
}
catch(PDOException $e) {
    die("Error: " . $e->getMessage() . "\n");
}
