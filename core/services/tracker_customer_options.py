"""Customer-specific Order Tracker defaults (never share owner lists)."""

from ..models import OrderContainer


def is_retriever_company(company):
    return bool(company and company.owner_id and company.owner.username.casefold() == "retrieverpackaging")


def owner_names(company):
    if is_retriever_company(company):
        return ["Spencer", "Jaime"]
    if company is None:
        return []
    return sorted(set(OrderContainer.objects.filter(company=company).exclude(assigned_to="").values_list("assigned_to", flat=True)), key=str.casefold)


def country_for_container(container):
    if is_retriever_company(container.company):
        return "Netherlands"
    return (container.origin_country or "").strip()
