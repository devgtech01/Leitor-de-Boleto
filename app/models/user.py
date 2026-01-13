from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.orm import relationship
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, nullable=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    creditos = Column(Integer, default=10) # Todo novo usuário ganha 10 créditos
    plano = Column(String, default="trial", nullable=False)
    creditos_renovam_em = Column(DateTime, nullable=True)
    plano_pendente = Column(String, nullable=True)
    plano_pendente_em = Column(DateTime, nullable=True)
    is_admin = Column(Boolean, default=False, nullable=False)

    # Relacionamento
    boletos = relationship("BoletoHistory", back_populates="owner")
