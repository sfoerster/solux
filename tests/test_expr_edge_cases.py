"""Tests for expression evaluator edge cases: unary ops, ternary, chained
comparisons, list/tuple literals, boolean short-circuit, and error handling."""

from __future__ import annotations

import pytest

from solus.workflows.expr import evaluate_when, _eval_node, _check_safe
import ast


# ---------------------------------------------------------------------------
# Unary operators
# ---------------------------------------------------------------------------

def test_unary_not_true() -> None:
    assert evaluate_when("not True", {}) is False


def test_unary_not_false() -> None:
    assert evaluate_when("not False", {}) is True


def test_unary_not_variable() -> None:
    assert evaluate_when("not x", {"x": 0}) is True
    assert evaluate_when("not x", {"x": 1}) is False


def test_unary_minus() -> None:
    tree = ast.parse("-x", mode="eval")
    result = _eval_node(tree, {"x": 5})
    assert result == -5


def test_unary_plus() -> None:
    tree = ast.parse("+x", mode="eval")
    result = _eval_node(tree, {"x": -3})
    assert result == -3


def test_unary_invert() -> None:
    tree = ast.parse("~x", mode="eval")
    result = _eval_node(tree, {"x": 0})
    assert result == ~0


# ---------------------------------------------------------------------------
# Boolean short-circuit (and / or)
# ---------------------------------------------------------------------------

def test_and_short_circuit_false() -> None:
    assert evaluate_when("False and True", {}) is False


def test_and_all_true() -> None:
    assert evaluate_when("True and True", {}) is True


def test_and_with_variables() -> None:
    assert evaluate_when("a and b", {"a": 1, "b": 2}) is True
    assert evaluate_when("a and b", {"a": 0, "b": 2}) is False


def test_or_short_circuit_true() -> None:
    assert evaluate_when("True or False", {}) is True


def test_or_all_false() -> None:
    assert evaluate_when("False or False", {}) is False


def test_or_with_variables() -> None:
    assert evaluate_when("a or b", {"a": 0, "b": 0}) is False
    assert evaluate_when("a or b", {"a": 0, "b": 1}) is True


def test_and_or_combined() -> None:
    assert evaluate_when("a and b or c", {"a": 1, "b": 0, "c": 1}) is True
    assert evaluate_when("a and b or c", {"a": 1, "b": 0, "c": 0}) is False


# ---------------------------------------------------------------------------
# Chained comparisons
# ---------------------------------------------------------------------------

def test_chained_comparison_true() -> None:
    assert evaluate_when("1 < x < 10", {"x": 5}) is True


def test_chained_comparison_false() -> None:
    assert evaluate_when("1 < x < 10", {"x": 15}) is False


def test_chained_comparison_equal() -> None:
    assert evaluate_when("1 <= x <= 5", {"x": 5}) is True
    assert evaluate_when("1 <= x <= 5", {"x": 0}) is False


def test_chained_comparison_three_ops() -> None:
    assert evaluate_when("0 < a < b < 100", {"a": 10, "b": 20}) is True
    assert evaluate_when("0 < a < b < 100", {"a": 10, "b": 5}) is False


# ---------------------------------------------------------------------------
# Ternary (IfExp)
# ---------------------------------------------------------------------------

def test_ternary_true_branch() -> None:
    tree = ast.parse("'yes' if x else 'no'", mode="eval")
    _check_safe(tree)
    result = _eval_node(tree, {"x": True})
    assert result == "yes"


def test_ternary_false_branch() -> None:
    tree = ast.parse("'yes' if x else 'no'", mode="eval")
    result = _eval_node(tree, {"x": False})
    assert result == "no"


def test_ternary_in_when() -> None:
    # When used in evaluate_when, the result is coerced to bool
    assert evaluate_when("'yes' if x else ''", {"x": True}) is True
    assert evaluate_when("'yes' if x else ''", {"x": False}) is False


# ---------------------------------------------------------------------------
# List / Tuple literals
# ---------------------------------------------------------------------------

def test_list_literal() -> None:
    tree = ast.parse("[1, 2, 3]", mode="eval")
    _check_safe(tree)
    result = _eval_node(tree, {})
    assert result == [1, 2, 3]


def test_tuple_literal() -> None:
    tree = ast.parse("(1, 2)", mode="eval")
    _check_safe(tree)
    result = _eval_node(tree, {})
    assert result == [1, 2]  # tuples also return lists


def test_empty_list() -> None:
    tree = ast.parse("[]", mode="eval")
    result = _eval_node(tree, {})
    assert result == []


def test_in_with_list_literal() -> None:
    assert evaluate_when("x in [1, 2, 3]", {"x": 2}) is True
    assert evaluate_when("x in [1, 2, 3]", {"x": 9}) is False


def test_not_in_with_list() -> None:
    assert evaluate_when("x not in ['a', 'b']", {"x": "c"}) is True
    assert evaluate_when("x not in ['a', 'b']", {"x": "a"}) is False


# ---------------------------------------------------------------------------
# None literal
# ---------------------------------------------------------------------------

def test_none_literal() -> None:
    tree = ast.parse("None", mode="eval")
    result = _eval_node(tree, {})
    assert result is None


def test_is_none() -> None:
    assert evaluate_when("x is None", {"x": None}) is True
    assert evaluate_when("x is None", {"x": 42}) is False


def test_is_not_none() -> None:
    assert evaluate_when("x is not None", {"x": 42}) is True
    assert evaluate_when("x is not None", {}) is False  # missing key → None


# ---------------------------------------------------------------------------
# Error handling / fail-open
# ---------------------------------------------------------------------------

def test_syntax_error_returns_true() -> None:
    """Malformed expressions should fail-open (return True)."""
    assert evaluate_when("if then what???", {}) is True


def test_unsafe_node_returns_true() -> None:
    """Expressions with disallowed AST nodes should fail-open."""
    assert evaluate_when("__import__('os')", {}) is True


def test_eval_error_returns_true() -> None:
    """Runtime errors during evaluation should fail-open."""
    # ~"hello" will raise TypeError
    assert evaluate_when("~x", {"x": "hello"}) is True


def test_missing_variable_is_none() -> None:
    """Undefined variables should resolve to None, not raise."""
    assert evaluate_when("missing_var is None", {}) is True


# ---------------------------------------------------------------------------
# Safety check
# ---------------------------------------------------------------------------

def test_check_safe_rejects_call() -> None:
    tree = ast.parse("print(1)", mode="eval")
    with pytest.raises(ValueError, match="Unsafe AST node"):
        _check_safe(tree)


def test_check_safe_rejects_attribute() -> None:
    tree = ast.parse("x.y", mode="eval")
    with pytest.raises(ValueError, match="Unsafe AST node"):
        _check_safe(tree)


def test_check_safe_rejects_subscript() -> None:
    tree = ast.parse("x[0]", mode="eval")
    with pytest.raises(ValueError, match="Unsafe AST node"):
        _check_safe(tree)
