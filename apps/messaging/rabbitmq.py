import json
import logging
import threading
import time
from django.conf import settings
from kombu import Connection, Exchange, Queue, Producer
from apps.messaging.websocket_server import broadcast_employee_event

logger = logging.getLogger(__name__)

QUEUE_NAME = 'employee.user.created'

def publish_event(event_type: str, payload: dict):
    """
    Publishes an event to the RabbitMQ topic exchange using Celery's Kombu core.
    Replaces Pika with Celery/Kombu.
    """
    try:
        topic_exchange = Exchange(settings.RABBITMQ_EXCHANGE, type='topic', durable=True)
        with Connection(settings.RABBITMQ_URL, connect_timeout=5.0) as conn:
            with Producer(conn) as producer:
                message = {'event': event_type, 'data': payload}
                producer.publish(
                    message,
                    exchange=topic_exchange,
                    routing_key=event_type,
                    declare=[topic_exchange],
                    serializer='json',
                    delivery_mode=2,
                )
        logger.info(f"[Celery/Kombu] Published {event_type}: {payload.get('id') or payload.get('username')}")
        
        # If this is an employee update/created event, also broadcast to WebSockets
        if event_type in ('employee.created', 'employee.updated'):
            broadcast_employee_event(event_type, payload)

        return True
    except Exception as exc:
        logger.warning(f"[Celery/Kombu] Could not publish {event_type}: {exc}")
        return False


def handle_incoming_event(event_type: str, data: dict):
    """
    Handles events from RabbitMQ or direct dispatch (e.g. user.created).
    Automatically creates the corresponding Employee record in Employee Service.
    """
    valid_events = {'user.created', 'apps.employees.tasks.create_employee_profile'}
    if event_type not in valid_events:
        logger.info(f"[Employee Event Handler] Ignoring event '{event_type}' (not in {valid_events})")
        return None

    try:
        from apps.employees.models import Employee, DepartmentOrProject, EmployeeDepartmentProject
        from django.db import models
        import uuid

        raw_user_id = data.get('user_id') or data.get('outer_id') or data.get('id')
        username = data.get('username')
        if not raw_user_id or not username:
            logger.warning(f"[Employee Event Handler] Missing user_id or username in event payload: {data}")
            return None

        # Ensure user_id is a valid UUID
        try:
            if isinstance(raw_user_id, uuid.UUID):
                user_uuid = raw_user_id
            else:
                user_uuid = uuid.UUID(str(raw_user_id))
        except (ValueError, TypeError):
            user_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, f"user-{raw_user_id}")

        emp = Employee.objects.filter(models.Q(user_id=user_uuid) | models.Q(username=username)).first()
        created = False

        if not emp:
            emp = Employee.objects.create(
                user_id=user_uuid,
                username=username,
                first_name=data.get('first_name', '') or '',
                last_name=data.get('last_name', '') or '',
                email=data.get('email') or None,
                job_title=data.get('job_title', 'Team Member') or 'Team Member',
                phone=data.get('phone') or None,
            )
            created = True
            logger.info(f"[Employee Event Handler] Created employee for user '{username}' (user_id={user_uuid}, emp_id={emp.id})")
        else:
            updated = False
            if not emp.email and data.get('email'):
                emp.email = data.get('email')
                updated = True
            if not emp.phone and data.get('phone'):
                emp.phone = data.get('phone')
                updated = True
            if (emp.job_title == 'Team Member' or not emp.job_title) and data.get('job_title'):
                emp.job_title = data.get('job_title')
                updated = True
            if updated:
                emp.save()
            logger.info(f"[Employee Event Handler] Employee already exists for user '{username}' (emp_id={emp.id})")

        # Department assignment if specified
        dept_name = data.get('department')
        if dept_name and emp:
            try:
                dept = DepartmentOrProject.objects.filter(
                    models.Q(name__iexact=dept_name) | models.Q(code__iexact=dept_name),
                    type=DepartmentOrProject.TYPE_DEPARTMENT
                ).first()
                if dept:
                    EmployeeDepartmentProject.objects.get_or_create(
                        employee=emp,
                        department_project=dept,
                        defaults={'is_current': True}
                    )
                    logger.info(f"[Employee Event Handler] Linked employee {emp.username} to department '{dept.name}'")
            except Exception as d_exc:
                logger.warning(f"[Employee Event Handler] Department assignment note: {d_exc}")

        # Broadcast via WebSocket directly to any connected frontend clients
        emp_event_data = emp.to_event_dict()
        broadcast_employee_event('employee.created' if created else 'employee.updated', emp_event_data)

        return emp
    except Exception as exc:
        logger.error(f"[Employee Event Handler] Failed to process event {event_type}: {exc}", exc_info=True)
        return None


def start_consumer():
    """
    Consumer loop for RabbitMQ using Celery's Kombu core.
    """
    topic_exchange = Exchange(settings.RABBITMQ_EXCHANGE, type='topic', durable=True)
    task_queue = Queue(QUEUE_NAME, exchange=topic_exchange, routing_key='user.#', durable=True)

    while True:
        try:
            with Connection(settings.RABBITMQ_URL, connect_timeout=5.0) as conn:
                logger.info(f"[Celery/Kombu Consumer] Listening on queue: {QUEUE_NAME} (exchange: {settings.RABBITMQ_EXCHANGE})")
                
                def _on_message(body, message):
                    try:
                        if isinstance(body, str):
                            payload = json.loads(body)
                        elif isinstance(body, dict):
                            payload = body
                        else:
                            payload = json.loads(message.body.decode('utf-8'))

                        event_type = payload.get('event') or (message.delivery_info.get('routing_key') if hasattr(message, 'delivery_info') else 'user.created')
                        event_data = payload.get('data') or {}
                        logger.info(f"[Celery/Kombu Consumer] Processing event: {event_type}")
                        handle_incoming_event(event_type, event_data)
                        message.ack()
                    except Exception as e:
                        logger.error(f"[Celery/Kombu Consumer] Error handling message: {e}")
                        try:
                            message.requeue()
                        except Exception:
                            pass

                with conn.Consumer(queues=[task_queue], callbacks=[_on_message], prefetch_count=1):
                    while True:
                        try:
                            conn.drain_events(timeout=2.0)
                        except TimeoutError:
                            pass
                        except Exception as de_err:
                            if "timed out" not in str(de_err).lower():
                                raise

        except Exception as exc:
            logger.warning(f"[Celery/Kombu Consumer] Disconnected or offline ({exc}). Retrying in 10s...")
            time.sleep(10)


_consumer_started = False

def start_consumer_thread():
    global _consumer_started
    if _consumer_started:
        return
    _consumer_started = True
    thread = threading.Thread(target=start_consumer, name="EmployeeKombuConsumer", daemon=True)
    thread.start()
    logger.info("[Celery/Kombu] Started background consumer daemon thread")
