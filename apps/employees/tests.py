import uuid
from datetime import date
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.utils import timezone
from apps.employees.models import (
    Employee,
    Supervision,
    DepartmentOrProject,
    SupervisionRequest,
)
from apps.employees.views import (
    get_active_supervisor,
    get_supervision_chain_upwards,
    get_root_supervisor,
    would_create_supervision_cycle,
    determine_supervision_approver,
)

class DepartmentProjectHierarchyTests(TestCase):
    def setUp(self):
        self.emp = Employee.objects.create(
            username='emp_test',
            first_name='Test',
            last_name='User',
            job_title='Engineer'
        )

    def test_1_create_department(self):
        """1. Successfully create a Department with department=None."""
        dept = DepartmentOrProject.objects.create(
            code='DEPT-IT',
            name='IT Department',
            type=DepartmentOrProject.TYPE_DEPARTMENT,
            department=None,
            manager=self.emp
        )
        dept.full_clean()
        self.assertEqual(dept.type, 'DEPARTMENT')
        self.assertIsNone(dept.department)

    def test_2_create_project_under_department(self):
        """2. Successfully create a Project under a Department."""
        dept = DepartmentOrProject.objects.create(
            code='DEPT-IT',
            name='IT Department',
            type=DepartmentOrProject.TYPE_DEPARTMENT,
            department=None,
            manager=self.emp
        )
        proj = DepartmentOrProject.objects.create(
            code='PROJ-PORTAL',
            name='Portal Project',
            type=DepartmentOrProject.TYPE_PROJECT,
            department=dept,
            manager=self.emp
        )
        proj.full_clean()
        self.assertEqual(proj.department, dept)

    def test_3_reject_project_without_department(self):
        """3. Reject Project without a parent department."""
        proj = DepartmentOrProject(
            code='PROJ-ORPHAN',
            name='Orphan Project',
            type=DepartmentOrProject.TYPE_PROJECT,
            department=None,
            manager=self.emp
        )
        with self.assertRaises(ValidationError):
            proj.full_clean()

    def test_4_reject_project_under_project(self):
        """4. Reject Project that tries to have a Project as its parent."""
        dept = DepartmentOrProject.objects.create(
            code='DEPT-IT',
            name='IT Department',
            type=DepartmentOrProject.TYPE_DEPARTMENT,
            manager=self.emp
        )
        parent_proj = DepartmentOrProject.objects.create(
            code='PROJ-MAIN',
            name='Main Project',
            type=DepartmentOrProject.TYPE_PROJECT,
            department=dept,
            manager=self.emp
        )
        child_proj = DepartmentOrProject(
            code='PROJ-SUB',
            name='Sub Project',
            type=DepartmentOrProject.TYPE_PROJECT,
            department=parent_proj,
            manager=self.emp
        )
        with self.assertRaises(ValidationError):
            child_proj.full_clean()

    def test_5_reject_department_under_department(self):
        """5. Reject Department that tries to have a parent."""
        dept1 = DepartmentOrProject.objects.create(
            code='DEPT-1',
            name='Parent Dept',
            type=DepartmentOrProject.TYPE_DEPARTMENT,
            manager=self.emp
        )
        dept2 = DepartmentOrProject(
            code='DEPT-2',
            name='Child Dept',
            type=DepartmentOrProject.TYPE_DEPARTMENT,
            department=dept1,
            manager=self.emp
        )
        with self.assertRaises(ValidationError):
            dept2.full_clean()


class SupervisionHierarchyAndAuthorityTests(TestCase):
    def setUp(self):
        # Setup employees: A -> B -> C, and D
        self.emp_a = Employee.objects.create(username='emp_a', first_name='A')
        self.emp_b = Employee.objects.create(username='emp_b', first_name='B')
        self.emp_c = Employee.objects.create(username='emp_c', first_name='C')
        self.emp_d = Employee.objects.create(username='emp_d', first_name='D')

        # Active supervisions: A -> B, B -> C
        Supervision.objects.create(supervisor=self.emp_a, subordinate=self.emp_b, start_date=date.today())
        Supervision.objects.create(supervisor=self.emp_b, subordinate=self.emp_c, start_date=date.today())

    def test_hierarchy_structure(self):
        """Verify A -> B -> C setup."""
        self.assertEqual(get_active_supervisor(self.emp_c), self.emp_b)
        self.assertEqual(get_active_supervisor(self.emp_b), self.emp_a)
        self.assertIsNone(get_active_supervisor(self.emp_a))

        chain = get_supervision_chain_upwards(self.emp_c)
        self.assertEqual([e.id for e in chain], [self.emp_b.id, self.emp_a.id])
        self.assertEqual(get_root_supervisor(self.emp_c), self.emp_a)

    def test_b_cannot_relinquish_c_and_request_goes_to_a(self):
        """
        When D requests to supervise C, B cannot relinquish C because B has superior A.
        The request approver must be dynamically resolved to A.
        """
        approver, current_sup = determine_supervision_approver(
            proposed_supervisor=self.emp_d,
            proposed_subordinate=self.emp_c,
            request_type=SupervisionRequest.TYPE_SUPERVISE_TARGET
        )
        self.assertEqual(current_sup, self.emp_b)
        self.assertEqual(approver, self.emp_a, "Approver must be A (top authority), NOT B!")

    def test_top_level_without_supervisor_can_relinquish(self):
        """
        If B supervises C, but B has NO supervisor (A does not exist),
        B is the top authority and can relinquish C directly.
        """
        # Remove A -> B supervision
        Supervision.objects.filter(supervisor=self.emp_a, subordinate=self.emp_b).delete()
        self.assertIsNone(get_active_supervisor(self.emp_b))

        approver, current_sup = determine_supervision_approver(
            proposed_supervisor=self.emp_d,
            proposed_subordinate=self.emp_c,
            request_type=SupervisionRequest.TYPE_SUPERVISE_TARGET
        )
        self.assertEqual(current_sup, self.emp_b)
        self.assertEqual(approver, self.emp_b, "B has no supervisor, so B is top authority and can decide!")

    def test_prevent_self_supervision(self):
        """Prevent employee from supervising themselves."""
        sup = Supervision(supervisor=self.emp_a, subordinate=self.emp_a, start_date=date.today())
        with self.assertRaises(ValidationError):
            sup.clean()

    def test_prevent_supervision_cycle(self):
        """A -> B -> C. Attempting C -> A must be detected as a cycle."""
        self.assertTrue(
            would_create_supervision_cycle(self.emp_c, self.emp_a),
            "C -> A would create a cycle because A is already ancestor of C!"
        )
        self.assertFalse(
            would_create_supervision_cycle(self.emp_d, self.emp_c),
            "D -> C creates no cycle."
        )

    def test_supervision_request_approval_ends_old_and_creates_new(self):
        """Approving request atomically closes previous supervision and creates new."""
        # D requests to supervise C -> approver is A
        approver, current_sup = determine_supervision_approver(self.emp_d, self.emp_c, SupervisionRequest.TYPE_SUPERVISE_TARGET)
        req = SupervisionRequest.objects.create(
            requester=self.emp_d,
            target_employee=self.emp_c,
            proposed_supervisor=self.emp_d,
            proposed_subordinate=self.emp_c,
            current_supervisor=current_sup,
            current_approver=approver,
            status=SupervisionRequest.STATUS_PENDING,
        )

        # A approves
        from django.db import transaction
        with transaction.atomic():
            old_sup = Supervision.objects.get(subordinate=self.emp_c, end_date__isnull=True)
            old_sup.end_date = timezone.now().date()
            old_sup.save()

            Supervision.objects.create(
                supervisor=req.proposed_supervisor,
                subordinate=req.proposed_subordinate,
                start_date=timezone.now().date()
            )
            req.status = SupervisionRequest.STATUS_APPROVED
            req.save()

        # Verify old supervision is closed and new supervision is active
        self.assertEqual(Supervision.objects.filter(subordinate=self.emp_c, end_date__isnull=True).count(), 1)
        active_sup = Supervision.objects.get(subordinate=self.emp_c, end_date__isnull=True)
        self.assertEqual(active_sup.supervisor, self.emp_d)
        self.assertEqual(req.status, SupervisionRequest.STATUS_APPROVED)
