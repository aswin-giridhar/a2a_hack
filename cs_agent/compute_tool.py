"""Deterministic calculator tool (NO LLM) for exact money / points / fee math.

The largest failure bucket was wrong NUMERIC arguments (refund 24.50 vs 27.00,
points 1499 vs 1500) — the model doing arithmetic in its head. This tool lets
the agent offload all arithmetic to exact, deterministic evaluation. It is a
plain local function: no model call, no network, no model-lock concern, and
negligible latency, so it cannot affect the 5-min/turn or 10-min/task budget.
Only +-*/%, **, parentheses, and numbers are allowed (safe AST eval — no names,
calls, or attribute access).
"""

import ast
import operator

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("only numbers and + - * / % ** ( ) are allowed")


def compute(expression: str) -> dict:
    """Evaluate an arithmetic expression EXACTLY. Use this for ALL money, fee,
    refund, reward-point, percentage, and total calculations — never compute
    these by hand, as small arithmetic slips produce wrong tool arguments.

    Args:
        expression: An arithmetic expression, e.g. "(27.00 + 8.00 + 4.75) * 0.5"
            or "1500 - 1" or "250 * 0.025". Only numbers and + - * / % ** ( ).

    Returns:
        {"result": <number>} on success, or {"error": "..."} if it can't parse.
    """
    try:
        value = _eval(ast.parse(expression, mode="eval").body)
        # Keep currency clean: round float noise to 4 dp, drop trailing .0
        if isinstance(value, float):
            value = round(value, 4)
            if value == int(value):
                value = int(value) if value == int(value) and "." not in expression else value
        return {"result": value}
    except Exception as e:
        return {"error": f"could not evaluate {expression!r}: {e}"}
