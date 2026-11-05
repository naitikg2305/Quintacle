"""2026-11-05: the shared sqlite connection must survive concurrent use
(the dashboard fires many requests at once)."""
from concurrent.futures import ThreadPoolExecutor

from quintacle_core import db


def test_shared_connection_survives_concurrent_reads_and_writes(tmp_path):
    conn = db.connect(tmp_path / "q.db")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v INTEGER)")
    conn.commit()

    def work(i):
        conn.execute("INSERT INTO t (v) VALUES (?)", (i,))
        conn.commit()
        rows = conn.execute("SELECT v FROM t WHERE v = ?", (i,)).fetchall()
        assert [r["v"] for r in rows] == [i]
        return sum(1 for _ in conn.execute("SELECT id FROM t LIMIT 5"))

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(work, range(400)))
    assert conn.execute("SELECT COUNT(*) AS n FROM t").fetchone()["n"] == 400


def test_cursor_attributes_still_work(tmp_path):
    conn = db.connect(tmp_path / "q.db")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    cur = conn.execute("INSERT INTO t (v) VALUES ('a')")
    assert cur.lastrowid == 1 and cur.rowcount == 1
    assert conn.execute("SELECT v FROM t").fetchone()["v"] == "a"
