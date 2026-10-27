import os
import sys
from django.apps import AppConfig

class EmployeesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.employees'

    def ready(self):
        # Prevent running consumer during migrations or tests or manage.py commands
        cmd = sys.argv[1] if len(sys.argv) > 1 else ''
        if cmd in ('makemigrations', 'migrate', 'collectstatic', 'test', 'seed_employees'):
            return

        # Ensure consumer thread and WebSocket server are started in the worker process
        if os.environ.get('RUN_MAIN') == 'true' or '--noreload' in sys.argv or 'runserver' not in sys.argv:
            from apps.messaging.rabbitmq import start_consumer_thread
            from apps.messaging.websocket_server import start_websocket_server_thread
            start_consumer_thread()
            start_websocket_server_thread()

