"""Consistent, punctuation-insensitive filtering of free-text order statuses.

The stored status is never rewritten: only the filter comparison is normalized.
"""

import re

from django.db.models import F, Value
from django.db.models.functions import Replace

# Common separators used interchangeably in shipment statuses.
_SEPARATORS = (" ", "-", "_", "/", ".", "\\", "\t", "\n")


def normalize_status(value):
    """Return a separator-free, case-folded status for comparing demo snapshots."""
    return re.sub(r"[\s\-_./\\]", "", value or "").casefold()


def filter_by_status(queryset, search):
    """Preserve partial matches while ignoring status punctuation and spacing."""
    needle = normalize_status(search)
    if not needle:
        return queryset
    field = F("status")
    for separator in _SEPARATORS:
        field = Replace(field, Value(separator), Value(""))
    return queryset.alias(_status_for_search=field).filter(
        _status_for_search__icontains=needle
    )
