from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext_lazy as _
from apps.employees.models import (
    Employee,
    Supervision,
    DepartmentOrProject,
    EmployeeDepartmentProject,
    SupervisionRequest,
)

class EmployeeOuterIdRelatedField(serializers.RelatedField):
    """
    Serializes Employee instances to their outer_id (UUID string) instead of integer id.
    Accepts Employee instance, outer_id UUID string, or integer id on input,
    and resolves to the Employee instance.
    """
    def get_queryset(self):
        return Employee.objects.all()

    def to_representation(self, value):
        if value is None:
            return None
        return str(getattr(value, 'outer_id', value))

    def to_internal_value(self, data):
        if not data:
            return None
        if isinstance(data, Employee):
            return data
        try:
            if str(data).isdigit():
                return Employee.objects.get(id=int(data))
            return Employee.objects.get(outer_id=data)
        except (Employee.DoesNotExist, ValueError):
            raise serializers.ValidationError(_(f"Employee with identifier '{data}' not found."))


class DepartmentOrProjectSerializer(serializers.ModelSerializer):
    manager = EmployeeOuterIdRelatedField(queryset=Employee.objects.all(), required=False, allow_null=True)
    manager_name = serializers.CharField(source='manager.full_name', read_only=True)
    manager_username = serializers.CharField(source='manager.username', read_only=True)
    department_name = serializers.CharField(source='department.name', read_only=True, allow_null=True)
    department_code = serializers.CharField(source='department.code', read_only=True, allow_null=True)

    class Meta:
        model = DepartmentOrProject
        fields = [
            'id',
            'outer_id',
            'name',
            'code',
            'description',
            'type',
            'department',
            'department_name',
            'department_code',
            'manager',
            'manager_name',
            'manager_username',
            'created_at',
            'updated_at',
        ]

    def validate(self, data):
        obj_type = data.get('type', getattr(self.instance, 'type', None))
        department = data.get('department', getattr(self.instance, 'department', None))

        if obj_type == DepartmentOrProject.TYPE_PROJECT:
            if not department:
                raise serializers.ValidationError({'department': 'A project must belong to a department.'})
            if department.type != DepartmentOrProject.TYPE_DEPARTMENT:
                raise serializers.ValidationError({'department': 'Parent entity must be a Department, not a Project.'})
            if self.instance and department.id == self.instance.id:
                raise serializers.ValidationError({'department': 'A project cannot be its own department.'})
        elif obj_type == DepartmentOrProject.TYPE_DEPARTMENT:
            if department is not None:
                raise serializers.ValidationError({'department': 'A department cannot belong to another department or project.'})
        return data


class EmployeeDepartmentProjectSerializer(serializers.ModelSerializer):
    department_project_details = DepartmentOrProjectSerializer(source='department_project', read_only=True)
    employee = EmployeeOuterIdRelatedField(queryset=Employee.objects.all())
    employee_name = serializers.CharField(source='employee.full_name', read_only=True)

    class Meta:
        model = EmployeeDepartmentProject
        fields = [
            'id',
            'outer_id',
            'employee',
            'employee_name',
            'department_project',
            'department_project_details',
            'is_current',
            'assigned_at',
            'ended_at',
        ]

    def validate(self, attrs):
        instance = self.instance or EmployeeDepartmentProject()
        for attr, val in attrs.items():
            setattr(instance, attr, val)
        try:
            instance.clean()
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.message_dict if hasattr(e, 'message_dict') else e.messages)
        return attrs


class SupervisionSerializer(serializers.ModelSerializer):
    supervisor = EmployeeOuterIdRelatedField(queryset=Employee.objects.all())
    subordinate = EmployeeOuterIdRelatedField(queryset=Employee.objects.all())
    supervisor_name = serializers.CharField(source='supervisor.full_name', read_only=True)
    subordinate_name = serializers.CharField(source='subordinate.full_name', read_only=True)

    class Meta:
        model = Supervision
        fields = [
            'id',
            'outer_id',
            'supervisor',
            'supervisor_name',
            'subordinate',
            'subordinate_name',
            'start_date',
            'end_date',
            'created_at',
        ]

    def validate(self, data):
        supervisor = data.get('supervisor')
        subordinate = data.get('subordinate')
        if supervisor and subordinate and supervisor == subordinate:
            raise serializers.ValidationError("An employee cannot supervise themselves.")
        return data


class EmployeeSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(required=True)
    username = serializers.CharField(required=True)
    first_name = serializers.CharField(required=True)
    last_name = serializers.CharField(required=True)
    email = serializers.EmailField(required=True)
    job_title = serializers.CharField(required=True)
    phone = serializers.CharField(max_length=50, required=False, allow_null=True, allow_blank=True, default=None)
    full_name = serializers.CharField(read_only=True)
    supervisors = serializers.SerializerMethodField()
    subordinates = serializers.SerializerMethodField()
    current_projects_departments = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = [
            'outer_id',
            'user_id',
            'username',
            'first_name',
            'last_name',
            'full_name',
            'email',
            'job_title',
            'employee_type',
            'phone',
            'is_active',
            'supervisors',
            'subordinates',
            'current_projects_departments',
            'created_at',
        ]

    def create(self, validated_data):
        from django.db import models
        if not validated_data.get('email'):
            validated_data['email'] = None
        if not validated_data.get('phone'):
            validated_data['phone'] = None

        user_id = validated_data.get('user_id')
        username = validated_data.get('username')

        # If employee already exists with this user_id or username, update and return it idempotently
        existing = Employee.objects.filter(models.Q(user_id=user_id) | models.Q(username=username)).first()
        if existing:
            for k, v in validated_data.items():
                setattr(existing, k, v)
            existing.save()
            return existing

        return super().create(validated_data)

    def get_supervisors(self, obj):
        active_supervisions = obj.supervisors.filter(end_date__isnull=True)
        return [
            {
                'outer_id': str(s.supervisor.outer_id),
                'name': s.supervisor.full_name,
                'start_date': s.start_date,
            }
            for s in active_supervisions
        ]

    def get_subordinates(self, obj):
        active_subordinates = obj.subordinates.filter(end_date__isnull=True)
        return [
            {
                'outer_id': str(s.subordinate.outer_id),
                'name': s.subordinate.full_name,
                'start_date': s.start_date,
            }
            for s in active_subordinates
        ]

    def get_current_projects_departments(self, obj):
        assignments = obj.department_projects.filter(is_current=True).select_related('department_project', 'department_project__department')
        return [
            {
                'id': a.department_project.id,
                'outer_id': str(a.department_project.outer_id),
                'name': a.department_project.name,
                'code': a.department_project.code,
                'type': a.department_project.type,
                'department_id': a.department_project.department_id,
                'department_outer_id': str(a.department_project.department.outer_id) if a.department_project.department else None,
                'department_name': a.department_project.department.name if a.department_project.department else None,
                'assigned_at': a.assigned_at,
            }
            for a in assignments
        ]


class SupervisionRequestSerializer(serializers.ModelSerializer):
    requester = EmployeeOuterIdRelatedField(queryset=Employee.objects.all(), read_only=True)
    requester_name = serializers.CharField(source='requester.full_name', read_only=True)
    requester_username = serializers.CharField(source='requester.username', read_only=True)
    target_employee = EmployeeOuterIdRelatedField(queryset=Employee.objects.all())
    target_employee_name = serializers.CharField(source='target_employee.full_name', read_only=True)
    target_employee_username = serializers.CharField(source='target_employee.username', read_only=True)
    proposed_supervisor = EmployeeOuterIdRelatedField(queryset=Employee.objects.all(), read_only=True)
    proposed_supervisor_name = serializers.CharField(source='proposed_supervisor.full_name', read_only=True)
    proposed_subordinate = EmployeeOuterIdRelatedField(queryset=Employee.objects.all(), read_only=True)
    proposed_subordinate_name = serializers.CharField(source='proposed_subordinate.full_name', read_only=True)
    current_supervisor = EmployeeOuterIdRelatedField(queryset=Employee.objects.all(), read_only=True, allow_null=True)
    current_supervisor_name = serializers.CharField(source='current_supervisor.full_name', read_only=True, allow_null=True)
    current_approver = EmployeeOuterIdRelatedField(queryset=Employee.objects.all(), read_only=True)
    current_approver_name = serializers.CharField(source='current_approver.full_name', read_only=True)
    current_approver_username = serializers.CharField(source='current_approver.username', read_only=True)
    escalated_to = EmployeeOuterIdRelatedField(queryset=Employee.objects.all(), read_only=True, allow_null=True)

    class Meta:
        model = SupervisionRequest
        fields = [
            'id',
            'outer_id',
            'requester',
            'requester_name',
            'requester_username',
            'target_employee',
            'target_employee_name',
            'target_employee_username',
            'request_type',
            'proposed_supervisor',
            'proposed_supervisor_name',
            'proposed_subordinate',
            'proposed_subordinate_name',
            'current_supervisor',
            'current_supervisor_name',
            'current_approver',
            'current_approver_name',
            'current_approver_username',
            'status',
            'decision_reason',
            'created_at',
            'responded_at',
            'escalated_at',
            'escalated_to',
        ]
        read_only_fields = [
            'id',
            'requester',
            'proposed_supervisor',
            'proposed_subordinate',
            'current_supervisor',
            'current_approver',
            'status',
            'created_at',
            'responded_at',
            'escalated_at',
            'escalated_to',
        ]
