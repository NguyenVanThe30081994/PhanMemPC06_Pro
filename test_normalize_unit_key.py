#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test normalize_unit_key() function
"""

from utils import normalize_unit_key

print("=" * 80)
print("TEST: normalize_unit_key() function")
print("=" * 80)

test_cases = [
    # (input, expected_output, description)
    ("Phòng Kế Hoạch", "phong ke hoach", "Vietnamese accents"),
    ("phòng kế hoạch", "phong ke hoach", "Lowercase with accents"),
    ("PHÒNG KỀ HOẠCH", "phong ke hoach", "Uppercase with accents"),
    ("PK", "pk", "Abbreviation"),
    ("Phòng Kế Hoạch", "phong ke hoach", "Mixed case"),
    ("  Phòng   Kế   Hoạch  ", "phong ke hoach", "Extra spaces"),
    ("Công An Xã An Tường", "cong an xa an tuong", "Multiple words"),
    ("công an xã an tường", "cong an xa an tuong", "Lowercase multiple words"),
    ("", "", "Empty string"),
    (None, "", "None value"),
    ("Đơn Vị A", "don vi a", "Simple unit"),
    ("đơn vị a", "don vi a", "Lowercase simple unit"),
]

passed = 0
failed = 0

for input_val, expected, description in test_cases:
    result = normalize_unit_key(input_val)
    status = "✓ PASS" if result == expected else "✗ FAIL"
    
    if result == expected:
        passed += 1
    else:
        failed += 1
    
    print(f"\n{status}: {description}")
    print(f"  Input:    {repr(input_val)}")
    print(f"  Expected: {repr(expected)}")
    print(f"  Got:      {repr(result)}")

print("\n" + "=" * 80)
print(f"Results: {passed} passed, {failed} failed out of {len(test_cases)} tests")
print("=" * 80)

if failed == 0:
    print("✓ All tests passed!")
else:
    print(f"✗ {failed} test(s) failed")
