"""
admin_mixins.py
---------------
Shared Django admin mixin for soft-delete / hard-delete enforcement.

Rules:
  - Superuser  (is_superuser=True, employeeidnum=0) → HARD DELETE  (removed from DB)
  - Everyone else (staff, admins, …)                → SOFT DELETE  (is_deleted=True, stays in DB)

Usage
-----
class MyModelAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    use_soft_delete_manager = True   # True  → model uses SoftDeleteManager (has all_with_deleted())
                                     # False → model uses default Django manager
    ...
"""

from django.db.models import Model as _DjangoModel
from django.db.models.query import QuerySet as _DjangoQuerySet


class SoftDeleteAdminMixin:
    """
    Mixin to be placed *before* admin.ModelAdmin (or UserAdmin) in the MRO.

    Attributes
    ----------
    use_soft_delete_manager : bool
        Set to True for models whose `objects` manager is SoftDeleteManager
        (i.e. has an `all_with_deleted()` method).
        Set to False (default) for models that use Django's default manager.
    """

    use_soft_delete_manager: bool = False

    # ------------------------------------------------------------------ #
    #  Single-object delete  (toolbar "Delete" button on the change page) #
    # ------------------------------------------------------------------ #
    def delete_model(self, request, obj):
        if request.user.is_superuser:
            # Hard delete: call Django's base Model.delete() directly,
            # bypassing any model-level override (e.g. Product.delete → soft-delete).
            _DjangoModel.delete(obj)
        else:
            # Soft delete: just flag the record, keep it in DB.
            obj.is_deleted = True
            obj.save(update_fields=["is_deleted"])

    # ------------------------------------------------------------------ #
    #  Bulk delete  (list-view "Delete selected …" action)               #
    # ------------------------------------------------------------------ #
    def delete_queryset(self, request, queryset):
        if request.user.is_superuser:
            # Collect PKs first (the queryset may be filtered / annotated).
            pk_list = list(queryset.values_list("pk", flat=True))

            if self.use_soft_delete_manager:
                # SoftDeleteQuerySet.delete() is overridden to soft-delete.
                # Bypass it by calling Django's base QuerySet.delete() directly.
                qs = queryset.model._default_manager.all_with_deleted().filter(
                    pk__in=pk_list
                )
            else:
                # Standard manager – plain queryset, no override.
                qs = queryset.model._default_manager.filter(pk__in=pk_list)

            # Force real DB deletion regardless of QuerySet subclass.
            _DjangoQuerySet.delete(qs)
        else:
            # Soft delete for everyone else.
            queryset.update(is_deleted=True)
