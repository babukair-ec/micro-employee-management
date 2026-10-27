from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from apps.employees.models import (
    Employee,
    Supervision,
    DepartmentOrProject,
    EmployeeDepartmentProject,
)
from apps.employees.serializers import (
    EmployeeSerializer,
    SupervisionSerializer,
    DepartmentOrProjectSerializer,
    EmployeeDepartmentProjectSerializer,
)
from datetime import timezone
from django.http import Http404

class DualIdLookupMixin:
    def get_object(self):
        lookup = self.kwargs.get(self.lookup_field or 'pk')
        queryset = self.filter_queryset(self.get_queryset())
        if str(lookup).isdigit():
            obj = queryset.filter(id=int(lookup)).first()
        else:
            obj = queryset.filter(outer_id=lookup).first()
        if not obj:
            raise Http404
        self.check_object_permissions(self.request, obj)
        return obj

def get_supervision_request_by_id_or_outer_id(pk, for_update=True):
    qs = SupervisionRequest.objects.select_for_update() if for_update else SupervisionRequest.objects
    if str(pk).isdigit():
        return qs.get(id=int(pk))
    return qs.get(outer_id=pk)

def check_authenticated(request):
    """Explicitly verify whether or not the user is authenticated."""
    return bool(request.user and getattr(request.user, 'is_authenticated', False))

def get_current_employee(request):
    """Helper to retrieve Employee profile for current authenticated user."""
    user_id = getattr(request.user, 'id', None)
    emp = None
    if user_id:
        emp = Employee.objects.filter(user_id=user_id).first()
        if not emp:
            emp = Employee.objects.filter(user_id=str(user_id)).first()
    if not emp and getattr(request.user, 'username', None):
        emp = Employee.objects.filter(username=request.user.username).first()
    return emp

def get_user_and_descendants(employee):
    """
    Returns list of Employee IDs containing the given employee and all their
    descendants traversing the active Supervision hierarchy.
    """
    if not employee:
        return []
    descendants = [employee.id]
    queue = [employee.id]
    visited = {employee.id}

    while queue:
        curr_id = queue.pop(0)
        sub_ids = list(Supervision.objects.filter(
            supervisor_id=curr_id,
            end_date__isnull=True
        ).values_list('subordinate_id', flat=True))

        for sid in sub_ids:
            if sid not in visited:
                visited.add(sid)
                queue.append(sid)
                descendants.append(sid)

    return descendants

def evaluate_department_assignment_permission(current_emp, department_project):
    """
    Evaluation of Department/Project Manager's Hierarchy via Supervision:
    - Determine if assigned manager has a manager above them by querying Supervision (subordinate == dept.manager).
    - Case A (Manager has a superior): The department manager is strictly blocked from adding employees.
      Only their direct superior manager (found via Supervision) has authority to assign employees.
    - Case B (Manager has NO superior / Top authority): The manager has full authority and is permitted
      to add any employee to the department/project.
    """
    if not department_project:
        return False, str(_("Department/Project not found.")), "NONE", {}

    manager = department_project.manager
    if not manager:
        return False, str(_("This department/project does not have an assigned manager. Please assign a manager first.")), "NO_MANAGER", {}

    if not current_emp:
        return False, str(_("Current user has no associated employee profile.")), "NO_PROFILE", {}

    # Query active supervisions where subordinate == department.manager
    supervisions = list(Supervision.objects.filter(
        subordinate=manager,
        end_date__isnull=True
    ).select_related('supervisor'))

    superior_ids = [s.supervisor_id for s in supervisions]
    superior_names = [s.supervisor.full_name for s in supervisions]

    if supervisions:
        # Case A: Manager has a superior
        if current_emp.id == manager.id:
            # Manager is strictly blocked
            return (
                False,
                str(_(f"Access Blocked (Case A): As the manager of {department_project.name}, you have a superior manager above you. Under organizational hierarchy rules, only your direct superior manager can assign employees to this department/project.")),
                "CASE_A_MANAGER_BLOCKED",
                {
                    'manager_name': manager.full_name,
                    'superior_names': superior_names,
                    'has_superior': True,
                }
            )
        elif current_emp.id in superior_ids:
            # Current user is direct superior manager
            return (
                True,
                str(_(f"Authority Granted (Case A): You are a direct superior manager of {manager.full_name}. You have the authority to assign employees to this department/project.")),
                "CASE_A_SUPERIOR_ALLOWED",
                {
                    'manager_name': manager.full_name,
                    'superior_names': superior_names,
                    'has_superior': True,
                }
            )
        else:
            return (
                False,
                str(_(f"Access Denied (Case A): The manager of {department_project.name} ({manager.full_name}) has superior manager(s) [{', '.join(superior_names)}]. Only their direct superior manager holds authority to assign employees.")),
                "CASE_A_UNAUTHORIZED",
                {
                    'manager_name': manager.full_name,
                    'superior_names': superior_names,
                    'has_superior': True,
                }
            )
    else:
        # Case B: Manager has NO superior (Top authority)
        if current_emp.id == manager.id:
            return (
                True,
                str(_(f"Authority Granted (Case B): You are the top authority manager of {department_project.name} with no superiors above you. You have full authority to assign employees.")),
                "CASE_B_TOP_MANAGER_ALLOWED",
                {
                    'manager_name': manager.full_name,
                    'superior_names': [],
                    'has_superior': False,
                }
            )
        else:
            return (
                False,
                str(_(f"Access Denied (Case B): {manager.full_name} is the top authority manager of {department_project.name}. Only this manager is permitted to assign employees.")),
                "CASE_B_UNAUTHORIZED",
                {
                    'manager_name': manager.full_name,
                    'superior_names': [],
                    'has_superior': False,
                }
            )

class CheckAuthView(APIView):
    """Endpoint to explicitly check whether or not the user is authenticated."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        if check_authenticated(request):
            emp = get_current_employee(request)
            return Response({
                'authenticated': True,
                'user_id': str(getattr(request.user, 'id', None)),
                'outer_id': str(emp.outer_id) if emp else None,
                'username': getattr(request.user, 'username', ''),
                'email': getattr(request.user, 'email', ''),
                'full_name': getattr(request.user, 'full_name', ''),
            }, status=status.HTTP_200_OK)
        return Response({
            'authenticated': False,
            'error': 'ERR_UNAUTHORIZED',
            'message': str(_('User is not authenticated'))
        }, status=status.HTTP_401_UNAUTHORIZED)

class EmployeeListView(generics.ListCreateAPIView):
    """
    Append-only employee listing & creation endpoint.
    Strictly disallows editing or deletion.
    """
    queryset = Employee.objects.filter(is_active=True).order_by('first_name', 'username')
    serializer_class = EmployeeSerializer

    def get_permissions(self):
        if self.request.method == 'POST':
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def list(self, request, *args, **kwargs):
        if not check_authenticated(request):
            return Response({
                'error': 'ERR_UNAUTHORIZED',
                'message': str(_('User is not authenticated'))
            }, status=status.HTTP_401_UNAUTHORIZED)
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

class EmployeeDetailView(DualIdLookupMixin, generics.RetrieveAPIView):
    """
    Retrieve-only employee detail view.
    Updates and deletions are strictly rejected here;
    Employee data can ONLY be updated through their dedicated Profile page (/api/employees/me/).
    """
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def retrieve(self, request, *args, **kwargs):
        if not check_authenticated(request):
            return Response({
                'error': 'ERR_UNAUTHORIZED',
                'message': str(_('User is not authenticated'))
            }, status=status.HTTP_401_UNAUTHORIZED)
        return super().retrieve(request, *args, **kwargs)

    def put(self, request, *args, **kwargs):
        return Response({
            'error': 'ERR_UPDATE_RESTRICTED',
            'message': str(_('Employee data can ONLY be updated through their dedicated Profile page.'))
        }, status=status.HTTP_403_FORBIDDEN)

    def patch(self, request, *args, **kwargs):
        return Response({
            'error': 'ERR_UPDATE_RESTRICTED',
            'message': str(_('Employee data can ONLY be updated through their dedicated Profile page.'))
        }, status=status.HTTP_403_FORBIDDEN)

    def delete(self, request, *args, **kwargs):
        return Response({
            'error': 'ERR_DELETE_RESTRICTED',
            'message': str(_('Employee deletion is strictly disallowed.'))
        }, status=status.HTTP_403_FORBIDDEN)

class CurrentEmployeeProfileView(APIView):
    """
    Dedicated Profile endpoint for viewing and updating the current employee's data.
    Employee updates can ONLY be performed through this endpoint.
    GET requests are strictly idempotent and read-only.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not check_authenticated(request):
            return Response({
                'error': 'ERR_UNAUTHORIZED',
                'message': str(_('User is not authenticated'))
            }, status=status.HTTP_401_UNAUTHORIZED)

        employee = get_current_employee(request)
        if not employee:
            return Response({
                'error': 'ERR_EMPLOYEE_NOT_FOUND',
                'message': str(_('Employee profile not found'))
            }, status=status.HTTP_404_NOT_FOUND)

        serializer = EmployeeSerializer(employee)
        return Response(serializer.data)

    def post(self, request):
        """
        Creates an employee profile for the currently authenticated user if it does not exist yet.
        Used when the employee was not created via event or needs manual creation from the Profile screen.
        """
        if not check_authenticated(request):
            return Response({
                'error': 'ERR_UNAUTHORIZED',
                'message': str(_('User is not authenticated'))
            }, status=status.HTTP_401_UNAUTHORIZED)

        existing = get_current_employee(request)
        if existing:
            return Response({
                'error': 'ERR_EMPLOYEE_EXISTS',
                'message': str(_('Employee profile already exists')),
                'data': EmployeeSerializer(existing).data
            }, status=status.HTTP_400_BAD_REQUEST)

        user_id = getattr(request.user, 'id', None)
        username = getattr(request.user, 'username', '')

        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        data['user_id'] = user_id
        data['username'] = username
        if not data.get('first_name'):
            data['first_name'] = getattr(request.user, 'first_name', '')
        if not data.get('last_name'):
            data['last_name'] = getattr(request.user, 'last_name', '')
        if not data.get('email'):
            data['email'] = getattr(request.user, 'email', None)

        serializer = EmployeeSerializer(data=data)
        if serializer.is_valid():
            employee = serializer.save()
            return Response(EmployeeSerializer(employee).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request):
        return self._update_profile(request, partial=False)

    def patch(self, request):
        return self._update_profile(request, partial=True)

    def _update_profile(self, request, partial=False):
        if not check_authenticated(request):
            return Response({
                'error': 'ERR_UNAUTHORIZED',
                'message': str(_('User is not authenticated'))
            }, status=status.HTTP_401_UNAUTHORIZED)

        employee = get_current_employee(request)
        if not employee:
            return Response({
                'error': 'ERR_EMPLOYEE_NOT_FOUND',
                'message': str(_('Employee profile not found'))
            }, status=status.HTTP_404_NOT_FOUND)

        # Do not allow modifying id or user_id
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        data.pop('id', None)
        data.pop('outer_id', None)
        data.pop('user_id', None)
        data.pop('username', None)

        serializer = EmployeeSerializer(employee, data=data, partial=partial)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class EligibleManagersView(APIView):
    """
    Returns employees eligible to be manager for Department/Project:
    strictly includes the current user and their descendants in the Supervision hierarchy only.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not check_authenticated(request):
            return Response({
                'error': 'ERR_UNAUTHORIZED',
                'message': str(_('User is not authenticated'))
            }, status=status.HTTP_401_UNAUTHORIZED)

        current_emp = get_current_employee(request)
        if not current_emp:
            return Response([], status=status.HTTP_200_OK)

        eligible_ids = get_user_and_descendants(current_emp)
        eligible_emps = Employee.objects.filter(id__in=eligible_ids, is_active=True).order_by('first_name', 'username')
        serializer = EmployeeSerializer(eligible_emps, many=True)
        return Response(serializer.data)

# -----------------------------------------------------------------------------
# Views for Supervision, DepartmentOrProject, EmployeeDepartmentProject
# -----------------------------------------------------------------------------

class SupervisionListCreateView(generics.ListCreateAPIView):
    queryset = Supervision.objects.all().order_by('-start_date')
    serializer_class = SupervisionSerializer
    permission_classes = [permissions.IsAuthenticated]

class SupervisionDetailView(DualIdLookupMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = Supervision.objects.all()
    serializer_class = SupervisionSerializer
    permission_classes = [permissions.IsAuthenticated]

class DepartmentOrProjectListCreateView(generics.ListCreateAPIView):
    queryset = DepartmentOrProject.objects.all().order_by('name')
    serializer_class = DepartmentOrProjectSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        manager = serializer.validated_data.get('manager')
        if manager:
            current_emp = get_current_employee(self.request)
            if current_emp:
                eligible_ids = get_user_and_descendants(current_emp)
                if manager.id not in eligible_ids:
                    raise ValidationError({'manager': str(_("Manager must be yourself or one of your descendants in the supervision hierarchy."))})
        serializer.save()

class DepartmentOrProjectDetailView(DualIdLookupMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = DepartmentOrProject.objects.all()
    serializer_class = DepartmentOrProjectSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_update(self, serializer):
        manager = serializer.validated_data.get('manager')
        if manager:
            current_emp = get_current_employee(self.request)
            if current_emp:
                eligible_ids = get_user_and_descendants(current_emp)
                if manager.id not in eligible_ids:
                    raise ValidationError({'manager': str(_("Manager must be yourself or one of your descendants in the supervision hierarchy."))})
        serializer.save()

class AssignmentPermissionCheckView(APIView):
    """
    Evaluates whether the current user is authorized to assign employees to a Department/Project
    based on the Supervision hierarchy rules.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        dept_id = request.query_params.get('department_project')
        if not dept_id:
            return Response({'error': 'ERR_MISSING_FIELD', 'message': str(_('department_project parameter is required'))}, status=status.HTTP_400_BAD_REQUEST)

        try:
            dept = DepartmentOrProject.objects.select_related('manager').get(id=dept_id)
        except DepartmentOrProject.DoesNotExist:
            return Response({'error': 'ERR_NOT_FOUND', 'message': str(_('Department or Project not found'))}, status=status.HTTP_404_NOT_FOUND)

        current_emp = get_current_employee(request)
        allowed, reason, case_code, details = evaluate_department_assignment_permission(current_emp, dept)

        return Response({
            'allowed': allowed,
            'reason': reason,
            'case': case_code,
            'details': details,
            'department_project': {
                'id': str(dept.id),
                'name': dept.name,
                'code': dept.code,
                'type': dept.type,
                'manager_name': dept.manager.full_name if dept.manager else None,
                'manager_id': str(dept.manager.id) if dept.manager else None,
            }
        })

class EmployeeDepartmentProjectListCreateView(generics.ListCreateAPIView):
    serializer_class = EmployeeDepartmentProjectSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = EmployeeDepartmentProject.objects.all().order_by('-assigned_at')
        dept_id = self.request.query_params.get('department_project')
        if dept_id:
            qs = qs.filter(department_project_id=dept_id)
        emp_id = self.request.query_params.get('employee')
        if emp_id:
            qs = qs.filter(employee_id=emp_id)
        return qs

    def create(self, request, *args, **kwargs):
        if not check_authenticated(request):
            return Response({
                'error': 'ERR_UNAUTHORIZED',
                'message': str(_('User is not authenticated'))
            }, status=status.HTTP_401_UNAUTHORIZED)

        dept_id = request.data.get('department_project')
        if not dept_id:
            return Response({'error': 'ERR_MISSING_FIELD', 'message': str(_('department_project is required'))}, status=status.HTTP_400_BAD_REQUEST)

        try:
            dept = DepartmentOrProject.objects.select_related('manager').get(id=dept_id)
        except DepartmentOrProject.DoesNotExist:
            return Response({'error': 'ERR_NOT_FOUND', 'message': str(_('Department or Project not found'))}, status=status.HTTP_404_NOT_FOUND)

        current_emp = get_current_employee(request)
        allowed, reason, case_code, details = evaluate_department_assignment_permission(current_emp, dept)

        if not allowed:
            return Response({
                'error': 'ERR_PERMISSION_DENIED',
                'message': reason,
                'case': case_code,
                'details': details,
            }, status=status.HTTP_403_FORBIDDEN)

        # Check for duplicate active assignment
        emp_id = request.data.get('employee')
        existing = EmployeeDepartmentProject.objects.filter(
            employee_id=emp_id,
            department_project_id=dept_id,
            is_current=True
        ).first()
        if existing:
            return Response({
                'error': 'ERR_DUPLICATE_ASSIGNMENT',
                'message': str(_('This employee is already actively assigned to this department/project.')),
                'assignment': EmployeeDepartmentProjectSerializer(existing).data
            }, status=status.HTTP_400_BAD_REQUEST)

        # Constraint enforcement:
        # 1. An employee cannot be assigned to more than one project.
        # 2. An employee can be assigned to a department and a project within the same department.
        if dept.type == DepartmentOrProject.TYPE_PROJECT:
            # Rule 1: Cannot have more than one active project
            existing_project = EmployeeDepartmentProject.objects.filter(
                employee_id=emp_id,
                department_project__type=DepartmentOrProject.TYPE_PROJECT,
                is_current=True
            ).exclude(department_project_id=dept_id).select_related('department_project').first()
            if existing_project:
                return Response({
                    'error': 'ERR_MULTIPLE_PROJECTS_NOT_ALLOWED',
                    'message': str(_("An employee cannot be assigned to more than one project. Employee is already assigned to project '%(project)s'.") % {
                        'project': existing_project.department_project.name
                    })
                }, status=status.HTTP_400_BAD_REQUEST)

            # Rule 2: If assigned to a department, project must belong to that same department
            existing_dept = EmployeeDepartmentProject.objects.filter(
                employee_id=emp_id,
                department_project__type=DepartmentOrProject.TYPE_DEPARTMENT,
                is_current=True
            ).select_related('department_project').first()
            if existing_dept and dept.department_id:
                if dept.department_id != existing_dept.department_project_id:
                    dept_name = existing_dept.department_project.name
                    proj_dept_name = dept.department.name if dept.department else "N/A"
                    return Response({
                        'error': 'ERR_PROJECT_DEPARTMENT_MISMATCH',
                        'message': str(_("An employee can only be assigned to a project within their assigned department. The employee belongs to '%(dept)s', whereas this project belongs to '%(proj_dept)s'.") % {
                            'dept': dept_name,
                            'proj_dept': proj_dept_name
                        })
                    }, status=status.HTTP_400_BAD_REQUEST)

        elif dept.type == DepartmentOrProject.TYPE_DEPARTMENT:
            # Rule 3: If employee has an active project, it must belong to this department
            existing_project = EmployeeDepartmentProject.objects.filter(
                employee_id=emp_id,
                department_project__type=DepartmentOrProject.TYPE_PROJECT,
                is_current=True
            ).select_related('department_project', 'department_project__department').first()
            if existing_project and existing_project.department_project.department_id:
                if existing_project.department_project.department_id != dept.id:
                    proj_name = existing_project.department_project.name
                    proj_dept_name = existing_project.department_project.department.name if existing_project.department_project.department else "N/A"
                    return Response({
                        'error': 'ERR_DEPARTMENT_PROJECT_MISMATCH',
                        'message': str(_("The employee is currently assigned to project '%(project)s' under department '%(proj_dept)s', and cannot be assigned to a different department.") % {
                            'project': proj_name,
                            'proj_dept': proj_dept_name
                        })
                    }, status=status.HTTP_400_BAD_REQUEST)

            # Rule 4: An employee cannot be assigned to more than one department
            existing_dept = EmployeeDepartmentProject.objects.filter(
                employee_id=emp_id,
                department_project__type=DepartmentOrProject.TYPE_DEPARTMENT,
                is_current=True
            ).exclude(department_project_id=dept_id).select_related('department_project').first()
            if existing_dept:
                return Response({
                    'error': 'ERR_MULTIPLE_DEPARTMENTS_NOT_ALLOWED',
                    'message': str(_("The employee is already assigned to department '%(dept)s'. An employee cannot be assigned to more than one department.") % {
                        'dept': existing_dept.department_project.name
                    })
                }, status=status.HTTP_400_BAD_REQUEST)

        return super().create(request, *args, **kwargs)

class EmployeeDepartmentProjectDetailView(DualIdLookupMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = EmployeeDepartmentProject.objects.all()
    serializer_class = EmployeeDepartmentProjectSerializer
    permission_classes = [permissions.IsAuthenticated]


# -----------------------------------------------------------------------------
# Supervision Hierarchy Helpers & Dynamic Relinquishing Authority
# -----------------------------------------------------------------------------

def get_active_supervisor(employee):
    """Returns direct active supervisor of employee, or None."""
    if not employee:
        return None
    sup = Supervision.objects.filter(
        subordinate=employee,
        end_date__isnull=True
    ).select_related('supervisor').first()
    return sup.supervisor if sup else None

def get_supervision_chain_upwards(employee):
    """Returns list of supervisors from direct supervisor up to root."""
    if not employee:
        return []
    chain = []
    curr = employee
    visited = {curr.id}
    while True:
        supervisor = get_active_supervisor(curr)
        if not supervisor or supervisor.id in visited:
            break
        visited.add(supervisor.id)
        chain.append(supervisor)
        curr = supervisor
    return chain

def get_root_supervisor(employee):
    """Returns the top supervisor in employee's upwards chain (the one with no supervisor)."""
    chain = get_supervision_chain_upwards(employee)
    return chain[-1] if chain else employee

def would_create_supervision_cycle(proposed_supervisor, proposed_subordinate):
    """
    Checks if making proposed_supervisor supervise proposed_subordinate would create a cycle.
    If proposed_subordinate is already an ancestor of proposed_supervisor, this would cause a cycle.
    """
    if not proposed_supervisor or not proposed_subordinate:
        return False
    if proposed_supervisor.id == proposed_subordinate.id:
        return True
    ancestors = get_supervision_chain_upwards(proposed_supervisor)
    ancestor_ids = {a.id for a in ancestors}
    return proposed_subordinate.id in ancestor_ids

def determine_supervision_approver(proposed_supervisor, proposed_subordinate, request_type):
    """
    Determines the legitimate approver for a supervision request according to organizational hierarchy rules.
    - If proposed_subordinate has a current supervisor B:
      - Does B have a supervisor A above him?
        - If yes: B CANNOT relinquish C. The request goes to the root supervisor above B (A).
        - If no (B has no supervisor above him): B is top level and CAN relinquish C directly.
    - If proposed_subordinate has NO supervisor:
      - If request_type == 'REQUEST_TO_SUPERVISE': the proposed subordinate must approve.
      - If request_type == 'REQUEST_TO_BE_SUPERVISED': the proposed supervisor must approve.
    """
    current_sup = get_active_supervisor(proposed_subordinate)
    if current_sup:
        superiors_of_current = get_supervision_chain_upwards(current_sup)
        if superiors_of_current:
            return superiors_of_current[-1], current_sup
        else:
            return current_sup, current_sup
    else:
        if request_type == SupervisionRequest.TYPE_SUPERVISE_TARGET:
            return proposed_subordinate, None
        else:
            return proposed_supervisor, None


# -----------------------------------------------------------------------------
# Supervision Requests Views
# -----------------------------------------------------------------------------

from django.db import transaction
from apps.employees.models import SupervisionRequest
from apps.employees.serializers import SupervisionRequestSerializer
from apps.messaging.rabbitmq import publish_event


class SupervisionRequestListCreateView(APIView):
    """
    List and create supervision requests with dynamic authority assignment.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not check_authenticated(request):
            return Response({'error': 'ERR_UNAUTHORIZED', 'message': str(_('User is not authenticated'))}, status=status.HTTP_401_UNAUTHORIZED)

        current_emp = get_current_employee(request)
        if not current_emp:
            return Response([], status=status.HTTP_200_OK)

        scope = request.query_params.get('scope', 'all')
        req_status = request.query_params.get('status')

        qs = SupervisionRequest.objects.all().select_related(
            'requester', 'target_employee', 'proposed_supervisor',
            'proposed_subordinate', 'current_supervisor', 'current_approver', 'escalated_to'
        )

        if scope == 'incoming':
            qs = qs.filter(current_approver=current_emp)
        elif scope == 'outgoing':
            qs = qs.filter(requester=current_emp)
        else:
            from django.db.models import Q
            qs = qs.filter(
                Q(current_approver=current_emp) |
                Q(requester=current_emp) |
                Q(proposed_supervisor=current_emp) |
                Q(proposed_subordinate=current_emp)
            )

        if req_status:
            qs = qs.filter(status=req_status)

        serializer = SupervisionRequestSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def create(self, request):
        if not check_authenticated(request):
            return Response({'error': 'ERR_UNAUTHORIZED', 'message': str(_('User is not authenticated'))}, status=status.HTTP_401_UNAUTHORIZED)

        current_emp = get_current_employee(request)
        if not current_emp:
            return Response({'error': 'ERR_NO_PROFILE', 'message': str(_('Current user has no associated employee profile'))}, status=status.HTTP_400_BAD_REQUEST)

        target_id = request.data.get('target_employee') or request.data.get('target_employee_id')
        request_type = request.data.get('request_type', SupervisionRequest.TYPE_SUPERVISE_TARGET)
        decision_reason = request.data.get('decision_reason', '')

        if not target_id:
            return Response({'error': 'ERR_MISSING_FIELD', 'message': str(_('target_employee is required'))}, status=status.HTTP_400_BAD_REQUEST)

        try:
            if str(target_id).isdigit():
                target_emp = Employee.objects.get(id=int(target_id), is_active=True)
            else:
                target_emp = Employee.objects.get(outer_id=target_id, is_active=True)
        except (Employee.DoesNotExist, ValueError):
            return Response({'error': 'ERR_NOT_FOUND', 'message': str(_('Target employee not found'))}, status=status.HTTP_404_NOT_FOUND)

        if str(current_emp.id) == str(target_emp.id):
            return Response({'error': 'ERR_SELF_SUPERVISION', 'message': str(_('An employee cannot supervise themselves.'))}, status=status.HTTP_400_BAD_REQUEST)

        if request_type == SupervisionRequest.TYPE_SUPERVISE_TARGET:
            proposed_supervisor = current_emp
            proposed_subordinate = target_emp
        elif request_type == SupervisionRequest.TYPE_BE_SUPERVISED:
            proposed_supervisor = target_emp
            proposed_subordinate = current_emp
        else:
            return Response({'error': 'ERR_INVALID_REQUEST_TYPE', 'message': str(_('Invalid request type.'))}, status=status.HTTP_400_BAD_REQUEST)

        # Check if already supervised by this supervisor
        current_active_sup = get_active_supervisor(proposed_subordinate)
        if current_active_sup and current_active_sup.id == proposed_supervisor.id:
            return Response({
                'error': 'ERR_ALREADY_SUPERVISED',
                'message': str(_(f'{proposed_subordinate.full_name} is already supervised by {proposed_supervisor.full_name}.'))
            }, status=status.HTTP_400_BAD_REQUEST)

        # Cycle check
        if would_create_supervision_cycle(proposed_supervisor, proposed_subordinate):
            return Response({
                'error': 'ERR_SUPERVISION_CYCLE',
                'message': str(_('This request would create a cycle in the supervision hierarchy.'))
            }, status=status.HTTP_400_BAD_REQUEST)

        # Determine dynamic approver
        current_approver, current_supervisor = determine_supervision_approver(
            proposed_supervisor, proposed_subordinate, request_type
        )

        supervision_req = SupervisionRequest.objects.create(
            requester=current_emp,
            target_employee=target_emp,
            request_type=request_type,
            proposed_supervisor=proposed_supervisor,
            proposed_subordinate=proposed_subordinate,
            current_supervisor=current_supervisor,
            current_approver=current_approver,
            status=SupervisionRequest.STATUS_PENDING,
            decision_reason=decision_reason or '',
        )

        publish_event('supervision.requested', {
            'id': str(supervision_req.id),
            'requester_id': str(current_emp.id),
            'proposed_supervisor_id': str(proposed_supervisor.id),
            'proposed_subordinate_id': str(proposed_subordinate.id),
            'current_approver_id': str(current_approver.id),
            'current_supervisor_id': str(current_supervisor.id) if current_supervisor else None,
            'request_type': request_type,
        })

        serializer = SupervisionRequestSerializer(supervision_req)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def post(self, request):
        return self.create(request)


class SupervisionRequestApproveView(APIView):
    """
    Atomic approval of supervision request with row-locking and concurrency guard.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        if not check_authenticated(request):
            return Response({'error': 'ERR_UNAUTHORIZED', 'message': str(_('User is not authenticated'))}, status=status.HTTP_401_UNAUTHORIZED)

        current_emp = get_current_employee(request)
        if not current_emp:
            return Response({'error': 'ERR_NO_PROFILE', 'message': str(_('Current user has no associated employee profile'))}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                req = get_supervision_request_by_id_or_outer_id(pk, for_update=True)

                if req.status not in [SupervisionRequest.STATUS_PENDING, SupervisionRequest.STATUS_ESCALATED]:
                    return Response({
                        'error': 'ERR_INVALID_STATUS',
                        'message': str(_(f'Cannot approve request in status: {req.status}'))
                    }, status=status.HTTP_400_BAD_REQUEST)

                # Authorization check: only current approver has authority!
                if str(req.current_approver_id) != str(current_emp.id):
                    return Response({
                        'error': 'ERR_UNAUTHORIZED_APPROVER',
                        'message': str(_(f'Only the assigned authority ({req.current_approver.full_name}) can approve this request.'))
                    }, status=status.HTTP_403_FORBIDDEN)

                # Check for cycle before committing
                if would_create_supervision_cycle(req.proposed_supervisor, req.proposed_subordinate):
                    return Response({
                        'error': 'ERR_SUPERVISION_CYCLE',
                        'message': str(_('Cannot approve: this would create a cycle in the supervision hierarchy.'))
                    }, status=status.HTTP_400_BAD_REQUEST)

                # Close any existing active supervision for subordinate with row lock
                active_supervisions = list(Supervision.objects.select_for_update().filter(
                    subordinate=req.proposed_subordinate,
                    end_date__isnull=True
                ))
                for s in active_supervisions:
                    s.end_date = timezone.now().date()
                    s.save()

                # Create new supervision
                new_sup = Supervision.objects.create(
                    supervisor=req.proposed_supervisor,
                    subordinate=req.proposed_subordinate,
                    start_date=timezone.now().date(),
                )

                req.status = SupervisionRequest.STATUS_APPROVED
                req.responded_at = timezone.now()
                req.save()

                publish_event('supervision.approved', {
                    'request_id': str(req.id),
                    'supervisor_id': str(req.proposed_supervisor_id),
                    'subordinate_id': str(req.proposed_subordinate_id),
                    'supervision_id': str(new_sup.id),
                })
                publish_event('supervision.changed', {
                    'supervisor_id': str(req.proposed_supervisor_id),
                    'subordinate_id': str(req.proposed_subordinate_id),
                })

                serializer = SupervisionRequestSerializer(req)
                return Response(serializer.data, status=status.HTTP_200_OK)

        except SupervisionRequest.DoesNotExist:
            return Response({'error': 'ERR_NOT_FOUND', 'message': str(_('Supervision request not found'))}, status=status.HTTP_404_NOT_FOUND)


class SupervisionRequestRejectView(APIView):
    """
    Reject supervision request by the assigned approver.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        if not check_authenticated(request):
            return Response({'error': 'ERR_UNAUTHORIZED', 'message': str(_('User is not authenticated'))}, status=status.HTTP_401_UNAUTHORIZED)

        current_emp = get_current_employee(request)
        if not current_emp:
            return Response({'error': 'ERR_NO_PROFILE', 'message': str(_('Current user has no associated employee profile'))}, status=status.HTTP_400_BAD_REQUEST)

        decision_reason = request.data.get('decision_reason', '')

        try:
            with transaction.atomic():
                req = get_supervision_request_by_id_or_outer_id(pk, for_update=True)

                if req.status not in [SupervisionRequest.STATUS_PENDING, SupervisionRequest.STATUS_ESCALATED]:
                    return Response({
                        'error': 'ERR_INVALID_STATUS',
                        'message': str(_(f'Cannot reject request in status: {req.status}'))
                    }, status=status.HTTP_400_BAD_REQUEST)

                if str(req.current_approver_id) != str(current_emp.id):
                    return Response({
                        'error': 'ERR_UNAUTHORIZED_APPROVER',
                        'message': str(_(f'Only the assigned authority ({req.current_approver.full_name}) can reject this request.'))
                    }, status=status.HTTP_403_FORBIDDEN)

                req.status = SupervisionRequest.STATUS_REJECTED
                req.decision_reason = decision_reason or req.decision_reason
                req.responded_at = timezone.now()
                req.save()

                publish_event('supervision.rejected', {
                    'request_id': str(req.id),
                    'approver_id': str(current_emp.id),
                    'reason': req.decision_reason,
                })

                serializer = SupervisionRequestSerializer(req)
                return Response(serializer.data, status=status.HTTP_200_OK)

        except SupervisionRequest.DoesNotExist:
            return Response({'error': 'ERR_NOT_FOUND', 'message': str(_('Supervision request not found'))}, status=status.HTTP_404_NOT_FOUND)


class SupervisionRequestEscalateView(APIView):
    """
    Manual escalation of a pending request to the current approver's direct supervisor.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        if not check_authenticated(request):
            return Response({'error': 'ERR_UNAUTHORIZED', 'message': str(_('User is not authenticated'))}, status=status.HTTP_401_UNAUTHORIZED)

        current_emp = get_current_employee(request)
        if not current_emp:
            return Response({'error': 'ERR_NO_PROFILE', 'message': str(_('Current user has no associated employee profile'))}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                req = get_supervision_request_by_id_or_outer_id(pk, for_update=True)

                if req.status not in [SupervisionRequest.STATUS_PENDING, SupervisionRequest.STATUS_ESCALATED]:
                    return Response({
                        'error': 'ERR_INVALID_STATUS',
                        'message': str(_(f'Cannot escalate request in status: {req.status}'))
                    }, status=status.HTTP_400_BAD_REQUEST)

                if str(req.current_approver_id) != str(current_emp.id):
                    return Response({
                        'error': 'ERR_UNAUTHORIZED_APPROVER',
                        'message': str(_('Only the current approver can escalate this request.'))
                    }, status=status.HTTP_403_FORBIDDEN)

                escalate_to_id = request.data.get('escalate_to_id')
                superior = None
                if escalate_to_id:
                    try:
                        if str(escalate_to_id).isdigit():
                            superior = Employee.objects.filter(id=int(escalate_to_id), is_active=True).first()
                        else:
                            superior = Employee.objects.filter(outer_id=escalate_to_id, is_active=True).first()
                    except (Employee.DoesNotExist, ValueError):
                        superior = None
                if not superior:
                    superior = get_active_supervisor(current_emp)
                if not superior:
                    return Response({
                        'error': 'ERR_CANNOT_ESCALATE_TOP_LEVEL',
                        'message': str(_('You are at the top level of the hierarchy and have no superior to escalate to.'))
                    }, status=status.HTTP_400_BAD_REQUEST)

                req.current_approver = superior
                req.escalated_to = superior
                req.escalated_at = timezone.now()
                req.status = SupervisionRequest.STATUS_ESCALATED
                req.save()

                publish_event('supervision.escalated', {
                    'request_id': str(req.id),
                    'escalated_by_id': str(current_emp.id),
                    'escalated_to_id': str(superior.id),
                })

                serializer = SupervisionRequestSerializer(req)
                return Response(serializer.data, status=status.HTTP_200_OK)

        except SupervisionRequest.DoesNotExist:
            return Response({'error': 'ERR_NOT_FOUND', 'message': str(_('Supervision request not found'))}, status=status.HTTP_404_NOT_FOUND)


class SupervisionRequestCancelView(APIView):
    """
    Cancel an outgoing pending supervision request by the requester.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        if not check_authenticated(request):
            return Response({'error': 'ERR_UNAUTHORIZED', 'message': str(_('User is not authenticated'))}, status=status.HTTP_401_UNAUTHORIZED)

        current_emp = get_current_employee(request)
        if not current_emp:
            return Response({'error': 'ERR_NO_PROFILE', 'message': str(_('Current user has no associated employee profile'))}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                req = get_supervision_request_by_id_or_outer_id(pk, for_update=True)

                if str(req.requester_id) != str(current_emp.id):
                    return Response({
                        'error': 'ERR_UNAUTHORIZED',
                        'message': str(_('Only the requester can cancel this request.'))
                    }, status=status.HTTP_403_FORBIDDEN)

                if req.status not in [SupervisionRequest.STATUS_PENDING, SupervisionRequest.STATUS_ESCALATED]:
                    return Response({
                        'error': 'ERR_INVALID_STATUS',
                        'message': str(_(f'Cannot cancel request in status: {req.status}'))
                    }, status=status.HTTP_400_BAD_REQUEST)

                req.status = SupervisionRequest.STATUS_CANCELLED
                req.save()

                serializer = SupervisionRequestSerializer(req)
                return Response(serializer.data, status=status.HTTP_200_OK)

        except SupervisionRequest.DoesNotExist:
            return Response({'error': 'ERR_NOT_FOUND', 'message': str(_('Supervision request not found'))}, status=status.HTTP_404_NOT_FOUND)


class SupervisionHierarchyView(APIView):
    """
    Returns current user's supervision hierarchy (supervisors ascending, subordinates descending).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not check_authenticated(request):
            return Response({'error': 'ERR_UNAUTHORIZED', 'message': str(_('User is not authenticated'))}, status=status.HTTP_401_UNAUTHORIZED)

        current_emp = get_current_employee(request)
        if not current_emp:
            return Response({'error': 'ERR_NO_PROFILE', 'message': str(_('Current user has no associated employee profile'))}, status=status.HTTP_400_BAD_REQUEST)

        supervisors_chain = get_supervision_chain_upwards(current_emp)
        supervisors_data = [
            {'outer_id': str(s.outer_id), 'username': s.username, 'full_name': s.full_name, 'job_title': s.job_title}
            for s in supervisors_chain
        ]

        descendant_ids = get_user_and_descendants(current_emp)
        # Exclude self from subordinates
        subordinate_ids = [d for d in descendant_ids if d != current_emp.id]
        subordinates = Employee.objects.filter(id__in=subordinate_ids, is_active=True).order_by('first_name')
        subordinates_data = [
            {'outer_id': str(s.outer_id), 'username': s.username, 'full_name': s.full_name, 'job_title': s.job_title}
            for s in subordinates
        ]

        return Response({
            'current_employee': {
                'outer_id': str(current_emp.outer_id),
                'username': current_emp.username,
                'full_name': current_emp.full_name,
                'job_title': current_emp.job_title,
                'employee_type': current_emp.employee_type,
            },
            'is_root': len(supervisors_chain) == 0,
            'supervisors': supervisors_data,
            'upward_chain': supervisors_data,
            'subordinates': subordinates_data,
        }, status=status.HTTP_200_OK)

