from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from .auth import Principal, resolve_principal
from .core import Forge


def get_forge(request: Request) -> Forge:
    return request.app.state.forge


def get_session(forge: Annotated[Forge, Depends(get_forge)]) -> Iterator[Session]:
    s = forge.session()
    try:
        yield s
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_principal(
    forge: Annotated[Forge, Depends(get_forge)],
    s: Annotated[Session, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    return resolve_principal(s, authorization, forge.settings)


ForgeDep = Annotated[Forge, Depends(get_forge)]
SessionDep = Annotated[Session, Depends(get_session)]
PrincipalDep = Annotated[Principal, Depends(get_principal)]
