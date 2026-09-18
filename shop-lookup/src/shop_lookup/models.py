from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Store:
    id: str
    name: str
    address: Optional[str] = None


@dataclass
class Product:
    id: str
    name: str
    price: Optional[float] = None
    price_unit: Optional[str] = None


@dataclass
class Location:
    label: Optional[str]
    department: Optional[str]
    aisle: Optional[str]
    shelf: Optional[str]


@dataclass
class LookupResult:
    retailer: str
    store: Store
    product: Product
    location: Location
    availability: Optional[str]
    checked_at: str
    source: str

    def to_json_dict(self) -> dict:
        return {
            "retailer": self.retailer,
            "store": {
                "id": self.store.id,
                "name": self.store.name,
                "address": self.store.address,
            },
            "product": {
                "id": self.product.id,
                "name": self.product.name,
                "price": self.product.price,
                "price_unit": self.product.price_unit,
            },
            "location": {
                "label": self.location.label,
                "department": self.location.department,
                "aisle": self.location.aisle,
                "shelf": self.location.shelf,
            },
            "availability": self.availability,
            "checked_at": self.checked_at,
            "source": self.source,
        }
