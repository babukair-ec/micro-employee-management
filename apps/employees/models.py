import uuid
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.utils import timezone
from apps.messaging.rabbitmq import publish_event

class Employee(models.Model):
    EMPLOYEE_TYPE_EMPLOYEE = 'EMPLOYEE'
    EMPLOYEE_TYPE_TESTER = 'TESTER'
    EMPLOYEE_TYPE_CHOICES = [
        (EMPLOYEE_TYPE_EMPLOYEE, _('Employee')),
        (EMPLOYEE_TYPE_TESTER, _('Tester')),
    ]

    id = models.BigAutoField(primary_key=True)
    outer_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    user_id = models.UUIDField(unique=True, verbose_name=_("User ID"))
    username = models.CharField(max_length=150, verbose_name=_("Username"))
    first_name = models.CharField(max_length=150, blank=True, default='', verbose_name=_("First Name"))
    last_name = models.CharField(max_length=150, blank=True, default='', verbose_name=_("Last Name"))
    email = models.EmailField(blank=True, null=True, verbose_name=_("Email"))
    job_title = models.CharField(max_length=100, default='Team Member', verbose_name=_("Job Title"))
    employee_type = models.CharField(
        max_length=20,
        choices=EMPLOYEE_TYPE_CHOICES,
        default=EMPLOYEE_TYPE_EMPLOYEE,
        verbose_name=_("Employee Type")
    )
    phone = models.CharField(max_length=50, blank=True, null=True, verbose_name=_("Phone"))
    is_active = models.BooleanField(default=True, verbose_name=_("Is Active"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))

    class Meta:
        db_table = 'employees_employee'
        verbose_name = _("Employee")
        verbose_name_plural = _("Employees")

    @property
    def full_name(self):
        name = f"{self.first_name} {self.last_name}".strip()
        return name if name else self.username

    def __str__(self):
        return self.full_name

    def to_event_dict(self):
        return {
            'id': self.id,
            'outer_id': str(self.outer_id),
            'user_id': str(self.user_id),
            'username': self.username,
            'full_name': self.full_name,
            'email': self.email or None,
            'job_title': self.job_title,
            'employee_type': self.employee_type,
            'phone': self.phone or None,
            'is_active': self.is_active,
        }

@receiver(post_save, sender=Employee)
def employee_post_save(sender, instance, created, **kwargs):
    event_name = 'employee.created' if created else 'employee.updated'
    publish_event(event_name, instance.to_event_dict())


class Supervision(models.Model):
    """
    Self-referential join model on Employee tracking supervisory hierarchy.
    Enforces a database constraint and validation rule preventing self-supervision.
    """
    id = models.BigAutoField(primary_key=True)
    outer_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    supervisor = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='subordinates',
        verbose_name=_("Supervisor")
    )
    subordinate = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='supervisors',
        verbose_name=_("Subordinate")
    )
    start_date = models.DateField(verbose_name=_("Start Date"))
    end_date = models.DateField(null=True, blank=True, verbose_name=_("End Date"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))

    class Meta:
        db_table = 'supervisions'
        verbose_name = _("Supervision")
        verbose_name_plural = _("Supervisions")
        constraints = [
            models.CheckConstraint(
                check=~models.Q(supervisor=models.F('subordinate')),
                name='prevent_self_supervision'
            ),
            models.UniqueConstraint(
                fields=['supervisor', 'subordinate'],
                name='unique_supervision_pair'
            ),
        ]

    def clean(self):
        super().clean()
        if self.supervisor_id and self.subordinate_id and self.supervisor_id == self.subordinate_id:
            raise ValidationError(_("An employee cannot supervise themselves."))

    def __str__(self):
        return f"{self.supervisor} -> {self.subordinate} ({self.start_date} to {self.end_date or 'Present'})"


class DepartmentOrProject(models.Model):
    """
    Stores departments and projects within the organization.
    Every PROJECT must belong to exactly one DEPARTMENT.
    A DEPARTMENT cannot belong to another department or project.
    """
    TYPE_DEPARTMENT = 'DEPARTMENT'
    TYPE_PROJECT = 'PROJECT'
    TYPE_CHOICES = [
        (TYPE_DEPARTMENT, _('Department')),
        (TYPE_PROJECT, _('Project')),
    ]

    id = models.BigAutoField(primary_key=True)
    outer_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    name = models.CharField(max_length=200, verbose_name=_("Name"))
    code = models.CharField(max_length=50, unique=True, verbose_name=_("Unique Code"))
    description = models.TextField(blank=True, default='', verbose_name=_("Description"))
    type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default=TYPE_DEPARTMENT,
        verbose_name=_("Type")
    )
    department = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='projects',
        verbose_name=_("Parent Department")
    )
    manager = models.ForeignKey(
        'Employee',
        on_delete=models.PROTECT,
        related_name='managed_departments_projects',
        verbose_name=_("Manager")
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))

    class Meta:
        db_table = 'departments_or_projects'
        verbose_name = _("Department or Project")
        verbose_name_plural = _("Departments and Projects")

    def clean(self):
        super().clean()
        if self.type == self.TYPE_PROJECT:
            if not self.department_id:
                raise ValidationError({'department': _("A project must belong to a department.")})
            if self.department and self.department.type != self.TYPE_DEPARTMENT:
                raise ValidationError({'department': _("A project cannot belong to another project. It must belong to a department.")})
            if self.id and self.department_id == self.id:
                raise ValidationError({'department': _("A project cannot be its own department.")})
        elif self.type == self.TYPE_DEPARTMENT:
            if self.department_id:
                raise ValidationError({'department': _("A department cannot belong to another department or project.")})

    def __str__(self):
        return f"[{self.type}] {self.name} ({self.code})"


class EmployeeDepartmentProject(models.Model):
    """
    M:N join table between Employee and DepartmentOrProject.
    Tracks active assignments and past assignments with timestamps.
    """
    id = models.BigAutoField(primary_key=True)
    outer_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='department_projects',
        verbose_name=_("Employee")
    )
    department_project = models.ForeignKey(
        DepartmentOrProject,
        on_delete=models.CASCADE,
        related_name='employee_assignments',
        verbose_name=_("Department or Project")
    )
    is_current = models.BooleanField(default=True, verbose_name=_("Is Current"))
    assigned_at = models.DateTimeField(default=timezone.now, verbose_name=_("Assigned At"))
    ended_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Ended At"))

    class Meta:
        db_table = 'employee_department_projects'
        verbose_name = _("Employee Department Project")
        verbose_name_plural = _("Employee Department Projects")

    def clean(self):
        super().clean()
        if not self.is_current or not self.employee_id or not self.department_project_id:
            return

        target_unit = self.department_project

        if target_unit.type == DepartmentOrProject.TYPE_PROJECT:
            # Rule: An employee cannot be assigned to more than one project
            other_project = EmployeeDepartmentProject.objects.filter(
                employee_id=self.employee_id,
                department_project__type=DepartmentOrProject.TYPE_PROJECT,
                is_current=True
            ).exclude(id=self.id).exclude(department_project_id=self.department_project_id).select_related('department_project').first()
            if other_project:
                raise ValidationError({
                    'department_project': _("An employee cannot be assigned to more than one project. Employee is already assigned to '%(proj)s'.") % {
                        'proj': other_project.department_project.name
                    }
                })

            # Rule: If assigned to a department, project must belong to that same department
            active_dept = EmployeeDepartmentProject.objects.filter(
                employee_id=self.employee_id,
                department_project__type=DepartmentOrProject.TYPE_DEPARTMENT,
                is_current=True
            ).exclude(id=self.id).select_related('department_project').first()
            if active_dept and target_unit.department_id:
                if target_unit.department_id != active_dept.department_project_id:
                    dept_name = active_dept.department_project.name
                    proj_dept_name = target_unit.department.name if target_unit.department else "N/A"
                    raise ValidationError({
                        'department_project': _("An employee can only be assigned to a project within their assigned department. Employee belongs to '%(dept)s', while project belongs to '%(proj_dept)s'.") % {
                            'dept': dept_name,
                            'proj_dept': proj_dept_name
                        }
                    })

        elif target_unit.type == DepartmentOrProject.TYPE_DEPARTMENT:
            # Rule: If employee has an active project, it must belong to this department
            active_proj = EmployeeDepartmentProject.objects.filter(
                employee_id=self.employee_id,
                department_project__type=DepartmentOrProject.TYPE_PROJECT,
                is_current=True
            ).exclude(id=self.id).select_related('department_project', 'department_project__department').first()
            if active_proj and active_proj.department_project.department_id:
                if active_proj.department_project.department_id != self.department_project_id:
                    proj_name = active_proj.department_project.name
                    proj_dept_name = active_proj.department_project.department.name if active_proj.department_project.department else "N/A"
                    raise ValidationError({
                        'department_project': _("The employee is currently assigned to project '%(proj)s' under department '%(proj_dept)s', and cannot be assigned to a different department.") % {
                            'proj': proj_name,
                            'proj_dept': proj_dept_name
                        }
                    })

            # Rule: An employee cannot be assigned to more than one department
            other_dept = EmployeeDepartmentProject.objects.filter(
                employee_id=self.employee_id,
                department_project__type=DepartmentOrProject.TYPE_DEPARTMENT,
                is_current=True
            ).exclude(id=self.id).exclude(department_project_id=self.department_project_id).select_related('department_project').first()
            if other_dept:
                raise ValidationError({
                    'department_project': _("The employee is already assigned to department '%(dept)s'. An employee cannot be assigned to more than one department.") % {
                        'dept': other_dept.department_project.name
                    }
                })

    def __str__(self):
        status = "Current" if self.is_current else "Past"
        return f"{self.employee} in {self.department_project} ({status})"


class SupervisionRequest(models.Model):
    """
    Model representing supervision creation/transfer/escalation requests.
    Supports dynamic authority determination and escalation workflows.
    """
    STATUS_PENDING = 'PENDING'
    STATUS_APPROVED = 'APPROVED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_CANCELLED = 'CANCELLED'
    STATUS_ESCALATED = 'ESCALATED'
    STATUS_CHOICES = [
        (STATUS_PENDING, _('Pending')),
        (STATUS_APPROVED, _('Approved')),
        (STATUS_REJECTED, _('Rejected')),
        (STATUS_CANCELLED, _('Cancelled')),
        (STATUS_ESCALATED, _('Escalated')),
    ]

    TYPE_SUPERVISE_TARGET = 'REQUEST_TO_SUPERVISE'
    TYPE_BE_SUPERVISED = 'REQUEST_TO_BE_SUPERVISED'
    TYPE_CHOICES = [
        (TYPE_SUPERVISE_TARGET, _('Request to Supervise Target')),
        (TYPE_BE_SUPERVISED, _('Request to be Supervised by Target')),
    ]

    id = models.BigAutoField(primary_key=True)
    outer_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    requester = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='requested_supervisions',
        verbose_name=_("Requester")
    )
    target_employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='supervision_requests_as_target',
        verbose_name=_("Target Employee")
    )
    request_type = models.CharField(
        max_length=50,
        choices=TYPE_CHOICES,
        default=TYPE_SUPERVISE_TARGET,
        verbose_name=_("Request Type")
    )
    proposed_supervisor = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='proposed_supervisor_requests',
        verbose_name=_("Proposed Supervisor")
    )
    proposed_subordinate = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='proposed_subordinate_requests',
        verbose_name=_("Proposed Subordinate")
    )
    current_supervisor = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='relinquishing_supervision_requests',
        verbose_name=_("Current Supervisor")
    )
    current_approver = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='assigned_supervision_approvals',
        verbose_name=_("Current Approver")
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        verbose_name=_("Status")
    )
    decision_reason = models.TextField(blank=True, default='', verbose_name=_("Decision Reason"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    responded_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Responded At"))
    escalated_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Escalated At"))
    escalated_to = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='escalated_supervision_requests',
        verbose_name=_("Escalated To")
    )

    class Meta:
        db_table = 'supervision_requests'
        verbose_name = _("Supervision Request")
        verbose_name_plural = _("Supervision Requests")
        ordering = ['-created_at']

    def clean(self):
        super().clean()
        if self.proposed_supervisor_id and self.proposed_subordinate_id:
            if self.proposed_supervisor_id == self.proposed_subordinate_id:
                raise ValidationError(_("An employee cannot supervise themselves."))

    def __str__(self):
        return f"Request [{self.status}]: {self.proposed_supervisor} -> {self.proposed_subordinate} (Approver: {self.current_approver})"
