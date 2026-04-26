from __future__ import annotations

import hashlib
import re

import sqlglot
from sqlglot import exp

from sqlscout.log import get_logger

_log = get_logger("fingerprinter")


def fingerprint_query(sql: str, dialect: str = "snowflake") -> tuple[str, str, list[str]]:
    try:
        return _fingerprint_via_ast(sql, dialect)
    except Exception as e:
        _log.debug("AST parse failed, falling back to regex: %s", e)
        return _fingerprint_via_regex(sql)


def _fingerprint_via_ast(sql: str, dialect: str) -> tuple[str, str, list[str]]:
    tree = sqlglot.parse_one(sql, dialect=dialect, error_level=sqlglot.ErrorLevel.RAISE)

    tables = _extract_tables(tree)

    tree = tree.transform(_replace_literals)

    alias_map = _build_alias_canonicalization(tree)
    tree = tree.transform(lambda n: _canonicalize_aliases(n, alias_map))
    tree = tree.transform(_strip_aliases)

    normalized = tree.sql(dialect=dialect, normalize=True, pretty=False)
    normalized = re.sub(r"\s+", " ", normalized).strip().upper()

    fp = hashlib.sha256(normalized.encode()).hexdigest()[:32]
    return fp, normalized, tables


def _fingerprint_via_regex(sql: str) -> tuple[str, str, list[str]]:
    normalized = sql.strip()
    normalized = re.sub(r"'(?:[^']|'')*'", "'?'", normalized)
    normalized = re.sub(r"\b\d+(\.\d+)?\b", "?", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = normalized.upper()

    fp = hashlib.sha256(normalized.encode()).hexdigest()[:32]
    return fp, normalized, []


def _replace_literals(node: exp.Expression) -> exp.Expression:
    if isinstance(node, exp.Literal):
        if node.is_string:
            return exp.Literal.string("?")
        return exp.Literal.number("?")
    return node


def _strip_aliases(node: exp.Expression) -> exp.Expression:
    if isinstance(node, exp.Alias):
        return node.this
    return node


def _build_alias_canonicalization(tree: exp.Expression) -> dict[str, str]:
    mapping: dict[str, str] = {}
    counter = 0
    for table in tree.find_all(exp.Table):
        alias = table.alias
        if alias and alias not in mapping:
            mapping[alias] = f"t{counter}"
            counter += 1
    return mapping


def _canonicalize_aliases(node: exp.Expression, mapping: dict[str, str]) -> exp.Expression:
    if not mapping:
        return node
    if isinstance(node, exp.Table) and node.alias and node.alias in mapping:
        node.set("alias", exp.TableAlias(this=exp.to_identifier(mapping[node.alias])))
    elif isinstance(node, exp.Column) and node.table:
        ref = str(node.table)
        if ref in mapping:
            node.set("table", exp.to_identifier(mapping[ref]))
    return node


def _extract_tables(tree: exp.Expression) -> list[str]:
    tables: list[str] = []
    for table in tree.find_all(exp.Table):
        parts = []
        if table.catalog:
            parts.append(table.catalog)
        if table.db:
            parts.append(table.db)
        if table.name:
            parts.append(table.name)
        if parts:
            tables.append(".".join(parts))
    return sorted(set(tables))
