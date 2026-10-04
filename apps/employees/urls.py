from django.urls import path
from apps.employees.views import (
    EmployeeListView,
    EmployeeDetailView,
    CurrentEmployeeProfileView,
    CheckAuthView,
)

urlpatterns = [
    path('', EmployeeListView.as_view(), name='employee-list'),
    path('me/', CurrentEmployeeProfileView.as_view(), name='employee-me'),
    path('check-auth/', CheckAuthView.as_view(), name='employee-check-auth'),
    path('<int:pk>/', EmployeeDetailView.as_view(), name='employee-detail'),
]
