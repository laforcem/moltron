from __future__ import annotations

from datetime import datetime, timezone

from shop_lookup.models import Location, LookupResult, Product, Store


def to_lookup_result(store: Store, fields: dict, source: str = "safeway-pdp-api") -> LookupResult:
    return LookupResult(
        retailer="safeway",
        store=store,
        product=Product(
            id=fields["pid"],
            name=fields["name"],
            price=fields.get("price"),
            price_unit=fields.get("pricePer"),
        ),
        location=Location(
            label=fields.get("aisleLocation"),
            department=fields.get("departmentName"),
            aisle=fields.get("aisleName"),
            shelf=fields.get("shelfName"),
        ),
        availability=fields.get("availability"),
        checked_at=datetime.now(timezone.utc).isoformat(),
        source=source,
    )
