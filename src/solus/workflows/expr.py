"""
Safe expression evaluator for workflow `when:` conditions.

Uses ast.parse() + a whitelist of safe AST node types to evaluate
simple boolean expressions against context data. No eval() used.
"""

from __future__ import annotations

import ast
import logging
import operator
from typing import Any

logger = logging.getLogger(__name__)

_SAFE_NODE_TYPES = (
    ast.Expression,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.UnaryOp,
    ast.Not,
    ast.Invert,
    ast.UAdd,
    ast.USub,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Is,
    ast.IsNot,
    ast.In,
    ast.NotIn,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Del,  # context markers on Name nodes
    ast.Constant,
    ast.IfExp,
    ast.List,
    ast.Tuple,
)

_CMP_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}


def _check_safe(node: ast.AST) -> None:
    if not isinstance(node, _SAFE_NODE_TYPES):
        raise ValueError(f"Unsafe AST node type in expression: {type(node).__name__}")
    for child in ast.iter_child_nodes(node):
        _check_safe(child)


def _eval_node(node: ast.AST, data: dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, data)

    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        # Resolve name against data dict; treat missing names as None
        name = node.id
        if name == "True":
            return True
        if name == "False":
            return False
        if name == "None":
            return None
        return data.get(name)

    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, data)
        if isinstance(node.op, ast.Not):
            return not operand
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return +operand
        if isinstance(node.op, ast.Invert):
            return ~operand
        raise ValueError(f"Unsupported unary op: {type(node.op).__name__}")

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result = True
            for value in node.values:
                result = _eval_node(value, data)
                if not result:
                    return result
            return result
        if isinstance(node.op, ast.Or):
            result = False
            for value in node.values:
                result = _eval_node(value, data)
                if result:
                    return result
            return result
        raise ValueError(f"Unsupported bool op: {type(node.op).__name__}")

    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, data)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_node(comparator, data)
            fn = _CMP_OPS.get(type(op))
            if fn is None:
                raise ValueError(f"Unsupported compare op: {type(op).__name__}")
            if not fn(left, right):
                return False
            left = right
        return True

    if isinstance(node, ast.IfExp):
        test = _eval_node(node.test, data)
        if test:
            return _eval_node(node.body, data)
        return _eval_node(node.orelse, data)

    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval_node(el, data) for el in node.elts]

    raise ValueError(f"Unhandled AST node type: {type(node).__name__}")


def evaluate_when(expr: str, data: dict[str, Any]) -> bool:
    """
    Safely evaluate a when-expression against context data.

    Returns True if the expression is truthy, False if falsy.
    On parse or eval error, returns True (fail-open: run the step anyway)
    and logs a warning.
    """
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        logger.warning("when: failed to parse expression %r: %s; running step anyway", expr, exc)
        return True

    try:
        _check_safe(tree)
    except ValueError as exc:
        logger.warning("when: unsafe expression %r: %s; running step anyway", expr, exc)
        return True

    try:
        result = _eval_node(tree, data)
        return bool(result)
    except Exception as exc:
        logger.warning("when: failed to evaluate %r: %s; running step anyway", expr, exc)
        return True
