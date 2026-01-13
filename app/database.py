from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import sqlite3

# Configuração do SQLite
SQLALCHEMY_DATABASE_URL = "sqlite:///./app.db"

# O engine é o "motor" que se conecta ao arquivo do banco
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

# O SessionLocal é a "fábrica" de sessões para o banco
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# A Base é a classe que seus modelos (User, Boleto) vão herdar
Base = declarative_base()

def ensure_users_admin_column():
    if not SQLALCHEMY_DATABASE_URL.startswith("sqlite:///"):
        return

    db_path = SQLALCHEMY_DATABASE_URL.replace("sqlite:///", "", 1)
    db_path = os.path.abspath(db_path)

    if not os.path.exists(db_path):
        return

    con = sqlite3.connect(db_path)
    try:
        cols = [row[1] for row in con.execute("PRAGMA table_info(users)").fetchall()]
        if "is_admin" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
            con.commit()
        if "nome" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN nome TEXT")
            con.commit()
        if "plano" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN plano TEXT NOT NULL DEFAULT 'trial'")
            con.commit()
        if "creditos_renovam_em" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN creditos_renovam_em TEXT")
            con.commit()
        if "plano_pendente" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN plano_pendente TEXT")
            con.commit()
        if "plano_pendente_em" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN plano_pendente_em TEXT")
            con.commit()
    finally:
        con.close()


def ensure_boleto_history_telemetry_columns():
    if not SQLALCHEMY_DATABASE_URL.startswith("sqlite:///"):
        return

    db_path = SQLALCHEMY_DATABASE_URL.replace("sqlite:///", "", 1)
    db_path = os.path.abspath(db_path)

    if not os.path.exists(db_path):
        return

    con = sqlite3.connect(db_path)
    try:
        cols = [row[1] for row in con.execute("PRAGMA table_info(boleto_history)").fetchall()]
        # Se a tabela não existir ainda, o create_all vai criar; aqui só fazemos ALTER.
        if not cols:
            return

        if "sucesso" not in cols:
            con.execute("ALTER TABLE boleto_history ADD COLUMN sucesso INTEGER NOT NULL DEFAULT 1")
            con.commit()
        if "erro" not in cols:
            con.execute("ALTER TABLE boleto_history ADD COLUMN erro TEXT")
            con.commit()
        if "modelo_ia" not in cols:
            con.execute("ALTER TABLE boleto_history ADD COLUMN modelo_ia TEXT")
            con.commit()
        if "paginas_total" not in cols:
            con.execute("ALTER TABLE boleto_history ADD COLUMN paginas_total INTEGER")
            con.commit()
        if "paginas_processadas" not in cols:
            con.execute("ALTER TABLE boleto_history ADD COLUMN paginas_processadas INTEGER")
            con.commit()
        if "processamento_ms" not in cols:
            con.execute("ALTER TABLE boleto_history ADD COLUMN processamento_ms INTEGER")
            con.commit()
        if "telemetria" not in cols:
            con.execute("ALTER TABLE boleto_history ADD COLUMN telemetria TEXT")
            con.commit()
    finally:
        con.close()

# Função que o FastAPI usa para abrir e fechar o banco automaticamente
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
