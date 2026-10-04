import json
import logging
import pika
from django.conf import settings

logger = logging.getLogger(__name__)

def publish_event(event_type: str, payload: dict):
    try:
        parameters = pika.URLParameters(settings.RABBITMQ_URL)
        parameters.socket_timeout = 2.0
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        channel.exchange_declare(exchange=settings.RABBITMQ_EXCHANGE, exchange_type='topic', durable=True)
        message = {'event': event_type, 'data': payload}
        channel.basic_publish(
            exchange=settings.RABBITMQ_EXCHANGE,
            routing_key=event_type,
            body=json.dumps(message),
            properties=pika.BasicProperties(content_type='application/json', delivery_mode=2)
        )
        logger.info(f"[RabbitMQ] Published {event_type}: {payload.get('id')}")
        connection.close()
        return True
    except Exception as exc:
        logger.warning(f"[RabbitMQ] Could not publish {event_type}: {exc}")
        return False
