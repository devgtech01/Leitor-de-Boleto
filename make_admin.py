import sqlite3
import sys
from pathlib import Path


def ensure_is_admin_column(con: sqlite3.Connection) -> None:
    cols = [row[1] for row in con.execute("PRAGMA table_info(users)").fetchall()]
    if "is_admin" in cols:
        return
    con.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
    con.commit()


def main() -> int:
    if len(sys.argv) != 2:
        print("Uso: python make_admin.py <email>")
        return 2

    email = sys.argv[1].strip()
    if not email:
        print("Email inválido.")
        return 2

    db_path = Path("app.db")
    if not db_path.exists():
        print("Não encontrei `app.db` no diretório atual.")
        return 1

    con = sqlite3.connect(str(db_path))
    try:
        ensure_is_admin_column(con)
        cur = con.execute("UPDATE users SET is_admin = 1 WHERE email = ?", (email,))
        con.commit()
        if cur.rowcount == 0:
            print("Usuário não encontrado. Cadastre-se primeiro e rode novamente.")
            return 1
    finally:
        con.close()

    print(f"OK: `{email}` agora é admin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

