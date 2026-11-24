from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from support_platform.api.deps import get_container, require_scopes
from support_platform.api.presenters import customer_summary
from support_platform.container import Container
from support_platform.security.auth import CUSTOMERS_READ, Principal

router = APIRouter(prefix="/v1/customers", tags=["customers"])

CustomerId = Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{1,31}$")]


@router.get("/{customerId}")
async def get_customer(
    customerId: CustomerId,
    principal: Principal = Depends(require_scopes(CUSTOMERS_READ)),
    c: Container = Depends(get_container),
) -> dict:
    view = await c.customers.get_view(customerId)
    return customer_summary(view, principal, c.clock())
