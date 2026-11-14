"""JNP3-PER-002: the database changes only through additive migrations and keeps its history.

Two layers. (1) A static scan of every migrations/*.sql that flags each statement which is not
purely additive; the flagged set must equal REVIEWED below, so a new risky statement fails here
until a person reads it and writes a justification. (2) A live check that the immutable_record
trigger rejects UPDATE and DELETE on the four tables it guards.
test_migrations.py already proves that a populated database upgrades with its rows intact.
"""

import re
from collections import namedtuple
from pathlib import Path

import psycopg
import pytest

from aimo.db import connection
from aimo.schemas import PrepareRequest

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
IMMUTABLE = ("proposal_revisions", "audit_events", "policies", "customer_confirmations")
# Tables that carry buyers, identities, policies, approvals, orders and audit history (PER-002).
HISTORY = set(IMMUTABLE) | {
    "buyers",
    "identities",
    "approvals",
    "orders",
    "proposals",
    "idempotency",
    "prepare_requests",
    "internal_agents",
    "conversations",
    "conversation_turns",
    "conversation_messages",
}
# Never acceptable in a migration, on any table.
NEVER = {
    "DROP_TABLE",
    "DROP_COLUMN",
    "TRUNCATE",
    "DELETE",
    "RENAME",
    "DISABLE_TRIGGER",
    "DROP_TRIGGER",
    "DROP_FUNCTION",
    "REPLACE_FUNCTION",
    "DROP_OTHER",
}

Finding = namedtuple("Finding", "file line kind table detail text")


def strip_comments(text):
    """Blank out comments but keep every newline, so line numbers stay true."""
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group()), text, flags=re.S)
    return re.sub(r"--[^\n]*", lambda m: " " * len(m.group()), text)


def split_statements(text, base=0):
    """Yield (offset, statement) split on ';', descending into $$ bodies."""
    statements, depth, start, i = [], False, 0, 0
    while i < len(text):
        if text.startswith("$$", i):
            depth = not depth
            i += 2
            continue
        if text[i] == ";" and not depth:
            statements.append((base + start, text[start:i]))
            start = i + 1
        i += 1
    if text[start:].strip():
        statements.append((base + start, text[start:]))
    out = []
    for offset, statement in statements:
        out.append((offset, statement))
        match = re.search(r"\$\$(.*?)\$\$", statement, flags=re.S)
        if match:
            out.extend(split_statements(match.group(1), offset + match.start(1)))
    return out


def line_of(text, offset):
    return text.count("\n", 0, offset) + 1


NAME = r'"?(\w+)"?'
ALTER_TABLE = re.compile(r"\bALTER\s+TABLE\s+(?:ONLY\s+)?(?:IF\s+EXISTS\s+)?" + NAME, re.I)


def scan_text(file, raw):
    """Return (findings, inserts) for one migration's text."""
    text = strip_comments(raw)
    findings, inserts = [], []
    for offset, statement in split_statements(text):
        # A $$ body is scanned as its own statements below; scan only the head here.
        sql = " ".join(re.sub(r"\$\$.*?\$\$", " ", statement, flags=re.S).split())
        if not sql:
            continue
        # Lead the statement with its first real keyword; skip plpgsql "IF ... THEN" wrappers.
        line = line_of(text, offset + len(statement) - len(statement.lstrip()))
        alter = ALTER_TABLE.search(sql)
        table = alter.group(1).lower() if alter else ""

        def add(kind, table_name, detail="", sql=sql, line=line):
            findings.append(Finding(file, line, kind, table_name.lower(), detail, sql[:140]))

        if re.match(r"CREATE\s+(?:CONSTRAINT\s+)?TRIGGER", sql, re.I):
            continue  # "BEFORE UPDATE OR DELETE" is a trigger definition, not DML
        if re.search(r"\bCREATE\s+OR\s+REPLACE\s+FUNCTION\s+" + NAME, sql, re.I):
            add("REPLACE_FUNCTION", re.search(r"FUNCTION\s+" + NAME, sql, re.I).group(1))
        for m in re.finditer(r"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?" + NAME, sql, re.I):
            add("DROP_TABLE", m.group(1))
        for m in re.finditer(r"\bDROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?" + NAME, sql, re.I):
            add("DROP_COLUMN", table, m.group(1))
        for m in re.finditer(r"\bTRUNCATE\s+(?:TABLE\s+)?(?:ONLY\s+)?" + NAME, sql, re.I):
            add("TRUNCATE", m.group(1))
        for m in re.finditer(r"\bDELETE\s+FROM\s+(?:ONLY\s+)?" + NAME, sql, re.I):
            add("DELETE", m.group(1))
        for m in re.finditer(
            r"\bALTER\s+(?:COLUMN\s+)?" + NAME + r"\s+(?:SET\s+DATA\s+)?TYPE\s+([\w()]+)", sql, re.I
        ):
            add("ALTER_TYPE", table, f"{m.group(1)} -> {m.group(2)}")
        for m in re.finditer(
            r"\bALTER\s+COLUMN\s+" + NAME + r"\s+(SET|DROP)\s+NOT\s+NULL", sql, re.I
        ):
            add("ALTER_NULLABILITY", table, f"{m.group(2).upper()} NOT NULL on {m.group(1)}")
        for m in re.finditer(r"\bRENAME\b[^;]*", sql, re.I):
            add("RENAME", table, m.group(0)[:60])
        for m in re.finditer(
            r"\bUPDATE\s+" + NAME + r"\s+(?:AS\s+)?(?:\w+\s+)?SET\s+(.*)", sql, re.I
        ):
            columns = sorted(
                set(
                    re.findall(
                        r"(?:^|,)\s*(\w+)\s*=",
                        re.split(r"\bFROM\b|\bWHERE\b", m.group(2), flags=re.I)[0],
                    )
                )
            )
            add("UPDATE", m.group(1), ",".join(columns))
        for m in re.finditer(r"\bDROP\s+CONSTRAINT\s+(?:IF\s+EXISTS\s+)?" + NAME, sql, re.I):
            add("DROP_CONSTRAINT", table, m.group(1))
        for m in re.finditer(
            r"\bDROP\s+INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+EXISTS\s+)?" + NAME, sql, re.I
        ):
            add("DROP_INDEX", "", m.group(1))
        for m in re.finditer(
            r"\bDROP\s+TRIGGER\s+(?:IF\s+EXISTS\s+)?" + NAME + r"(?:\s+ON\s+" + NAME + ")?",
            sql,
            re.I,
        ):
            if re.search(r"CREATE\s+TRIGGER\s+" + re.escape(m.group(1)) + r"\b", text, re.I):
                continue  # repeatable re-creation of a trigger the same file creates (008)
            add("DROP_TRIGGER", m.group(2) or "", m.group(1))
        for m in re.finditer(r"\bDROP\s+FUNCTION\s+(?:IF\s+EXISTS\s+)?" + NAME, sql, re.I):
            add("DROP_FUNCTION", "", m.group(1))
        for m in re.finditer(
            r"\bDROP\s+(SCHEMA|TYPE|EXTENSION|VIEW|MATERIALIZED\s+VIEW|SEQUENCE|POLICY|RULE|ROLE)\b",
            sql,
            re.I,
        ):
            add("DROP_OTHER", "", m.group(1))
        for m in re.finditer(
            r"\b(?:DISABLE|ENABLE)\s+(?:TRIGGER|RULE|ROW\s+LEVEL)|session_replication_role",
            sql,
            re.I,
        ):
            add("DISABLE_TRIGGER", table, m.group(0))
        for m in re.finditer(
            r"\bADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?" + NAME + r"([^,]*)", sql, re.I
        ):
            definition = m.group(2)
            if re.search(r"NOT\s+NULL", definition, re.I) and not re.search(
                r"\bDEFAULT\b", definition, re.I
            ):
                add("ADD_NOT_NULL_NO_DEFAULT", table, m.group(1))
        for m in re.finditer(r"\bINSERT\s+INTO\s+" + NAME, sql, re.I):
            inserts.append((file, line, m.group(1).lower()))
    return findings, inserts


def scan_all():
    findings, inserts = [], []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        f, i = scan_text(path.name, path.read_text())
        findings += f
        inserts += i
    return findings, inserts


# Every flagged statement in the current migrations, with the reason it is acceptable. Key is
# (file, kind, table, detail). A change to the migrations must update this table on purpose.
REVIEWED = {
    (
        "004_worker_queue.sql",
        "DROP_CONSTRAINT",
        "conversation_turns",
        "conversation_turns_state_check",
    ): (
        "Immediately re-added in the same file with a wider CHECK (adds 'queued'). No row is "
        "touched; every old state value stays valid. Relaxes a constraint, loses nothing."
    ),
    ("004_worker_queue.sql", "UPDATE", "conversation_turns", "state"): (
        "NOT PURELY ADDITIVE. Changes the stored state of historical rows from 'running' to "
        "'failed' so they can be retried. Rows are kept and only the status column changes; "
        "justified in docs/separate-apps.md (no authenticated submitter was recorded). "
        "conversation_turns is chat history, not one of the four immutable tables."
    ),
    ("005_hosted_search.sql", "DROP_INDEX", "", "products_vector"): (
        "Drops the HNSW index only (a derived structure, no data). Needed because pgvector HNSW "
        "cannot index an unbounded vector; the catalog is not buyer history."
    ),
    ("005_hosted_search.sql", "ALTER_TYPE", "products", "embedding -> vector"): (
        "Catalog table. vector(384) -> unbounded vector widens the type; values are kept. "
        "Not buyer, policy, approval, order or audit history."
    ),
    ("005_hosted_search.sql", "ALTER_TYPE", "embedding_cache", "embedding -> vector"): (
        "Cache table for embeddings, same widening of vector(384) to vector; values are kept and the table holds no buyer history."
    ),
    ("006_recipe_proposal_link.sql", "UPDATE", "recipe_plans", "locked,proposal_id"): (
        "Backfills the NEW column proposal_id and sets locked=true on legacy recipe plans that "
        "already have a proposal. Rewrites an existing column (locked) of recipe data, not of a "
        "history table; aborts first when the match is ambiguous."
    ),
    ("009_product_withdrawn_since.sql", "UPDATE", "products", "withdrawn_since"): (
        "Backfills the NEW nullable column withdrawn_since for catalog rows already flagged "
        "deleted, from the creation time of the generation that carries them (the true date is "
        "unknown). Catalog data only: no buyer, policy, approval, order or audit history, and no "
        "existing column is rewritten."
    ),
    (
        "007_recipe_refresh_keys.sql",
        "DROP_CONSTRAINT",
        "prepare_requests",
        "prepare_requests_proposal_id_key",
    ): (
        "Drops a UNIQUE(proposal_id) so a refreshed proposal can hold several retry keys. "
        "Relaxes a constraint; the primary key (buyer, agent, key) still enforces idempotency; "
        "no row changes."
    ),
    ("011_proposal_revision_ordering.sql", "UPDATE", "proposals", "updated_at"): (
        "Only fills the NEW column updated_at (guarded so it runs once, inside the block that "
        "adds the column). No existing column of proposals changes."
    ),
}
# INSERT targets that migrations may use (new reference rows only).
ALLOWED_INSERT_TABLES = {"identities", "internal_agents"}


def key(finding):
    return (finding.file, finding.kind, finding.table, finding.detail)


# ---- scanner self-tests: it must catch what it claims to catch ----------------------------


@pytest.mark.parametrize(
    "sql,kind",
    [
        ("DROP TABLE orders", "DROP_TABLE"),
        ("DROP TABLE IF EXISTS audit_events CASCADE", "DROP_TABLE"),
        ("ALTER TABLE orders DROP COLUMN receipt", "DROP_COLUMN"),
        ("TRUNCATE policies", "TRUNCATE"),
        ("TRUNCATE TABLE buyers CASCADE", "TRUNCATE"),
        ("DELETE FROM audit_events WHERE id < 10", "DELETE"),
        ("ALTER TABLE orders ALTER COLUMN receipt TYPE text", "ALTER_TYPE"),
        ("ALTER TABLE orders ALTER COLUMN receipt SET DATA TYPE text", "ALTER_TYPE"),
        ("ALTER TABLE orders RENAME COLUMN receipt TO r", "RENAME"),
        ("ALTER TABLE orders RENAME TO sales", "RENAME"),
        ("UPDATE policies SET rules='{}'", "UPDATE"),
        ("UPDATE audit_events a SET detail='{}' WHERE a.id=1", "UPDATE"),
        ("DROP TRIGGER immutable_audit ON audit_events", "DROP_TRIGGER"),
        ("DROP FUNCTION immutable_record()", "DROP_FUNCTION"),
        (
            "CREATE OR REPLACE FUNCTION immutable_record() RETURNS trigger AS $$ BEGIN RETURN NEW; END $$ LANGUAGE plpgsql",
            "REPLACE_FUNCTION",
        ),
        ("ALTER TABLE audit_events DISABLE TRIGGER immutable_audit", "DISABLE_TRIGGER"),
        ("ALTER TABLE orders ADD COLUMN note text NOT NULL", "ADD_NOT_NULL_NO_DEFAULT"),
        ("ALTER TABLE orders ALTER COLUMN receipt DROP NOT NULL", "ALTER_NULLABILITY"),
        ("DO $$ BEGIN DELETE FROM orders; END $$", "DELETE"),
        ("DO $$ BEGIN IF true THEN UPDATE orders SET receipt='{}'; END IF; END $$", "UPDATE"),
        ("DROP SCHEMA public CASCADE", "DROP_OTHER"),
    ],
)
def test_scanner_flags_every_non_additive_form(sql, kind):
    findings, _ = scan_text("synthetic.sql", sql + ";")
    assert kind in {f.kind for f in findings}, (sql, findings)


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE t (id int PRIMARY KEY)",
        "ALTER TABLE orders ADD COLUMN note text",
        "ALTER TABLE orders ADD COLUMN note text NOT NULL DEFAULT ''",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS note text",
        "CREATE INDEX i ON orders(created_at)",
        "ALTER TABLE orders ADD CONSTRAINT c CHECK (revision > 0)",
        "CREATE TRIGGER x BEFORE UPDATE OR DELETE ON orders FOR EACH ROW EXECUTE FUNCTION immutable_record()",
        "CREATE FUNCTION f() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$",
        "CREATE TABLE t (a int REFERENCES b(id) ON UPDATE CASCADE ON DELETE RESTRICT)",
        "SELECT 1 FROM orders FOR UPDATE",
        "INSERT INTO identities(id) VALUES ('x')",
        "-- DROP TABLE orders\nSELECT 1",
        "/* TRUNCATE orders */ SELECT 1",
    ],
)
def test_scanner_allows_additive_forms(sql):
    findings, _ = scan_text("synthetic.sql", sql + ";")
    assert findings == [], findings


def test_scanner_reports_the_true_line_number():
    findings, _ = scan_text("synthetic.sql", "-- one\nCREATE TABLE a (id int);\n\nDELETE FROM a;\n")
    assert [(f.kind, f.line) for f in findings] == [("DELETE", 4)]


# ---- the real migrations -----------------------------------------------------------------


def test_migrations_exist_and_are_scanned():
    names = sorted(p.name for p in MIGRATIONS.glob("*.sql"))
    assert "001_initial.sql" in names and len(names) >= 9


def test_flagged_statements_are_exactly_the_reviewed_findings(capsys):
    findings, _ = scan_all()
    with capsys.disabled():
        print("\nPER-002 scan findings (file:line kind table detail):")
        for f in findings:
            print(f"  {f.file}:{f.line} {f.kind} {f.table or '-'} {f.detail}")
    assert {key(f) for f in findings} == set(REVIEWED), "review the difference and update REVIEWED"
    assert all(len(reason) > 40 for reason in REVIEWED.values())


def test_no_migration_uses_a_never_allowed_statement():
    findings, _ = scan_all()
    assert [(f.file, f.line, f.kind) for f in findings if f.kind in NEVER] == []
    assert not {k[1] for k in REVIEWED} & NEVER


def test_no_migration_touches_the_four_immutable_tables_except_to_create_them():
    findings, _ = scan_all()
    assert [(f.file, f.line, f.kind, f.table) for f in findings if f.table in IMMUTABLE] == []


def test_inserts_only_add_reference_rows_to_known_tables():
    _, inserts = scan_all()
    assert inserts, "003_chat_purchasing.sql inserts the internal agents"
    assert {table for _, _, table in inserts} <= ALLOWED_INSERT_TABLES, inserts
    assert {file for file, _, _ in inserts} == {"003_chat_purchasing.sql"}


def test_immutable_trigger_definitions_cover_the_four_tables_and_never_replace_the_function():
    """The four base tables stay guarded. A later migration may guard a NEW table it creates
    itself (010 does, for withdrawals); it may not guard or unguard anything else."""
    guarded, created = {}, {}
    for path in sorted(MIGRATIONS.glob("*.sql")):
        text = strip_comments(path.read_text())
        for m in re.finditer(
            r"CREATE\s+TRIGGER\s+immutable_\w+\s+BEFORE\s+UPDATE\s+OR\s+DELETE\s+ON\s+(\w+)"
            r"\s+FOR\s+EACH\s+ROW\s+EXECUTE\s+FUNCTION\s+immutable_record\(\)",
            text,
            re.I,
        ):
            guarded[m.group(1)] = path.name
        for m in re.finditer(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", text, re.I):
            created[m.group(1)] = path.name
    assert set(IMMUTABLE) <= set(guarded), set(IMMUTABLE) - set(guarded)
    extra = {t: f for t, f in guarded.items() if t not in IMMUTABLE}
    # 008 (WS-D) additionally guards `orders`, a base table created in 001: a saved receipt is
    # history. It only adds protection; nothing is unguarded.
    guarded_later = {"orders": "008_orders_immutable.sql"}
    assert all(created.get(t) == f or guarded_later.get(t) == f for t, f in extra.items()), extra
    definitions = [
        p.name
        for p in MIGRATIONS.glob("*.sql")
        if re.search(
            r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+immutable_record",
            strip_comments(p.read_text()),
            re.I,
        )
    ]
    assert definitions == ["001_initial.sql"]


def test_database_catalog_shows_the_guard_on_each_immutable_table():
    """Live pg_trigger: an enabled BEFORE ROW trigger for UPDATE and DELETE running immutable_record."""
    with connection() as c:
        rows = c.execute(
            "SELECT c.relname AS tbl, t.tgenabled AS enabled, t.tgtype AS tgtype "
            "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
            "JOIN pg_proc p ON p.oid=t.tgfoid "
            "WHERE p.proname='immutable_record' AND NOT t.tgisinternal"
        ).fetchall()
    by_table = {r["tbl"]: r for r in rows}
    assert set(IMMUTABLE) <= set(by_table), set(IMMUTABLE) - set(by_table)
    for table, row in by_table.items():
        # tgtype bits: 1 row-level, 2 BEFORE, 8 DELETE, 16 UPDATE; 4 INSERT must be clear.
        assert row["enabled"] == "O", table
        assert row["tgtype"] & (1 | 2 | 8 | 16) == (1 | 2 | 8 | 16), table
        assert not row["tgtype"] & 4, table


def test_every_packaged_migration_is_in_the_ledger_under_its_original_name():
    names = {p.name for p in MIGRATIONS.glob("*.sql")}
    with connection() as c:
        applied = {r["version"] for r in c.execute("SELECT version FROM schema_migrations")}
    assert names <= applied, names - applied


# ---- live: the immutable_record trigger -------------------------------------------------


@pytest.fixture
def history_rows(agent, service, request_data):
    """A real proposal revision, audit event, policy and customer confirmation."""
    proposal = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    with connection() as c:
        revision = c.execute(
            "SELECT proposal_id,revision,fingerprint FROM proposal_revisions WHERE proposal_id=%s",
            (proposal["proposal_id"],),
        ).fetchone()
        c.execute(
            "INSERT INTO customer_confirmations(proposal_id,revision,fingerprint,actor_id,key,buyer_id)"
            " VALUES(%s,%s,%s,'buyer','per-002-key',%s)",
            (
                revision["proposal_id"],
                revision["revision"],
                revision["fingerprint"],
                agent["buyer_id"],
            ),
        )
    return proposal["proposal_id"]


SNAPSHOT = {
    "proposal_revisions": "SELECT * FROM proposal_revisions ORDER BY proposal_id,revision",
    "audit_events": "SELECT * FROM audit_events ORDER BY id",
    "policies": "SELECT * FROM policies ORDER BY buyer_id,version",
    "customer_confirmations": "SELECT * FROM customer_confirmations ORDER BY proposal_id,revision",
}
MUTATIONS = {
    "proposal_revisions": (
        "UPDATE proposal_revisions SET policy_outcome='denied'",
        "DELETE FROM proposal_revisions",
    ),
    "audit_events": ("UPDATE audit_events SET event='tampered'", "DELETE FROM audit_events"),
    "policies": ("UPDATE policies SET rules='{}'::jsonb", "DELETE FROM policies"),
    "customer_confirmations": (
        "UPDATE customer_confirmations SET key='tampered'",
        "DELETE FROM customer_confirmations",
    ),
}


@pytest.mark.parametrize("table", IMMUTABLE)
@pytest.mark.parametrize("operation", [0, 1], ids=["update", "delete"])
def test_immutable_record_rejects_update_and_delete(history_rows, table, operation):
    with connection() as c:
        before = c.execute(SNAPSHOT[table]).fetchall()
    assert before, f"{table} must hold a row for this test to mean anything"
    with connection() as c:
        with pytest.raises(psycopg.errors.RaiseException, match="immutable history"):
            with c.transaction():
                c.execute(MUTATIONS[table][operation])
    with connection() as c:
        assert c.execute(SNAPSHOT[table]).fetchall() == before


@pytest.mark.parametrize("table", IMMUTABLE)
def test_immutable_tables_still_accept_appended_history(history_rows, table):
    """The guard blocks rewriting, not adding: new versions and events are appended."""
    with connection() as c:
        before = c.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
        if table == "policies":
            c.execute(
                "INSERT INTO policies(buyer_id,version,rules) "
                "SELECT buyer_id,version+1000,rules FROM policies LIMIT 1"
            )
        elif table == "audit_events":
            c.execute(
                "INSERT INTO audit_events(proposal_id,actor_id,event,detail) "
                "VALUES(%s,'buyer','per_002_probe','{}')",
                (history_rows,),
            )
        elif table == "proposal_revisions":
            c.execute(
                "INSERT INTO proposal_revisions SELECT proposal_id,revision+1,policy_version,request,"
                "snapshot,fingerprint,policy_outcome,reasons,required_exceptions,expires_at "
                "FROM proposal_revisions WHERE proposal_id=%s",
                (history_rows,),
            )
        else:
            c.execute(
                "INSERT INTO customer_confirmations(proposal_id,revision,fingerprint,actor_id,key,buyer_id)"
                " SELECT proposal_id,revision,fingerprint,'demo-agent','per-002-second-key',buyer_id"
                " FROM customer_confirmations LIMIT 1"
            )
        assert c.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == before + 1


@pytest.mark.xfail(
    strict=True,
    reason="GAP: immutable_record is a row-level UPDATE/DELETE trigger; PostgreSQL does not fire "
    "it for TRUNCATE. The runtime role lacks the TRUNCATE privilege (permissions.py grants "
    "SELECT, INSERT, UPDATE, DELETE only) but the schema owner can erase the history tables.",
)
@pytest.mark.parametrize("table", IMMUTABLE)
def test_immutable_tables_also_reject_truncate(history_rows, table):
    with connection() as c:
        try:
            with pytest.raises(psycopg.errors.RaiseException, match="immutable history"):
                c.execute(f"TRUNCATE {table} CASCADE")
        finally:
            c.rollback()  # never keep a successful truncate
