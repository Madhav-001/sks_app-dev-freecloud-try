from django.urls import path
from .views import (
    EmployeeCreateView,
    ChangePasswordView,
    EmployeeListView,
    CustomLoginView,
    UserProfileView,
    LogoutView,
    LoginHistoryListView,
    EmployeeDetailView,
    CustomTokenRefreshView,
    AdminResetEmployeePasswordView,
    EmployeeRoleViewSet,
)


urlpatterns = [
    path('login/', CustomLoginView.as_view(), name='login'),
    path('token/refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('login-history/', LoginHistoryListView.as_view(), name='login-history'),
    path('create/', EmployeeCreateView.as_view(), name='employee-create'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('list/', EmployeeListView.as_view(), name='employee-list'),
    path('profile/', UserProfileView.as_view(), name='user-profile'),

    # Role-based access control matrix (Owner only)
    path('roles/', EmployeeRoleViewSet.as_view({'get': 'list', 'post': 'create'}), name='roles-list'),
    path('roles/<uuid:pk>/', EmployeeRoleViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'}), name='roles-detail'),

    path('<uuid:id>/', EmployeeDetailView.as_view(), name='employee-detail'),
    path('<uuid:id>/reset-password/', AdminResetEmployeePasswordView.as_view(), name='admin-reset-password'),
]
