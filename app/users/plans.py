from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class Plano:
    codigo: str
    creditos_mensais: int


PLANOS: dict[str, Plano] = {
    "trial": Plano(codigo="trial", creditos_mensais=10),
    "basico": Plano(codigo="basico", creditos_mensais=2000),
    "profissional": Plano(codigo="profissional", creditos_mensais=6000),
    "escritorio": Plano(codigo="escritorio", creditos_mensais=12000),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _add_30_days(dt: datetime) -> datetime:
    return dt + timedelta(days=30)


def plano_creditos(codigo: str | None) -> int:
    if not codigo:
        return PLANOS["trial"].creditos_mensais
    return PLANOS.get(codigo, PLANOS["trial"]).creditos_mensais


def ensure_plano_fields(user) -> bool:
    changed = False
    if not getattr(user, "plano", None):
        user.plano = "trial"
        changed = True

    if getattr(user, "creditos_renovam_em", None) is None:
        user.creditos_renovam_em = _add_30_days(_utcnow())
        changed = True

    return changed


def maybe_renew_credits(user) -> bool:
    if getattr(user, "is_admin", False):
        return False

    changed = ensure_plano_fields(user)
    renovam_em = getattr(user, "creditos_renovam_em", None)
    if renovam_em is None:
        return changed

    # SQLite pode devolver datetime naive; tratamos como UTC.
    if renovam_em.tzinfo is None:
        renovam_em = renovam_em.replace(tzinfo=timezone.utc)

    now = _utcnow()
    if now < renovam_em:
        return changed

    user.creditos = plano_creditos(getattr(user, "plano", None))
    user.creditos_renovam_em = _add_30_days(now)
    return True

