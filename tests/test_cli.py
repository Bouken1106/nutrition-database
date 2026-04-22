from src.cli.main import main
from src.db.connection import get_connection


def test_global_db_flag_before_subcommand_uses_requested_path(tmp_path):
    db_path = tmp_path / "custom.db"
    exit_code = main(["--db", str(db_path), "init-db"])
    assert exit_code == 0
    assert db_path.exists()
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM nutrients").fetchone()
        assert row["c"] > 0
