# -*- coding: utf-8 -*-
"""
Lightweight Excel formula evaluator for report preview rendering.

This is not a full spreadsheet engine. It exists so the web UI can display
common template formulas after user data is written into the workbook.
"""

import ast
import operator as op
import re


_CELL_REF_RE = re.compile(
    r"(?<![A-Za-z0-9_'\"])"
    r"((?:'[^']+'|[A-Za-z_][A-Za-z0-9_ ]*)!)?"
    r"(\$?[A-Z]{1,3}\$?\d+)"
)


class _SafeExpressionEvaluator(ast.NodeVisitor):
    _bin_ops = {
        ast.Add: op.add,
        ast.Sub: op.sub,
        ast.Mult: op.mul,
        ast.Div: op.truediv,
        ast.FloorDiv: op.floordiv,
        ast.Mod: op.mod,
        ast.Pow: op.pow,
    }
    _unary_ops = {
        ast.UAdd: op.pos,
        ast.USub: op.neg,
    }

    def visit_Expression(self, node):
        return self.visit(node.body)

    def visit_Constant(self, node):
        if isinstance(node.value, (int, float, str)):
            return node.value
        raise ValueError("Unsupported constant")

    def visit_BinOp(self, node):
        operator = self._bin_ops.get(type(node.op))
        if not operator:
            raise ValueError("Unsupported operator")
        return operator(self.visit(node.left), self.visit(node.right))

    def visit_UnaryOp(self, node):
        operator = self._unary_ops.get(type(node.op))
        if not operator:
            raise ValueError("Unsupported unary operator")
        return operator(self.visit(node.operand))

    def generic_visit(self, node):
        raise ValueError(f"Unsupported expression element: {type(node).__name__}")


class ExcelFormulaEngine:
    def __init__(self, workbook):
        self.workbook = workbook
        self._cache = {}
        self._stack = set()

    @staticmethod
    def _strip_dollar(value):
        return str(value or "").replace("$", "")

    @staticmethod
    def _split_args(raw_args):
        args = []
        current = []
        depth = 0
        in_string = False

        for ch in raw_args:
            if ch == '"':
                in_string = not in_string
                current.append(ch)
                continue
            if not in_string:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                elif ch == "," and depth == 0:
                    args.append("".join(current).strip())
                    current = []
                    continue
            current.append(ch)

        tail = "".join(current).strip()
        if tail:
            args.append(tail)
        return args

    @staticmethod
    def _coerce_number(value):
        if value in (None, ""):
            return 0
        if isinstance(value, (int, float)):
            return value
        raw = str(value).strip().replace(",", "")
        if raw == "":
            return 0
        return float(raw)

    def _resolve_sheet_and_ref(self, token, current_sheet):
        token = str(token or "").strip()
        if "!" in token:
            sheet_name, ref = token.rsplit("!", 1)
            sheet_name = sheet_name.strip()
            if sheet_name.startswith("'") and sheet_name.endswith("'"):
                sheet_name = sheet_name[1:-1].replace("''", "'")
        else:
            sheet_name, ref = current_sheet.title, token
        return self.workbook[sheet_name], self._strip_dollar(ref)

    def _iter_range_values(self, token, current_sheet):
        worksheet, range_ref = self._resolve_sheet_and_ref(token, current_sheet)
        if ":" not in range_ref:
            return [self.evaluate_cell(worksheet, range_ref)]

        from openpyxl.utils.cell import range_boundaries

        min_col, min_row, max_col, max_row = range_boundaries(range_ref)
        values = []
        for row in range(min_row, max_row + 1):
            for col in range(min_col, max_col + 1):
                values.append(self.evaluate_cell(worksheet, worksheet.cell(row=row, column=col).coordinate))
        return values

    def _literal_for_ref(self, match, current_sheet):
        sheet_prefix = match.group(1) or ""
        cell_ref = match.group(2)
        token = f"{sheet_prefix}{cell_ref}"
        value = self.evaluate_cell(*self._resolve_sheet_and_ref(token, current_sheet))
        if value in (None, ""):
            return "0"
        if isinstance(value, str):
            try:
                return str(float(value.replace(",", "").strip()))
            except Exception:
                return repr(value)
        return repr(value)

    def _eval_sum(self, worksheet, raw_args):
        total = 0
        for arg in self._split_args(raw_args):
            for value in self._iter_range_values(arg, worksheet):
                total += self._coerce_number(value)
        return total

    def _eval_iferror(self, worksheet, raw_args):
        args = self._split_args(raw_args)
        if len(args) != 2:
            raise ValueError("IFERROR requires 2 arguments")
        try:
            return self.evaluate_formula(worksheet, args[0])
        except Exception:
            return self.evaluate_formula(worksheet, args[1])

    def evaluate_formula(self, worksheet, formula):
        expression = str(formula or "").strip()
        if expression.startswith("="):
            expression = expression[1:].strip()

        if expression == "":
            return ""

        if expression.startswith('"') and expression.endswith('"'):
            return expression[1:-1]

        if re.fullmatch(r"-?\d+(?:\.\d+)?", expression):
            return float(expression) if "." in expression else int(expression)

        upper = expression.upper()
        if upper.startswith("SUM(") and expression.endswith(")"):
            return self._eval_sum(worksheet, expression[4:-1])
        if upper.startswith("IFERROR(") and expression.endswith(")"):
            return self._eval_iferror(worksheet, expression[8:-1])

        replaced = _CELL_REF_RE.sub(lambda match: self._literal_for_ref(match, worksheet), expression)
        replaced = replaced.replace("^", "**")
        tree = ast.parse(replaced, mode="eval")
        return _SafeExpressionEvaluator().visit(tree)

    def evaluate_cell(self, worksheet, cell_ref):
        cell = worksheet[cell_ref] if isinstance(cell_ref, str) else cell_ref
        cache_key = (worksheet.title, cell.coordinate)
        if cache_key in self._cache:
            return self._cache[cache_key]
        if cache_key in self._stack:
            raise ValueError(f"Circular reference detected at {worksheet.title}!{cell.coordinate}")

        raw_value = cell.value
        if not (isinstance(raw_value, str) and raw_value.startswith("=")) and cell.data_type != "f":
            self._cache[cache_key] = raw_value
            return raw_value

        self._stack.add(cache_key)
        try:
            result = self.evaluate_formula(worksheet, raw_value)
            self._cache[cache_key] = result
            return result
        finally:
            self._stack.discard(cache_key)
