import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken
from users.tests.factories import EmployeeFactory

@pytest.fixture
def api_client():
    return APIClient()

@pytest.fixture
def auth_client(api_client):
    employee = EmployeeFactory()
    token = AccessToken.for_user(employee.user)  # assumes Employee has OneToOne to User
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(token)}")
    return api_client

@pytest.mark.django_db
def test_create_product(auth_client):
    url = reverse("product-list")   # router name from sales/urls.py
    payload = {"name": "Gadget", "price": "49.99", "unit": "pcs"}
    resp = auth_client.post(url, payload, format="json")
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Gadget"
    assert data["price"] == "49.99"

@pytest.mark.django_db
def test_create_order_auto_employee(auth_client, sub_dealer):
    url = reverse("order-list")
    payload = {
        "sub_dealer": sub_dealer.id,
        "total_amount": "200.00"
    }
    resp = auth_client.post(url, payload, format="json")
    assert resp.status_code == 201
    data = resp.json()
    # employee is injected from the JWT token
    assert "employee" in data

@pytest.mark.django_db
def test_collection_status_flow(auth_client, order):
    url = reverse("collection-list")
    payload = {
        "order": str(order.id),
        "sub_dealer": str(order.sub_dealer.id),
        "employee": str(order.employee.id),
        "amount": "100.00",
        "payment_type": "cash",
        "status": "pending"
    }
    # create pending collection
    resp = auth_client.post(url, payload, format="json")
    assert resp.status_code == 201
    coll_id = resp.json()["id"]

    # mark as successful
    patch_url = reverse("collection-detail", args=[coll_id])
    resp = auth_client.patch(patch_url, {"status": "success"}, format="json")
    assert resp.status_code == 200

    # order status should now reflect partial payment
    order.refresh_from_db()
    assert order.status == "partially_paid"
