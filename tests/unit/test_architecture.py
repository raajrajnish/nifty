"""Static checks for MASTER_PLAN §15 separation rules (backs up import-linter)."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "tradingagent"
GROWW_ALLOWED = {"broker/groww_adapter.py", "broker/auth.py"}
PLACE_ORDER_ALLOWED = {"execution/executor.py", "broker/base.py", "broker/groww_adapter.py",
                       "broker/paper_broker.py", "sim/fills.py"}


def _modules():
    for p in SRC.rglob("*.py"):
        yield p.relative_to(SRC).as_posix(), ast.parse(p.read_text(encoding="utf-8"))


def test_growwapi_only_imported_in_broker():
    offenders = []
    for rel, tree in _modules():
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            if any(n.split(".")[0] == "growwapi" for n in names) and rel not in GROWW_ALLOWED:
                offenders.append(rel)
    assert offenders == []


def test_place_order_only_called_from_executor():
    offenders = []
    for rel, tree in _modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "place_order" and rel not in PLACE_ORDER_ALLOWED:
                offenders.append(rel)
    assert offenders == []


def test_ui_and_agent_never_import_broker():
    offenders = []
    for rel, tree in _modules():
        if not rel.startswith(("ui/", "agent/", "tools/")):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("tradingagent.broker"):
                offenders.append(rel)
    assert offenders == []
