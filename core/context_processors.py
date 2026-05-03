from __future__ import annotations

from .models import Company


NABER_USERNAME = "maudnaber"
NABER_COMPANY_NAME = "naber plastics"


def portal_theme(request):
    """Expose a small, safe theme object to every template.

    The Naber Plastics styling is intentionally scoped to one user/company so the
    existing Lemonade/Retriever portal theme remains unchanged for everyone else.
    """
    user = getattr(request, "user", None)
    theme = {
        "key": "default",
        "name": "Lemonade Stand",
    }

    if not user or not getattr(user, "is_authenticated", False):
        return {"portal_theme": theme}

    username = (getattr(user, "username", "") or "").strip().lower()
    if username == NABER_USERNAME:
        theme.update({"key": "naber", "name": "Naber Plastics"})
        return {"portal_theme": theme}

    company = None
    try:
        company = Company.objects.filter(owner=user).only("name").first()
    except Exception:
        company = None

    company_name = (getattr(company, "name", "") or "").strip().lower()
    if company_name == NABER_COMPANY_NAME:
        theme.update({"key": "naber", "name": "Naber Plastics"})

    return {"portal_theme": theme}
