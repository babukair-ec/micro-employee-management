from django.urls import path
from apps.employees.views import (
    EmployeeListView,
    EmployeeDetailView,
    CurrentEmployeeProfileView,
    CheckAuthView,
    SupervisionListCreateView,
    SupervisionDetailView,
    DepartmentOrProjectListCreateView,
    DepartmentOrProjectDetailView,
    EligibleManagersView,
    EmployeeDepartmentProjectListCreateView,
    EmployeeDepartmentProjectDetailView,
    AssignmentPermissionCheckView,
    SupervisionRequestListCreateView,
    SupervisionRequestApproveView,
    SupervisionRequestRejectView,
    SupervisionRequestEscalateView,
    SupervisionRequestCancelView,
    SupervisionHierarchyView,
)

urlpatterns = [
    # Core Employee endpoints
    path('', EmployeeListView.as_view(), name='employee-list'),
    path('me/', CurrentEmployeeProfileView.as_view(), name='employee-me'),
    path('check-auth/', CheckAuthView.as_view(), name='employee-check-auth'),
    path('hierarchy/', SupervisionHierarchyView.as_view(), name='employee-hierarchy'),
    path('<str:pk>/', EmployeeDetailView.as_view(), name='employee-detail'),

    # Supervision endpoints
    path('supervisions/', SupervisionListCreateView.as_view(), name='supervision-list-create'),
    path('supervisions/<str:pk>/', SupervisionDetailView.as_view(), name='supervision-detail'),

    # Supervision Requests endpoints
    path('supervision-requests/', SupervisionRequestListCreateView.as_view(), name='supervision-request-list-create'),
    path('supervision-requests/<str:pk>/approve/', SupervisionRequestApproveView.as_view(), name='supervision-request-approve'),
    path('supervision-requests/<str:pk>/reject/', SupervisionRequestRejectView.as_view(), name='supervision-request-reject'),
    path('supervision-requests/<str:pk>/escalate/', SupervisionRequestEscalateView.as_view(), name='supervision-request-escalate'),
    path('supervision-requests/<str:pk>/cancel/', SupervisionRequestCancelView.as_view(), name='supervision-request-cancel'),

    # Department and Project endpoints
    path('eligible-managers/', EligibleManagersView.as_view(), name='eligible-managers'),
    path('departments-projects/', DepartmentOrProjectListCreateView.as_view(), name='dept-proj-list-create'),
    path('departments-projects/<str:pk>/', DepartmentOrProjectDetailView.as_view(), name='dept-proj-detail'),

    # Employee Department/Project Assignments endpoints
    path('assignments/check-permission/', AssignmentPermissionCheckView.as_view(), name='assignment-check-permission'),
    path('assignments/', EmployeeDepartmentProjectListCreateView.as_view(), name='assignment-list-create'),
    path('assignments/<str:pk>/', EmployeeDepartmentProjectDetailView.as_view(), name='assignment-detail'),
]
