from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.employees.models import Employee
from apps.employees.serializers import EmployeeSerializer
from django.utils.translation import gettext_lazy as _

def check_authenticated(request):
    """Explicitly verify whether or not the user is authenticated."""
    return bool(request.user and getattr(request.user, 'is_authenticated', False))

class CheckAuthView(APIView):
    """Endpoint to explicitly check whether or not the user is authenticated."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        if check_authenticated(request):
            return Response({
                'authenticated': True,
                'user_id': getattr(request.user, 'id', None),
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
    queryset = Employee.objects.filter(is_active=True).order_by('first_name', 'username')
    serializer_class = EmployeeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request, *args, **kwargs):
        if not check_authenticated(request):
            return Response({
                'error': 'ERR_UNAUTHORIZED',
                'message': str(_('User is not authenticated'))
            }, status=status.HTTP_401_UNAUTHORIZED)
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        if not check_authenticated(request):
            return Response({
                'error': 'ERR_UNAUTHORIZED',
                'message': str(_('User is not authenticated'))
            }, status=status.HTTP_401_UNAUTHORIZED)
        return super().create(request, *args, **kwargs)

class EmployeeDetailView(generics.RetrieveUpdateAPIView):
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

    def update(self, request, *args, **kwargs):
        if not check_authenticated(request):
            return Response({
                'error': 'ERR_UNAUTHORIZED',
                'message': str(_('User is not authenticated'))
            }, status=status.HTTP_401_UNAUTHORIZED)
        return super().update(request, *args, **kwargs)

class CurrentEmployeeProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not check_authenticated(request):
            return Response({
                'error': 'ERR_UNAUTHORIZED',
                'message': str(_('User is not authenticated'))
            }, status=status.HTTP_401_UNAUTHORIZED)

        user_id = getattr(request.user, 'id', None)
        username = getattr(request.user, 'username', '')

        employee = None
        if user_id:
            employee = Employee.objects.filter(user_id=user_id).first()
        if not employee and username:
            # Fallback by username if present
            employee = Employee.objects.filter(username=username).first()

        if not employee and user_id:
            # Auto-provision employee profile from validated token data
            full_name = getattr(request.user, 'full_name', '') or username
            parts = full_name.split(' ', 1) if full_name else ['', '']
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ''
            employee = Employee.objects.create(
                user_id=user_id,
                username=username or f"user_{user_id}",
                first_name=first_name,
                last_name=last_name,
                email=getattr(request.user, 'email', ''),
                department=getattr(request.user, 'department', 'Engineering') or 'Engineering',
                job_title=getattr(request.user, 'job_title', 'Team Member') or 'Team Member',
            )

        if not employee:
            return Response({
                'error': 'ERR_EMPLOYEE_NOT_FOUND',
                'message': str(_('Employee profile not found'))
            }, status=status.HTTP_404_NOT_FOUND)

        serializer = EmployeeSerializer(employee)
        return Response(serializer.data)
