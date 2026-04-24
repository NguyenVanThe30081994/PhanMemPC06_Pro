#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script để kiểm tra hàm format_excel_number
"""

from excel_renderer import format_excel_number

# Test cases
test_cases = [
    # (value, number_format, expected_output, description)
    (491, '0', '491', 'Integer format'),
    (491.14, '0', '491', 'Float to integer'),
    (491.14, '0.00', '491.14', 'Two decimal places'),
    (491.1, '0.0', '491.1', 'One decimal place'),
    (0.5, '0%', '50%', 'Percentage'),
    (0.125, '0.0%', '12.5%', 'Percentage with 1 decimal'),
    (0.1234, '0.00%', '12.34%', 'Percentage with 2 decimals'),
    (1234.56, '#,##0', '1,235', 'Thousand separator, no decimals'),
    (1234.56, '#,##0.00', '1,234.56', 'Thousand separator with decimals'),
    (543, '0', '543', 'Another integer'),
    (543.11, '0.00', '543.11', 'Another float'),
    (3441, '0', '3441', 'Large integer'),
    (3441.6, '0.0', '3441.6', 'Large float with 1 decimal'),
    (None, '0', '', 'None value'),
    ('', '0', '', 'Empty string'),
    ('text', '0', 'text', 'Text value'),
]

print("=" * 80)
print("TEST: format_excel_number function")
print("=" * 80)

passed = 0
failed = 0

for value, fmt, expected, description in test_cases:
    result = format_excel_number(value, fmt)
    status = "✓ PASS" if result == expected else "✗ FAIL"
    
    if result == expected:
        passed += 1
    else:
        failed += 1
    
    print(f"\n{status}: {description}")
    print(f"  Input:    value={value}, format={fmt}")
    print(f"  Expected: {expected}")
    print(f"  Got:      {result}")

print("\n" + "=" * 80)
print(f"Results: {passed} passed, {failed} failed out of {len(test_cases)} tests")
print("=" * 80)

if failed == 0:
    print("✓ All tests passed!")
else:
    print(f"✗ {failed} test(s) failed")
