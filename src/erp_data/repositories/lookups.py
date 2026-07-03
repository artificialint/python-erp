"""Search + price lookups for autocomplete (desktop / online / AI callers).

Engine-free (erp_data). The desktop uses these to back QCompleters and to autofill
unit_price when a product is chosen.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from erp_data.db import models
from erp_data.db.base import PartyType, Status


def search_parties(
    session: Session, query: str, *, party_type: PartyType = PartyType.customer, limit: int = 20
) -> list[models.Party]:
    stmt = (
        select(models.Party)
        .where(
            models.Party.party_type == party_type,
            models.Party.status == Status.active,
            models.Party.legal_name.ilike(f"%{query}%"),
        )
        .order_by(models.Party.legal_name)
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())


def search_products(session: Session, query: str, *, limit: int = 20) -> list[models.ProductService]:
    like = f"%{query}%"
    stmt = (
        select(models.ProductService)
        .where(
            models.ProductService.status == Status.active,
            or_(
                models.ProductService.code.ilike(like),
                models.ProductService.description.ilike(like),
            ),
        )
        .order_by(models.ProductService.code)
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())


def resolve_unit_price(
    session: Session,
    *,
    product_code: str,
    seller_code: str,
    currency: str | None = None,
    on_date: date | None = None,
) -> float | None:
    """Latest valid price_list_item unit_price for (product, seller-or-shared, currency, date)."""
    on_date = on_date or date.today()
    product = session.execute(
        select(models.ProductService).where(models.ProductService.code == product_code)
    ).scalar_one_or_none()
    seller = session.execute(
        select(models.Organization).where(models.Organization.code == seller_code)
    ).scalar_one_or_none()
    if product is None or seller is None:
        return None
    curr = currency or seller.default_currency
    stmt = (
        select(models.PriceListItem.unit_price)
        .join(models.PriceList, models.PriceList.id == models.PriceListItem.price_list_id)
        .where(
            models.PriceListItem.product_id == product.id,
            or_(
                models.PriceList.organization_id == seller.id,
                models.PriceList.organization_id.is_(None),
            ),
            models.PriceList.valid_from <= on_date,
            or_(models.PriceList.valid_to.is_(None), models.PriceList.valid_to >= on_date),
        )
        .order_by(models.PriceList.valid_from.desc())
    )
    if curr:
        stmt = stmt.where(models.PriceList.currency == curr)
    return session.execute(stmt).scalars().first()
