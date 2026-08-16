import factory
from factory.django import DjangoModelFactory
from sales.models import Product, Order, OrderItem, Collection
from dealers.tests.factories import SubDealerFactory
from users.tests.factories import EmployeeFactory


class ProductFactory(DjangoModelFactory):
    class Meta:
        model = Product

    name = factory.Faker("word")
    price = 100.00
    unit = "box"


class OrderFactory(DjangoModelFactory):
    class Meta:
        model = Order

    sub_dealer = factory.SubFactory(SubDealerFactory)
    employee = factory.SubFactory(EmployeeFactory)
    total_amount = 0.00
    status = "pending"


class OrderItemFactory(DjangoModelFactory):
    class Meta:
        model = OrderItem

    order = factory.SubFactory(OrderFactory)
    product = factory.SubFactory(ProductFactory)
    quantity = 10
    unit_price = 10.00


class CollectionFactory(DjangoModelFactory):
    class Meta:
        model = Collection

    order = factory.SubFactory(OrderFactory)
    sub_dealer = factory.SubFactory(SubDealerFactory)
    employee = factory.SubFactory(EmployeeFactory)
    payment_type = "cash"
    amount = 500.00
    status = "pending"
