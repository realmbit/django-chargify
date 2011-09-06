from django.core.management.base import BaseCommand

from chargify.models import Subscription, Customer

class Command(BaseCommand):
    args = ''
    help = 'Reload all the customers and subscriptions from Chargify. IT MAY TAKE AWHILE TO RUN.'

    def handle(self, *args, **options):
        Customer.objects.reload_all()
        Subscription.objects.reload_all()
