from __future__ import annotations

from .models import Company


NABER_USERNAME = "maudnaber"
NABER_COMPANY_NAME = "naber plastics"


def _norm(value):
    return (str(value or "")).strip().lower()


def get_portal_theme(user=None, company=None):
    """Return the active portal theme for a user/company.

    Naber styling is intentionally scoped to MaudNaber / Naber Plastics so the
    normal Lemonade theme remains unchanged for other users.
    """
    theme = {
        "key": "default",
        "name": "Lemonade Stand",
    }

    username = _norm(getattr(user, "username", ""))
    if username == NABER_USERNAME:
        return {"key": "naber", "name": "Naber Plastics"}

    company_name = _norm(getattr(company, "name", ""))
    if company_name == NABER_COMPANY_NAME:
        return {"key": "naber", "name": "Naber Plastics"}

    if user is not None and getattr(user, "is_authenticated", False):
        try:
            owned_company = Company.objects.filter(owner=user).only("name").first()
        except Exception:
            owned_company = None
        if _norm(getattr(owned_company, "name", "")) == NABER_COMPANY_NAME:
            return {"key": "naber", "name": "Naber Plastics"}

    return theme


def portal_theme(request):
    user = getattr(request, "user", None)
    return {"portal_theme": get_portal_theme(user=user)}
