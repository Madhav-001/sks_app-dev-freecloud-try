from django.urls import path
from .views import SubDealerListCreateView, SubDealerUpdateView

urlpatterns = [
    path("", SubDealerListCreateView.as_view(), name="subdealer-list-create"),
    path("<uuid:id>", SubDealerUpdateView.as_view(), name="subdealer-update"),
]
