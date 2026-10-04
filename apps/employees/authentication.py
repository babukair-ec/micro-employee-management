import jwt
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from rest_framework import authentication, exceptions

class StatelessUser:
    """
    Stateless authenticated user representing the user claims from the validated JWT token.
    Allows microservice authentication without querying a local Django auth_user database table.
    """
    is_authenticated = True
    is_active = True
    is_anonymous = False
    is_staff = False
    is_superuser = False

    def __init__(self, payload: dict):
        self.payload = payload
        raw_id = payload.get('user_id') or payload.get('id') or payload.get('employee_id')
        try:
            self.id = int(raw_id) if raw_id is not None else None
        except (ValueError, TypeError):
            self.id = raw_id

        self.pk = self.id
        self.user_id = self.id
        self.username = payload.get('username', '')
        self.email = payload.get('email', '')
        self.full_name = payload.get('full_name', '')
        self.department = payload.get('department', '')
        self.job_title = payload.get('job_title', '')

    def __str__(self):
        return f"StatelessUser({self.username}, id={self.id})"

    def get_username(self):
        return self.username

    def has_perm(self, perm, obj=None):
        return False

    def has_perms(self, perm_list, obj=None):
        return False

    def has_module_perms(self, module):
        return False

    def __getattr__(self, name):
        return self.payload.get(name, None)


class StatelessJWTAuthentication(authentication.BaseAuthentication):
    """
    Stateless JWT Authentication for the Employee Microservice.
    Validates the Bearer token in the Authorization header using the shared JWT_SECRET_KEY,
    and returns a StatelessUser instance with is_authenticated=True.
    """

    def authenticate(self, request):
        auth_header = request.headers.get('Authorization') or request.META.get('HTTP_AUTHORIZATION')
        if not auth_header:
            return None

        parts = auth_header.split()
        if len(parts) == 0:
            return None

        if parts[0].lower() != 'bearer':
            raise exceptions.AuthenticationFailed(_('Authorization header must start with Bearer'))

        if len(parts) == 1:
            raise exceptions.AuthenticationFailed(_('Token not provided'))
        elif len(parts) > 2:
            raise exceptions.AuthenticationFailed(_('Authorization header contains extra spaces or invalid characters'))

        token = parts[1]

        secret_key = getattr(settings, 'JWT_SECRET_KEY', getattr(settings, 'SECRET_KEY', ''))
        algorithm = getattr(settings, 'SIMPLE_JWT', {}).get('ALGORITHM', 'HS256')

        try:
            payload = jwt.decode(
                token,
                secret_key,
                algorithms=[algorithm],
                options={"verify_signature": True, "verify_exp": True}
            )
        except jwt.ExpiredSignatureError:
            raise exceptions.AuthenticationFailed(_('Token has expired'))
        except jwt.InvalidTokenError as exc:
            raise exceptions.AuthenticationFailed(_(f'Invalid token: {str(exc)}'))

        user_id = payload.get('user_id') or payload.get('id')
        if not user_id:
            raise exceptions.AuthenticationFailed(_('Token missing user identification'))

        user = StatelessUser(payload)
        return (user, token)
