"""OwnedProduct query helpers for password changer."""

from __future__ import annotations

from django.db.models import QuerySet


def find_firstmail_owned_products(
    *,
    status: str | None = None,
    category_id: int | None = None,
) -> QuerySet:
    """Find OwnedProduct records whose email is hosted on FirstMail.

    Matches: email_login_link containing 'firstmail'
    (covers firstmail.ltd, wildbmail.com, etc.)
    """
    from apps.inventory.models import OwnedProduct

    qs = OwnedProduct.objects.filter(
        email_login_link__icontains="firstmail",
    ).exclude(
        email="",
    ).exclude(
        email_password="",
    )

    if status:
        qs = qs.filter(status=status)
    if category_id:
        qs = qs.filter(category_id=category_id)

    return qs.order_by("id")
