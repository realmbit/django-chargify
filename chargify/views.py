import traceback, hashlib
from functools import wraps

from django.http import HttpResponse, Http404
from django.utils.decorators import method_decorator
from django.views.generic.base import View
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.models import User
from chargify.models import Customer, Subscription
from chargify_settings import CHARGIFY_SHARED_KEY

import logging
logger = logging.getLogger(__name__)

def log_error(func):
    def _func(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
        except:
            logger.error("==== AN EXCEPTION IS RAISED ====")
            logger.error(args)
            logger.error(kwargs)
            logger.error(traceback.print_exc())
            logger.error("==== END OF EXCEPTION ====")
            raise
        else:
            #print "==== HTTP RESPONSE ===="
            #print args, kwargs
            #print result
            #print "==== END HTTP RESPONSE ===="
            return result
    return _func

def check_signature(func):
    """ if the signature does not match pretend that the page does not exist """
    @wraps(func)
    def __signature_checked_func(request, signature):
        # read request.POST first since otherwise it would be empty
        # when request.raw_post_data is read
        data = parse_chargify_webhook(request.POST)
        verified_signature = hashlib.md5(
            CHARGIFY_SHARED_KEY + request.raw_post_data
        ).hexdigest()
        if signature == verified_signature:
            return func(request, data)
        else:
            raise Http404()
    return __signature_checked_func


class ChargifyWebhookBaseView(View):
    # make sure to enable the sending of these events in chargify
    event_handlers = [
        'test',
        'signup_success',
        #'signup_failure',
        #'renewal_success',
        #'renewal_failure',
        #'payment_success',
        #'payment_failure',
        #'billing_date_change',
        'subscription_product_change',
        'subscription_state_change',
        #'expiring_card', 
    ]

    # this method is called when the 'event' attribute is invalid
    def method_not_allowed(self, request, *args, **kwargs):
        raise Http404()

    @csrf_exempt
    @log_error
    @method_decorator(check_signature)
    def dispatch(self, request, data):
        # Try to dispatch to the right method; if a method doesn't exist,
        # defer to the error handler. Also defer to the error handler if the
        # request method isn't on the approved list.

        event = data['event']
        payload = data['payload']
        if event.lower() in self.event_handlers:
            handler = getattr(self, event.lower(), self.method_not_allowed)
        else:
            handler = self.method_not_allowed
        self.request = request
        return handler(request, event, payload)

class ChargifyWebhookView(ChargifyWebhookBaseView):
    def post_signup_success(self, user, subscription):
        pass
    def signup_success(self, request, event, payload):
        # create the customer cache
        customer_id = payload['subscription']['customer']['id']
        customer, loaded = Customer.objects.get_or_load(customer_id)

        # attach the chargify customer to a contrib.auth user
        reference = payload['subscription']['customer']['reference']
        user = User.objects.get(email=reference)
        user.customer_set.add(customer)

        # create the subscription cache
        subscription_id = payload['subscription']['id']
        subscription, loaded = Subscription.objects.get_or_load(subscription_id)

        # call hook
        self.post_signup_success(user, subscription)

        # tell chargify we have processed this webhook correctly
        return HttpResponse(status=200)

    def post_subscription_state_change(self, user, subscription): 
        pass
    def subscription_state_change(self, request, event, payload):
        # update the subscription
        subscription_id = payload['subscription']['id']
        subscription, loaded = Subscription.objects.get_or_load(subscription_id)
        subscription.update(True)

        # call hook
        user = subscription.customer.user
        self.post_subscription_product_change(user, subscription)

        # tell chargify we have processed this webhook correctly
        return HttpResponse(status=200)

    def post_subscription_product_change(self, user, previous_product_handle, subscription): 
        pass
    def subscription_product_change(self, request, event, payload):
        # update the subscription
        subscription_id = payload['subscription']['id']
        subscription, loaded = Subscription.objects.get_or_load(subscription_id)
        subscription.update(True)

        # call hook
        previous_product_handle = payload['previous_product']['handle']
        user = subscription.customer.user
        self.post_subscription_product_change(user, previous_product_handle, subscription)

        # tell chargify we have processed this webhook correctly
        return HttpResponse(status=200)

def parse_chargify_webhook(post_data):
    """ Converts Chargify webhook parameters to a dictionary of nested dictionaries. """
    result = {}
    for k, v in post_data.iteritems():
        keys = [x.strip(']') for x in k.split('[')]
        cur = result
        for key in keys[:-1]:
            cur = cur.setdefault(key, {})
        cur[keys[-1]] = v
    return result

