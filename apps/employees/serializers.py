from rest_framework import serializers
from apps.employees.models import Employee

class EmployeeSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Employee
        fields = [
            'id',
            'user_id',
            'username',
            'first_name',
            'last_name',
            'full_name',
            'email',
            'department',
            'job_title',
            'phone',
            'is_active',
            'created_at',
        ]
