import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.employees.models import Employee

def seed_employees():
    employees_data = [
        {
            'id': 1,
            'user_id': 1,
            'username': 'ahmed',
            'first_name': 'Ahmed',
            'last_name': 'Al-Mansoor',
            'email': 'ahmed@company.com',
            'department': 'Backend Engineering',
            'job_title': 'Senior Software Engineer',
            'phone': '+966 50 111 2222',
        },
        {
            'id': 2,
            'user_id': 2,
            'username': 'mohammed',
            'first_name': 'Mohammed',
            'last_name': 'Al-Sayed',
            'email': 'mohammed@company.com',
            'department': 'Product Development',
            'job_title': 'Full Stack Developer',
            'phone': '+966 50 333 4444',
        },
        {
            'id': 3,
            'user_id': 3,
            'username': 'khaled',
            'first_name': 'Khaled',
            'last_name': 'Al-Rashid',
            'email': 'khaled@company.com',
            'department': 'DevOps & Reliability',
            'job_title': 'Systems Engineer',
            'phone': '+966 50 555 6666',
        },
        {
            'id': 4,
            'user_id': 4,
            'username': 'tariq',
            'first_name': 'Tariq',
            'last_name': 'Al-Harbi',
            'email': 'tariq@company.com',
            'department': 'Quality Assurance',
            'job_title': 'QA Automation Specialist',
            'phone': '+966 50 777 8888',
        },
    ]

    print("Seeding Employee Profiles in Employee Service...")
    for data in employees_data:
        emp_id = data.pop('id')
        user_id = data.pop('user_id')
        emp, created = Employee.objects.get_or_create(id=emp_id, defaults={'user_id': user_id, **data})
        if not created:
            emp.user_id = user_id
            for k, v in data.items():
                setattr(emp, k, v)
            emp.save()
        print(f"[{'Created' if created else 'Updated'}] Employee: {emp.full_name} (ID: {emp.id})")

    print("Employee seeding completed.")

if __name__ == '__main__':
    seed_employees()
