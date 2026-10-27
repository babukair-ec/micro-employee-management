from django.core.management.base import BaseCommand
from apps.messaging.rabbitmq import start_consumer

class Command(BaseCommand):
    help = 'Starts the RabbitMQ consumer for employee-service'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting RabbitMQ event consumer for employee-service...'))
        start_consumer()
