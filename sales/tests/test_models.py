import pytest
from sales.models import Order

@pytest.mark.django_db
def test_order_soft_delete(order):
    """Soft‑delete should flag the record and hide it from the default manager."""
    order.delete()
    assert order.is_deleted is True
    # default manager excludes deleted objects
    assert not Order.objects.filter(id=order.id).exists()
    # manager that includes deleted objects still sees it
    assert Order.all_with_deleted.filter(id=order.id).exists()

@pytest.mark.django_db
def test_order_status_updates(order, collection):
    """Order status should evolve based on related collections."""
    # initially pending
    assert order.status == "pending"

    # add a successful collection (partial payment)
    collection.status = "success"
    collection.amount = order.total_amount / 2
    collection.save()
    order.update_status()
    assert order.status == "partially_paid"

    # pay the remaining amount
    collection.amount = order.total_amount
    collection.save()
    order.update_status()
    assert order.status == "paid"
