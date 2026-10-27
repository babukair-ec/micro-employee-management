import logging
from celery import shared_task
from apps.messaging.rabbitmq import handle_incoming_event
from apps.messaging.websocket_server import broadcast_employee_event

logger = logging.getLogger(__name__)

@shared_task(name='apps.employees.tasks.create_employee_profile')
def create_employee_profile(data):
    """
    Celery task to asynchronously process user registration and create an Employee profile.
    Automatically triggers WebSocket notification to frontend once employee is created.
    """
    logger.info(f"[Celery Task] Processing employee profile creation for user: {data.get('username')}")
    emp = handle_incoming_event('user.created', data)
    if emp:
        event_dict = emp.to_event_dict()
        # Broadcast via WebSocket directly to any connected frontend clients
        broadcast_employee_event('employee.created', event_dict)
        logger.info(f"[Celery Task] Successfully created employee and broadcast event: {emp.username}")
        return event_dict
    else:
        logger.warning(f"[Celery Task] Failed to create employee for user payload: {data}")
        return None
