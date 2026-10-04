from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _
from apps.messaging.rabbitmq import publish_event

class Employee(models.Model):
    user_id = models.IntegerField(unique=True, verbose_name=_("User ID"))
    username = models.CharField(max_length=150, verbose_name=_("Username"))
    first_name = models.CharField(max_length=150, blank=True, default='', verbose_name=_("First Name"))
    last_name = models.CharField(max_length=150, blank=True, default='', verbose_name=_("Last Name"))
    email = models.EmailField(blank=True, default='', verbose_name=_("Email"))
    department = models.CharField(max_length=100, default='Engineering', verbose_name=_("Department"))
    job_title = models.CharField(max_length=100, default='Team Member', verbose_name=_("Job Title"))
    phone = models.CharField(max_length=50, blank=True, default='', verbose_name=_("Phone"))
    is_active = models.BooleanField(default=True, verbose_name=_("Is Active"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))

    class Meta:
        verbose_name = _("Employee")
        verbose_name_plural = _("Employees")

    @property
    def full_name(self):
        name = f"{self.first_name} {self.last_name}".strip()
        return name if name else self.username

    def __str__(self):
        return self.full_name

    def to_event_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'username': self.username,
            'full_name': self.full_name,
            'email': self.email,
            'department': self.department,
            'job_title': self.job_title,
            'phone': self.phone,
            'is_active': self.is_active,
        }

@receiver(post_save, sender=Employee)
def employee_post_save(sender, instance, created, **kwargs):
    event_name = 'employee.created' if created else 'employee.updated'
    publish_event(event_name, instance.to_event_dict())
