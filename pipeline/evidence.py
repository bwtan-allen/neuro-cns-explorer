"""Normalized SQLite publication evidence; replacement of a researcher run is atomic."""
import json
import sqlite3
from pathlib import Path


DEFAULT_DATABASE = Path(__file__).resolve().parents[1] / "data" / "publications.sqlite3"


class EvidenceStore:
    def __init__(self, path=DEFAULT_DATABASE, readonly=False):
        self.path = Path(path)
        if readonly:
            self.connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(str(self.path), timeout=30)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.row_factory = sqlite3.Row
        if not readonly:
            with self.connection:
                self.connection.executescript("""
                    CREATE TABLE IF NOT EXISTS metadata (
                        key TEXT PRIMARY KEY, value TEXT NOT NULL
                    );
                    INSERT OR IGNORE INTO metadata VALUES ('schema_version', '1');
                    CREATE TABLE IF NOT EXISTS publications (
                        pmid TEXT PRIMARY KEY, evidence TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS researcher_runs (
                        researcher_id TEXT PRIMARY KEY, metadata TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS researcher_publications (
                        researcher_id TEXT NOT NULL REFERENCES researcher_runs(researcher_id),
                        pmid TEXT NOT NULL REFERENCES publications(pmid),
                        decision TEXT NOT NULL CHECK(decision IN ('included', 'excluded', 'unresolved')),
                        reason TEXT NOT NULL,
                        PRIMARY KEY (researcher_id, pmid)
                    );
                    CREATE INDEX IF NOT EXISTS evidence_by_pmid ON researcher_publications(pmid);
                """)
        version = self.connection.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()
        if version is None or version["value"] != "1":
            self.connection.close()
            raise ValueError("Unsupported publication evidence schema.")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.connection.close()

    def metadata(self, researcher_id):
        row = self.connection.execute(
            "SELECT metadata FROM researcher_runs WHERE researcher_id = ?", (researcher_id,)
        ).fetchone()
        return json.loads(row["metadata"]) if row else None

    def result(self, researcher_id):
        metadata = self.metadata(researcher_id)
        if metadata is None:
            return None
        rows = self.connection.execute("""
            SELECT p.evidence, rp.decision, rp.reason
            FROM researcher_publications rp JOIN publications p ON p.pmid = rp.pmid
            WHERE rp.researcher_id = ? ORDER BY p.pmid
        """, (researcher_id,)).fetchall()
        return {**metadata, "papers": [
            {**json.loads(row["evidence"]), "decision": row["decision"], "reason": row["reason"]}
            for row in rows
        ]}

    def save(self, researcher_id, result):
        if result["researcher_id"] != researcher_id:
            raise ValueError("A publication run cannot be saved under a different researcher ID.")
        metadata = {key: value for key, value in result.items() if key != "papers"}
        papers = result["papers"]
        if len({paper["pmid"] for paper in papers}) != len(papers):
            raise ValueError("A completed researcher run cannot contain duplicate PMIDs.")
        encoded_metadata = json.dumps(metadata, allow_nan=False, sort_keys=True)
        with self.connection:
            self.connection.execute("""
                INSERT INTO researcher_runs VALUES (?, ?)
                ON CONFLICT(researcher_id) DO UPDATE SET metadata = excluded.metadata
            """, (researcher_id, encoded_metadata))
            self.connection.execute("DELETE FROM researcher_publications WHERE researcher_id = ?", (researcher_id,))
            for paper in papers:
                evidence = {key: value for key, value in paper.items() if key not in ("decision", "reason")}
                self.connection.execute("""
                    INSERT INTO publications VALUES (?, ?)
                    ON CONFLICT(pmid) DO UPDATE SET evidence = excluded.evidence
                """, (paper["pmid"], json.dumps(evidence, allow_nan=False, sort_keys=True)))
                self.connection.execute("INSERT INTO researcher_publications VALUES (?, ?, ?, ?)",
                                        (researcher_id, paper["pmid"], paper["decision"], paper["reason"]))

    def coverage(self):
        return {
            "researchers": self.connection.execute("SELECT count(*) FROM researcher_runs").fetchone()[0],
            "publications": self.connection.execute("SELECT count(*) FROM publications").fetchone()[0],
        }
