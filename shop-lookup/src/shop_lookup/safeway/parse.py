from __future__ import annotations

from shop_lookup.errors import NotFoundError, SchemaDriftError

_REQUIRED_FIELDS = ("pid", "name")
_OPTIONAL_FIELDS = (
    "availability",
    "departmentName",
    "aisleName",
    "aisleId",
    "shelfName",
    "aisleLocation",
    "price",
    "pricePer",
)


def _doc_to_fields(doc: dict) -> dict:
    fields = {field: doc[field] for field in _REQUIRED_FIELDS}
    for field in _OPTIONAL_FIELDS:
        fields[field] = doc.get(field)
    return fields


def extract_product_fields(raw: dict) -> dict:
    docs = raw.get("catalog", {}).get("response", {}).get("docs")
    if not docs:
        raise NotFoundError("No matching product returned", detail={})

    doc = docs[0]
    missing = [field for field in _REQUIRED_FIELDS if not doc.get(field)]
    if missing:
        raise SchemaDriftError(
            "Safeway's product response is missing expected fields",
            detail={"missing_fields": missing},
        )

    return _doc_to_fields(doc)


def extract_search_fields(raw: dict) -> list[dict]:
    docs = raw.get("primaryProducts", {}).get("response", {}).get("docs")
    if docs is None:
        raise SchemaDriftError(
            "Safeway's search response is missing the expected primaryProducts.response.docs shape",
            detail={},
        )

    results = []
    for doc in docs:
        if doc.get("pid") and doc.get("name"):
            fields = _doc_to_fields(doc)
            fields["availability"] = doc.get("status")
            results.append(fields)
    return results
