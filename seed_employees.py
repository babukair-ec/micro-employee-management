import os
import django
from datetime import date

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.employees.models import (
    Employee,
    Supervision,
    DepartmentOrProject,
    EmployeeDepartmentProject,
)

def seed_employees():
    employees_data = [
        {
            'id': '11111111-1111-4111-8111-111111111111',
            'user_id': '11111111-1111-4111-8111-111111111111',
            'username': 'ahmed',
            'first_name': 'Ahmed',
            'last_name': 'Al-Mansoor',
            'email': 'ahmed@company.com',
            'job_title': 'Lead Architect & Engineering Director',
            'phone': '+966 50 111 2222',
        },
        {
            'id': '22222222-2222-4222-8222-222222222222',
            'user_id': '22222222-2222-4222-8222-222222222222',
            'username': 'mohammed',
            'first_name': 'Mohammed',
            'last_name': 'Al-Sayed',
            'email': 'mohammed@company.com',
            'job_title': 'Senior Full Stack Developer',
            'phone': '+966 50 333 4444',
        },
        {
            'id': '33333333-3333-4333-8333-333333333333',
            'user_id': '33333333-3333-4333-8333-333333333333',
            'username': 'khaled',
            'first_name': 'Khaled',
            'last_name': 'Al-Rashid',
            'email': 'khaled@company.com',
            'job_title': 'DevOps & Infrastructure Lead',
            'phone': '+966 50 555 6666',
        },
        {
            'id': '44444444-4444-4444-8444-444444444444',
            'user_id': '44444444-4444-4444-8444-444444444444',
            'username': 'tariq',
            'first_name': 'Tariq',
            'last_name': 'Al-Harbi',
            'email': 'tariq@company.com',
            'job_title': 'QA Automation Specialist',
            'employee_type': 'TESTER',
            'phone': '+966 50 777 8888',
        },
        {
            'id': '55555555-5555-4555-8555-555555555555',
            'user_id': '55555555-5555-4555-8555-555555555555',
            'username': 'sarah',
            'first_name': 'Sarah',
            'last_name': 'Al-Otaibi',
            'email': 'sarah@company.com',
            'job_title': 'Product Manager & UX Lead',
            'employee_type': 'EMPLOYEE',
            'phone': '+966 50 888 9999',
        },
        {
            'id': '66666666-6666-4666-8666-666666666666',
            'user_id': '66666666-6666-4666-8666-666666666666',
            'username': 'fahad',
            'first_name': 'Fahad',
            'last_name': 'Al-Ghamdi',
            'email': 'fahad@company.com',
            'job_title': 'Junior Frontend Developer',
            'employee_type': 'EMPLOYEE',
            'phone': '+966 50 999 0000',
        },
    ]

    print("\n=======================================================")
    print(" [2/4] Seeding Employee Service (Profiles & Hierarchy)...")
    print("=======================================================")
    created_employees = {}
    for data in employees_data:
        emp_id = data.pop('id')
        user_id = data.pop('user_id')
        username = data.get('username')
        emp, created = Employee.objects.get_or_create(
            username=username,
            defaults={'outer_id': emp_id, 'user_id': user_id, **data}
        )
        emp.outer_id = emp_id
        emp.user_id = user_id
        for k, v in data.items():
            setattr(emp, k, v)
        emp.save()
        created_employees[emp.username] = emp
        print(f" -> {'[Created]' if created else '[Updated]'} Employee: {emp.full_name} (@{emp.username}) [ID: {emp.id}, Outer ID: {emp.outer_id}]")

    # Seed Departments and Projects with Managers
    print("\n -> Seeding Departments and Projects with Assigned Managers...")
    departments_data = [
        {
            'code': 'ENG-CORE',
            'name': 'Core Engineering Department',
            'description': 'Architecture, backend services, and distributed systems division',
            'type': 'DEPARTMENT',
            'department': None,
            'manager': created_employees['ahmed'],
        },
        {
            'code': 'PROD-DESIGN',
            'name': 'Product & UI/UX Department',
            'description': 'User experience, product discovery, and interface engineering',
            'type': 'DEPARTMENT',
            'department': None,
            'manager': created_employees['sarah'],
        },
        {
            'code': 'OPS-INFRA',
            'name': 'Cloud Infrastructure & SRE Department',
            'description': 'DevOps, site reliability, CI/CD pipelines, and cloud platform',
            'type': 'DEPARTMENT',
            'department': None,
            'manager': created_employees['khaled'],
        },
    ]

    created_depts = {}
    for d_data in departments_data:
        code = d_data['code']
        dept, created = DepartmentOrProject.objects.get_or_create(
            code=code,
            defaults=d_data
        )
        if not created:
            for k, v in d_data.items():
                setattr(dept, k, v)
            dept.save()
        created_depts[code] = dept
        print(f" -> {'[Created]' if created else '[Updated]'} Unit: {dept.name} [{dept.code}] - Manager: {dept.manager.full_name if dept.manager else 'None'}")

    projects_data = [
        {
            'code': 'PROJ-CLOUD-2026',
            'name': 'Cloud Native Multi-Region Migration',
            'description': 'Migrating legacy monolith workload to distributed Kubernetes cluster',
            'type': 'PROJECT',
            'department': created_depts['ENG-CORE'],
            'manager': created_employees['ahmed'],
        },
        {
            'code': 'PROJ-MOBILE-APP',
            'name': 'NextGen Mobile Experience',
            'description': 'Redesigning cross-platform mobile client with offline-first sync',
            'type': 'PROJECT',
            'department': created_depts['ENG-CORE'],
            'manager': created_employees['mohammed'],
        },
        {
            'code': 'PROJ-PAYMENTS-V2',
            'name': 'Global Payments & Billing Gateway',
            'description': 'PCI-DSS compliant payment processing engine with instant settlement',
            'type': 'PROJECT',
            'department': created_depts['ENG-CORE'],
            'manager': created_employees['mohammed'],
        },
        {
            'code': 'PROJ-SECURITY-AUDIT',
            'name': 'SOC2 Type II & Penetration Testing',
            'description': 'Organizational security compliance and automated audit controls',
            'type': 'PROJECT',
            'department': created_depts['OPS-INFRA'],
            'manager': created_employees['khaled'],
        },
    ]

    for p_data in projects_data:
        code = p_data['code']
        proj, created = DepartmentOrProject.objects.get_or_create(
            code=code,
            defaults=p_data
        )
        if not created:
            for k, v in p_data.items():
                setattr(proj, k, v)
            proj.save()
        created_depts[code] = proj
        print(f" -> {'[Created]' if created else '[Updated]'} Project: {proj.name} [{proj.code}] under Dept: {proj.department.name}")

    # Seed Department / Project Assignments
    print("\n -> Seeding Employee Unit Assignments...")
    assignments_list = [
        ('ahmed', 'ENG-CORE'),
        ('ahmed', 'PROJ-CLOUD-2026'),
        ('mohammed', 'ENG-CORE'),
        ('mohammed', 'PROJ-MOBILE-APP'),
        ('mohammed', 'PROJ-PAYMENTS-V2'),
        ('khaled', 'OPS-INFRA'),
        ('khaled', 'PROJ-CLOUD-2026'),
        ('khaled', 'PROJ-SECURITY-AUDIT'),
        ('tariq', 'ENG-CORE'),
        ('tariq', 'PROJ-MOBILE-APP'),
        ('sarah', 'PROD-DESIGN'),
        ('sarah', 'PROJ-MOBILE-APP'),
        ('fahad', 'ENG-CORE'),
        ('fahad', 'PROJ-PAYMENTS-V2'),
    ]

    for username, dept_code in assignments_list:
        if username in created_employees and dept_code in created_depts:
            EmployeeDepartmentProject.objects.get_or_create(
                employee=created_employees[username],
                department_project=created_depts[dept_code],
                defaults={'is_current': True}
            )
    print(f" -> Created {len(assignments_list)} active unit assignments.")

    # Seed Multi-Level Supervision Hierarchy
    print("\n -> Seeding Multi-Level Supervision Hierarchy...")
    supervisions_list = [
        # Level 1: Ahmed -> Mohammed, Khaled
        ('ahmed', 'mohammed', date(2025, 1, 15)),
        ('ahmed', 'khaled', date(2025, 2, 1)),
        # Level 2: Mohammed -> Tariq, Fahad
        ('mohammed', 'tariq', date(2025, 3, 1)),
        ('mohammed', 'fahad', date(2025, 4, 15)),
    ]

    for sup_user, sub_user, start_dt in supervisions_list:
        if sup_user in created_employees and sub_user in created_employees:
            Supervision.objects.get_or_create(
                supervisor=created_employees[sup_user],
                subordinate=created_employees[sub_user],
                defaults={'start_date': start_dt}
            )
            print(f" -> Supervision Link: {created_employees[sup_user].full_name} -> {created_employees[sub_user].full_name}")

    print(" -> Employee Service seeding successfully completed.\n")

if __name__ == '__main__':
    seed_employees()
