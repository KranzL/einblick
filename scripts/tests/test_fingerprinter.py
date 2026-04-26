from sqlscout.fingerprinter import fingerprint_query


class TestFingerprintIdenticalPatterns:
    def test_different_literals_same_fingerprint(self):
        q1 = "SELECT * FROM orders WHERE id = 1"
        q2 = "SELECT * FROM orders WHERE id = 9999"
        fp1, _, _ = fingerprint_query(q1)
        fp2, _, _ = fingerprint_query(q2)
        assert fp1 == fp2

    def test_different_string_literals_same_fingerprint(self):
        q1 = "SELECT * FROM users WHERE name = 'alice'"
        q2 = "SELECT * FROM users WHERE name = 'bob'"
        fp1, _, _ = fingerprint_query(q1)
        fp2, _, _ = fingerprint_query(q2)
        assert fp1 == fp2

    def test_different_case_same_fingerprint(self):
        q1 = "select * from orders where status = 'active'"
        q2 = "SELECT * FROM ORDERS WHERE STATUS = 'active'"
        fp1, _, _ = fingerprint_query(q1)
        fp2, _, _ = fingerprint_query(q2)
        assert fp1 == fp2

    def test_different_whitespace_same_fingerprint(self):
        q1 = "SELECT  *   FROM   orders   WHERE  id = 1"
        q2 = "SELECT * FROM orders WHERE id = 1"
        fp1, _, _ = fingerprint_query(q1)
        fp2, _, _ = fingerprint_query(q2)
        assert fp1 == fp2


class TestFingerprintDifferentPatterns:
    def test_different_tables_different_fingerprint(self):
        q1 = "SELECT * FROM orders WHERE id = 1"
        q2 = "SELECT * FROM customers WHERE id = 1"
        fp1, _, _ = fingerprint_query(q1)
        fp2, _, _ = fingerprint_query(q2)
        assert fp1 != fp2

    def test_different_columns_different_fingerprint(self):
        q1 = "SELECT name FROM users WHERE id = 1"
        q2 = "SELECT email FROM users WHERE id = 1"
        fp1, _, _ = fingerprint_query(q1)
        fp2, _, _ = fingerprint_query(q2)
        assert fp1 != fp2

    def test_aggregation_vs_select_different_fingerprint(self):
        q1 = "SELECT * FROM orders"
        q2 = "SELECT COUNT(*) FROM orders GROUP BY status"
        fp1, _, _ = fingerprint_query(q1)
        fp2, _, _ = fingerprint_query(q2)
        assert fp1 != fp2


class TestTableExtraction:
    def test_single_table(self):
        _, _, tables = fingerprint_query("SELECT * FROM orders")
        assert "ORDERS" in [t.upper() for t in tables]

    def test_join_tables(self):
        sql = "SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id"
        _, _, tables = fingerprint_query(sql)
        table_names = [t.upper() for t in tables]
        assert "ORDERS" in table_names
        assert "CUSTOMERS" in table_names

    def test_qualified_table(self):
        sql = "SELECT * FROM analytics.public.orders"
        _, _, tables = fingerprint_query(sql)
        assert len(tables) >= 1
        assert any("ORDERS" in t.upper() for t in tables)


class TestFallbackParsing:
    def test_unparseable_sql_still_fingerprints(self):
        sql = "THIS IS NOT VALID SQL AT ALL $$$ 123"
        fp, normalized, tables = fingerprint_query(sql)
        assert fp is not None
        assert len(fp) == 32
        assert tables == []

    def test_fingerprint_is_16_hex_chars(self):
        fp, _, _ = fingerprint_query("SELECT 1")
        assert len(fp) == 32
        assert all(c in "0123456789abcdef" for c in fp)


class TestDatabricksDialect:
    def test_databricks_dialect_parses(self):
        sql = "SELECT * FROM catalog.schema.orders WHERE id = 1"
        fp, normalized, tables = fingerprint_query(sql, dialect="databricks")
        assert fp is not None
        assert len(fp) == 32

    def test_databricks_same_pattern_groups(self):
        q1 = "SELECT * FROM orders WHERE date = '2026-01-01'"
        q2 = "SELECT * FROM orders WHERE date = '2026-02-01'"
        fp1, _, _ = fingerprint_query(q1, dialect="databricks")
        fp2, _, _ = fingerprint_query(q2, dialect="databricks")
        assert fp1 == fp2
