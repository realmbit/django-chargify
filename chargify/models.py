from chargify.settings import CHARGIFY, CHARGIFY_CC_TYPES
from decimal import Decimal
from django.contrib.auth.models import User
from django.db import models
from django.utils.datetime_safe import new_datetime
import datetime
from pychargify.api import ChargifyNotFound
import logging
import time
import traceback
from django.conf import settings
log = logging.getLogger("chargify")
#logging.basicConfig(level=logging.DEBUG)


def unique_reference(prefix = ''):
    return '%s%i' %(prefix, time.time()*1000)


class ChargifyBaseModel(object):
    """ You can change the gateway/subdomain used by
    changing the gateway on an instantiated object """
    gateway = CHARGIFY

    def _api(self):
        raise NotImplementedError()
    api = property(_api)

    def _from_cents(self, value):
        if value == "":
            return Decimal("0")
        return Decimal(str(float(value)/float(100)))

    def _in_cents(self, value):
        return Decimal(str(float(value)*float(100)))

    def update(self):
        raise NotImplementedError()

    def disable(self, commit=True):
        self.active = False
        if commit:
            self.save()

    def enable(self, commit=True):
        self.active = True
        if commit:
            self.save()


class ChargifyBaseManager(models.Manager):
    def _gateway(self):
        return self.model.gateway
    gateway = property(_gateway)

    def _api(self):
        raise NotImplementedError()
    api = property(_api)

    def _check_api(self):
        if self.api is None:
            raise ValueError('Blank API Not Set on Manager')

    def get_or_load(self, chargify_id):
        self._check_api()
        val = None
        loaded = False
        try:
            val = self.get(chargify_id=chargify_id)
            loaded = False
        except:
            pass
        finally:
            if val is None:
                api = self.api.getById(chargify_id)
                val = self.model().load(api)
                loaded = True
        return val, loaded

    def load_and_update(self, chargify_id):
        self._check_api()
        val, loaded = self.get_or_load(chargify_id)
        if not loaded:
            val.update()
        return val

    def reload_all(self):
        self._check_api()
        items = self.api.getAll()
        for item in items:
            val = self.load_and_update(item.id)
            val.save()


class CustomerManager(ChargifyBaseManager):
    def _api(self):
        return self.gateway.Customer()
    api = property(_api)


class Customer(models.Model, ChargifyBaseModel):
    """ The following are mapped fields:
        first_name = User.first_name (required)
        last_name = User.last_name (required)
        email = User.email (required)
        reference = Customer.id
    """
    chargify_id = models.IntegerField(null=True, blank=False, unique=True)
    user = models.ForeignKey(User)
    _first_name = models.CharField(max_length = 50, null=True, blank=False)
    _last_name = models.CharField(max_length = 50, null = True, blank=False)
    _email = models.EmailField(null=True, blank=False)
    _reference = models.CharField(max_length = 50, null=True, blank=True)
    organization = models.CharField(max_length = 75, null=True, blank=True)
    active = models.BooleanField(default=True)

    # Read only chargify fields
    chargify_created_at = models.DateTimeField(null=True)
    chargify_updated_at = models.DateTimeField(null=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = CustomerManager()

    def full_name(self):
        if not self.last_name:
            return self.first_name
        else:
            return '%s %s' %(self.first_name, self.last_name)

    def __str__(self):
        return self.full_name() + u' - ' + str(self.chargify_id )

    def _get_first_name(self):
        if self._first_name is not None:
            return self._first_name
        return self.user.first_name
    def _set_first_name(self, first_name):
        if self.user.first_name != first_name:
            self._first_name = first_name
    first_name = property(_get_first_name, _set_first_name)

    def _get_last_name(self):
        if self._last_name is not None:
            return self._last_name
        return self.user.last_name
    def _set_last_name(self, last_name):
        if self.user.last_name != last_name:
            self._last_name = last_name
    last_name = property(_get_last_name, _set_last_name)

    def _get_email(self):
        if self._email is not None:
            return self._email
        return self.user.email
    def _set_email(self, email):
        if self.user.email != email:
            self._email = email
    email = property(_get_email, _set_email)

    def _get_reference(self):
        """
        The reference matches the username. NOTE THIS MAY NOT APPLY IN ALL SITUATIONS.
        """
        """ You must save the customer before you can get the reference number"""
        if getattr(settings, 'TESTING', False) and not self._reference:
            self._reference = unique_reference()

        if self._reference:
            return self._reference
        elif self.user:
            return self.user.username
        elif self.id:
            return self.id
        else:
            return ''
    def _set_reference(self, reference):
        self._reference = str(reference)
    reference = property(_get_reference, _set_reference)

    def save(self, save_api = False, **kwargs):
        if save_api:
            if not self.id:
                super(Customer, self).save(**kwargs)
            saved = False
            try:
                saved, customer = self.api.save()
            except ChargifyNotFound as e:
                log.exception(e)
                api = self.api
                api.id = None
                saved, customer = api.save()

            if saved:
                log.debug("Customer Saved")
                return self.load(customer, commit=True) # object save happens after load
            else:
                log.debug("Customer Not Saved")
                log.debug(customer)
        self.user.save()
        return super(Customer, self).save(**kwargs)

    def delete(self, save_api = False, commit = True, *args, **kwargs):
        if save_api:
            self.api.delete()
        if commit:
            super(Customer, self).delete(*args, **kwargs)
        else:
            self.update()

    def load(self, api, commit=True):
        if self.id or self.chargify_id:# api.modified_at > self.chargify_updated_at:
            customer = self
        else:
            customer = Customer()
        customer.chargify_id = int(api.id)
        try:
            if customer.user:
                customer.first_name = api.first_name
                customer.last_name = api.last_name
                customer.email = api.email
            else:
                raise User.DoesNotExist
        except User.DoesNotExist: #@UndefinedVariable
            try:
                user = User.objects.get(models.Q(username=api.reference)
                                        |models.Q(email=api.email)
                                        |models.Q(username=self._gen_username(customer)))
            except:
                user = User(first_name = api.first_name, last_name = api.last_name, email = api.email, username = self._gen_username(customer))
                log.warning("Customer '%s %s' (%s) not matched to user. Given username '%s'" % (api.first_name, api.last_name, api.email, user.username))
                user.save()
            customer.user = user
        customer.organization = api.organization
        customer.chargify_updated_at = api.modified_at
        customer.chargify_created_at = api.created_at
        if commit:
            customer.save()
            log.debug("Saved customer '%s %s'." % (customer.first_name, customer.last_name))
        return customer

    def _gen_username(self, customer):
        """
        Create a unique username for the user
        """
        return("chargify_%s" % (self.id or customer.chargify_id))

    def update(self, commit = True):
        """ Update customer data from chargify """
        api = self.api.getById(self.chargify_id)
        return self.load(api, commit)

    def _api(self, nodename=None):
        """ Load data into chargify api object """
        if nodename == 'customer_attributes':
            customer = self.gateway.CustomerAttributes()
        else:
            customer = self.gateway.Customer()
        customer.id = str(self.chargify_id)
        customer.first_name = str(self.first_name)
        customer.last_name = str(self.last_name)
        customer.email = str(self.email)
        customer.organization = str(self.organization)
        customer.reference = str(self.reference)
        return customer
    api = property(_api)


class ProductFamilyManager(ChargifyBaseManager):
    def _api(self):
        return self.gateway.ProductFamily()
    api = property(_api)

    def get_or_load_component(self, component):
        val = None
        loaded = False
        try:
            val = Component.objects.get(chargify_id=component.id)
            loaded = False
        except:
            pass
        finally:
            if val is None:
                val = Component().load(component)
                loaded = True
        return val, loaded

    def reload_all(self):
        product_families = {}
        for product_family in self.gateway.ProductFamily().getAll():
            try:
                pf, loaded = self.get_or_load(product_family.id)
                if not loaded:
                    pf.update()
                pf.save()
                product_families[product_family.handle] = pf

                for component in product_family.getComponents():
                    c, loaded = self.get_or_load_component(component)
                    c.save()
            except:
                log.error('Failed to load product family: %s' %(product_family))
                log.error(traceback.format_exc())


class ProductFamily(models.Model, ChargifyBaseModel):
    chargify_id = models.IntegerField(null=True, blank=False, unique=True)
    accounting_code = models.CharField(max_length=30, null=True)
    name = models.CharField(max_length=75)
    description = models.TextField(default='')
    handle = models.CharField(max_length=75, default='')
    objects = ProductFamilyManager()

    def __str__(self):
        return self.name

    def _set_handle(self, handle):
        self.handle = str(handle)
    product_handle = property(handle, _set_handle)

    def save(self, save_api = False, **kwargs):
        if save_api:
            try:
                saved, product_family = self.api.save()
                if saved:
                    # object save happens after load
                    return self.load(product_family, commit=True)
            except Exception as e:
                log.exception(e)
        #self.api.save()
        return super(ProductFamily, self).save(**kwargs)

    def load(self, api, commit=True):
        self.chargify_id = int(api.id)
        self.name = api.name
        self.handle = api.handle
        self.description = api.description
        self.accounting_code = api.accounting_code
        if commit:
            self.save()
        return self

    def update(self, commit = True):
        """ Update product family data from chargify """
        api = self.api.getById(self.chargify_id)
        return self.load(api, commit = True)

    def _api(self):
        """ Load data into chargify api object """
        product_family = self.gateway.ProductFamily()
        product_family.id = str(self.chargify_id)
        product_family.name = self.name
        product_family.handle = self.handle
        product_family.description = self.description
        product_family.accounting_code = self.accounting_code
        return product_family
    api = property(_api)


class ComponentManager(ChargifyBaseManager):
    def _api(self):
        return self.gateway.Component()
    api = property(_api)



class Component(models.Model, ChargifyBaseModel):
    KIND_CHOICES = (
         ('metered_component', 'Metered Component'),
         ('quantity_based_component', 'Quantity Based Component'),
         ('on_off_component', 'On/Off Component'),
    )
    SCHEME_CHOICES = (
         ('per_unit', 'Per-Unit'),
         ('volume', 'Volume'),
         ('tiered', 'Tiered'),
         ('stairstep', 'Stairstep'),
    )
    chargify_id = models.IntegerField(null=True, blank=False, unique=True)
    name = models.CharField(max_length=75)
    product_family = models.ForeignKey(ProductFamily, null=True)
    kind = models.CharField(
        max_length=30, choices=KIND_CHOICES, default='metered_component')
    pricing_scheme = models.CharField(
        max_length=10, choices=SCHEME_CHOICES, null=True)
    price_per_unit = models.DecimalField(
        decimal_places = 2, max_digits = 15, default=Decimal('0.00'))
    unit_name = models.CharField(max_length=75)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now=True)
    objects = ComponentManager()

    def __str__(self):
        s = ""
        if self.product_family is not None:
            s+= "(%s) " % self.product_family
        s+= self.name
        return s

    def _price_per_unit_in_cents(self):
        return self._in_cents(self.price_per_unit)
    def _set_price_per_unit_in_cents(self, price):
        self.price_per_unit = self._from_cents(price)
    price_per_unit_in_cents = property(_price_per_unit_in_cents, _set_price_per_unit_in_cents)

    def _product_family_handle(self):
        return self.product_family.handle
    product_family_handle = property(_product_family_handle)

    def save(self, save_api = False, **kwargs):
        if save_api:
            saved, component = self.api.save()
            if saved:
                return self.load(component, commit=True)
        return super(Component, self).save(**kwargs)

    def load(self, api, commit=True):
        self.chargify_id = int(api.id)
        self.name = api.name
        self.kind = api.kind
        self.unit_name = api.unit_name
        self.price_per_unit_in_cents = api.price_per_unit_in_cents
        self.pricing_scheme = api.pricing_scheme

        if api.created_at:
            self.created_at = new_datetime(api.created_at)
        if api.updated_at:
            self.updated_at = new_datetime(api.updated_at)

        try:
            pf = ProductFamily.objects.get(
                    chargify_id=api.product_family_id)
        except:
            family = self.gateway.ProductFamily().getById(api.product_family_id)
            pf = ProductFamily()
            pf.load(family)
            pf.save()
        self.product_family = pf

        if commit:
            self.save()
        return self

    def update(self, commit = True):
        """ Update product family component data from chargify """
        api = self.api.getByIds(
            self.product_family.chargify_id, self.chargify_id)
        return self.load(api, commit = True)

    def _api(self):
        """ Load data into chargify api object """
        component = self.gateway.Component()
        component.id = str(self.chargify_id)
        component.name = self.name
        component.product_family = self.product_family.api
        component.kind = self.kind
        component.price_per_unit_in_cents = self.price_per_unit_in_cents
        component.pricing_scheme = self.pricing_scheme
        component.upated_at = self.updated_at
        component.created_at = self.created_at
        return component
    api = property(_api)

class ProductManager(ChargifyBaseManager):
    def _api(self):
        return self.gateway.Product()
    api = property(_api)

    def reload_all(self):
        products = {}
        for product in self.gateway.Product().getAll():
            try:
                p, loaded = self.get_or_load(product.id)
                if not loaded:
                    p.update()
                p.save()
                products[product.handle] = p
            except:
                log.error('Failed to load product: %s' %(product))
                log.error(traceback.format_exc())


class Product(models.Model, ChargifyBaseModel):
    MONTH = 'month'
    DAY = 'day'
    INTERVAL_TYPES = (
          (MONTH, MONTH.title()),
          (DAY, DAY.title()),
          )
    chargify_id = models.IntegerField(null=True, blank=False, unique=True)
    price = models.DecimalField(decimal_places = 2, max_digits = 15, default=Decimal('0.00'))
    name = models.CharField(max_length=75)
    handle = models.CharField(max_length=75, default='')
    product_family = models.ForeignKey(ProductFamily, null=True)
    accounting_code = models.CharField(max_length=30, null=True)
    interval_unit = models.CharField(max_length=10, choices = INTERVAL_TYPES, default=MONTH)
    interval = models.IntegerField(default=1)
    active = models.BooleanField(default=True)
    objects = ProductManager()

    def __str__(self):
        s = ""
        if self.product_family is not None:
            s+= "(%s) " % self.product_family
        s+= self.name
        return s

    def _price_in_cents(self):
        return self._in_cents(self.price)
    def _set_price_in_cents(self, price):
        self.price = self._from_cents(price)
    price_in_cents = property(_price_in_cents, _set_price_in_cents)

    def _set_handle(self, handle):
        self.handle = str(handle)
    product_handle = property(handle, _set_handle)

    def _product_family_handle(self):
        return self.product_family.handle
    product_family_handle = property(_product_family_handle)

    def save(self, save_api = False, **kwargs):
        if save_api:
            if self.product_family and self.product_family.chargify_id is None:
                log.debug('Saving Product Family')
                pf = self.product_family.save(save_api=True)
                log.debug("Returned Product Family: %s" %(pf))
                log.debug('Product Family ID: %s' %(pf.chargify_id))
                self.product_family = pf
            saved, product = self.api.save()
            if saved:
                return self.load(product, commit=True) # object save happens after load
        return super(Product, self).save(**kwargs)

    def load(self, api, commit=True):
        self.chargify_id = int(api.id)
        self.price_in_cents = api.price_in_cents
        self.name = api.name
        self.handle = api.handle
        self.accounting_code = api.accounting_code
        self.interval_unit = api.interval_unit
        self.interval = api.interval

        if api.product_family:
            try:
                pf = ProductFamily.objects.get(
                        chargify_id=api.product_family.id)
            except:
                pf = ProductFamily()
                pf.load(api.product_family)
                pf.save()
            self.product_family = pf

        if commit:
            self.save()
        return self

    def update(self, commit = True):
        """ Update customer data from chargify """
        api = self.api.getById(self.chargify_id)
        return self.load(api, commit = True)

    def _api(self):
        """ Load data into chargify api object """
        product = self.gateway.Product()
        product.id = str(self.chargify_id)
        product.price_in_cents = self.price_in_cents
        product.name = self.name
        product.handle = self.handle
        product.product_family = self.product_family.api
        product.product_family_handle = self.product_family_handle
        product.accounting_code = self.accounting_code
        product.interval_unit = self.interval_unit
        product.interval = self.interval
        return product
    api = property(_api)


class CreditCardManager(ChargifyBaseManager):
    def _api(self):
        return self.gateway.CreditCard()
    api = property(_api)


class CreditCard(models.Model, ChargifyBaseModel):
    """ This data should NEVER be saved in the database """
    CC_TYPES = CHARGIFY_CC_TYPES
    _full_number = ''
    ccv = ''

    first_name = models.CharField(max_length = 50, null=True, blank=False)
    last_name = models.CharField(max_length = 50, null=True, blank=False)
    masked_card_number = models.CharField(max_length=25, null=True)
    expiration_month = models.IntegerField(null=True, blank=True)
    expiration_year = models.IntegerField(null=True, blank=True)
    credit_type = models.CharField(max_length=25, null=True, blank=False, choices=CC_TYPES)
    billing_address = models.CharField(max_length=75, null=True, blank=False, default='')
    billing_city = models.CharField(max_length=75, null=True, blank=False, default='')
    billing_state = models.CharField(max_length=2, null=True, blank=False, default='')
    billing_zip = models.CharField(max_length=15, null=True, blank=False, default='')
    billing_country = models.CharField(max_length=75, null=True, blank=True, default='United States')
    active = models.BooleanField(default=True)
    objects = CreditCardManager()

    def __str__(self):
        s = u''
        if self.first_name:
            s += unicode(self.first_name)
        if self.last_name:
            if s:
                s += u' '
            s += unicode(self.last_name)
        if self.masked_card_number:
            if s:
                s += u'-'
            s += unicode(self.masked_card_number)
        return s

    # you have to set the customer if there is no related subscription yet
    _customer = None
    def _get_customer(self):
        if self._customer:
            return self._customer
        try:
            return self.subscription.all().order_by('-updated_at')[0].customer
        except IndexError:
            return None
    def _set_customer(self, customer):
        self._customer = customer
    customer = property(_get_customer, _set_customer)

    def _get_full_number(self):
        return self._full_number
    def _set_full_number(self, full_number):
        self._full_number = full_number

        if len(full_number) > 4:
            self.masked_card_number = u'XXXX-XXXX-XXXX-' + full_number[-4:]
        else: #not a real CC number, probably a testing number
            self.masked_card_number = u'XXXX-XXXX-XXXX-1111'
    full_number = property(_get_full_number, _set_full_number)

    def save(self,  save_api = False, *args, **kwargs):
        if save_api:
            self.api.save(self.subscription)
        return super(CreditCard, self).save(*args, **kwargs)

    def delete(self, save_api = False, *args, **kwargs):
        if save_api:
            self.api.delete(self.subscription)
        return super(CreditCard, self).delete(*args, **kwargs)

    def load(self, api, commit=True):
        if api is None:
            return self
        self.masked_card_number = api.masked_card_number
        self.expiration_month = api.expiration_month
        self.expiration_year = api.expiration_year
        self.credit_type = api.type
        if commit:
            self.save(save_api = False)
        return self

    def update(self, commit=True):
        """ Update Credit Card data from chargify """
        if self.subscription:
            return self.subscription.update()
        else:
            return self

    def _api(self):
        """ Load data into chargify api object """
        cc = self.gateway.CreditCard()
        cc.first_name = self.first_name
        cc.last_name = self.last_name
        cc.full_number = self._full_number
        cc.expiration_month = self.expiration_month
        cc.expiration_year = self.expiration_year
        cc.ccv = self.ccv
        cc.billing_address = self.billing_address
        cc.billing_city = self.billing_city
        cc.billing_state = self.billing_state
        cc.billing_zip = self.billing_zip
        cc.billing_country = self.billing_country
        return cc
    api = property(_api)


class SubscriptionManager(ChargifyBaseManager):
    def _api(self):
        return self.gateway.Subscription()
    api = property(_api)

    def get_or_load_component(self, component):
        val = None
        loaded = False
        try:
            val = SubscriptionComponent.objects.get(
                component__id=component.id,
                subscription__id=subscription.id
            )
            loaded = False
        except:
            pass
        finally:
            if val is None:
                val = SubscriptionComponent().load(component)
                loaded = True
        return val, loaded

    def update_list(self, lst):
        for id in lst:
            sub= self.load_and_update(id)
            sub.save()

    def reload_all(self):
        """ You should only run these when you first install the product!
        VERY EXPENSIVE!!! """
        ProductFamily.objects.reload_all()
        Product.objects.reload_all()

        for customer in Customer.objects.filter(active=True):
            subscriptions = self.api.getByCustomerId(str(customer.chargify_id))
            if not subscriptions:
                continue
            for subscription in subscriptions:
                try:
                    sub = self.get(chargify_id = subscription.id)
                except:
                    sub = self.model()
                    sub.load(subscription)
                sub.save()

                #for component in subscription.getComponents():
                #    c, loaded = self.get_or_load_component(component)
                #    c.save()


class Subscription(models.Model, ChargifyBaseModel):
    TRIALING = 'trialing'
    ASSESSING = 'assessing'
    ACTIVE = 'active'
    SOFT_FAILURE = 'soft_failure'
    PAST_DUE = 'past_due'
    SUSPENDED = 'suspended'
    CANCELLED = 'canceled'
    EXPIRED = 'expired'
    STATE_CHOICES = (
         (TRIALING, u'Trialing'),
         (ASSESSING, u'Assessing'),
         (ACTIVE, u'Active'),
         (SOFT_FAILURE, u'Soft Failure'),
         (PAST_DUE, u'Past Due'),
         (SUSPENDED, u'Suspended'),
         (CANCELLED, u'Cancelled'),
         (EXPIRED, u'Expired'),
         )
    chargify_id = models.IntegerField(null=True, blank=True, unique=True)
    state = models.CharField(max_length=15, null=True, blank=True, default='', choices=STATE_CHOICES)
    balance = models.DecimalField(decimal_places = 2, max_digits = 15, default=Decimal('0.00'))
    current_period_started_at = models.DateTimeField(null=True, blank=True)
    current_period_ends_at = models.DateTimeField(null=True, blank=True)
    trial_started_at = models.DateTimeField(null=True, blank=True)
    trial_ended_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    next_assessment_at = models.DateTimeField(null=True, blank=True)
    next_billing_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    last_deactivation_at = models.DateTimeField(null=True, blank=True)
    last_activation_at = models.DateTimeField(null=True, blank=True)
    customer = models.ForeignKey(Customer, null=True)
    product = models.ForeignKey(Product, null=True)
    credit_card = models.OneToOneField(CreditCard, related_name='subscription', null=True, blank=True)
    active = models.BooleanField(default=True)
    objects = SubscriptionManager()

    def __str__(self):
        s = unicode(self.get_state_display())
        if self.product:
            s += u' ' + self.product.name
        if self.chargify_id:
            s += ' - ' + unicode(self.chargify_id)

        return s

    def _balance_in_cents(self):
        return self._in_cents(self.balance)
    def _set_balance_in_cents(self, value):
        self.balance = self._from_cents(value)
    balance_in_cents = property(_balance_in_cents, _set_balance_in_cents)

    def _customer_reference(self):
        return self.customer.reference
    customer_reference = property(_customer_reference)

    def _product_handle(self):
        return self.product.handle
    product_handle = property(_product_handle)

    def save(self, save_api = False, *args, **kwargs):
        if save_api:
            if self.customer.chargify_id is None:
                log.debug('Saving Customer')
                self.customer.save(save_api = True)
                customer = self.customer
                log.debug("Returned Customer: %s" %(customer))
                log.debug('Customer ID: %s' %(customer.chargify_id))
                self.customer = customer
            if self.product and self.product.chargify_id is None:
                log.debug('Saving Product')
                #this won't actually work
                product = self.product.save(save_api = True)
                log.debug("Returned Product : %s" %(product))
                self.product = product
            api = self.api
            log.debug('Saving API')
            saved, subscription = api.save()
            if saved:
                return self.load(subscription, commit=True) # object save happens after load
        return super(Subscription, self).save(*args, **kwargs)


    def reactivate(self):
        self.last_activation_at = datetime.datetime.now()
        self.api.reactivate()
        self.update()

    def unsubscribe(self, message="", *args, **kwargs):
        self.api.unsubscribe(message=message)
        self.last_deactivation_at = datetime.datetime.now()
        self.update(commit=True)

    def delete(self, save_api = False, commit = True, message = None, *args, **kwargs):
        if save_api:
            self.api.delete(message=message)
        self.last_deactivation_at = datetime.datetime.now()
        if commit:
            super(Subscription, self).delete(*args, **kwargs)
        else:
            self.update()

    def load(self, api, commit=True):
        self.chargify_id = int(api.id)
        self.state = api.state
        self.balance_in_cents = api.balance_in_cents
        if api.current_period_started_at:
            self.current_period_started_at = new_datetime(api.current_period_started_at)
        else:
            self.current_period_started_at = None
        if api.current_period_ends_at:
            self.current_period_ends_at = new_datetime(api.current_period_ends_at)
        else:
            self.current_period_ends_at = None
        if api.trial_started_at:
            self.trial_started_at = new_datetime(api.trial_started_at)
        else:
            self.trial_started_at = None
        if api.trial_ended_at:
            self.trial_ended_at = new_datetime(api.trial_ended_at)
        else:
            self.trial_ended_at = None
        if api.activated_at:
            self.activated_at = new_datetime(api.activated_at)
        else:
            self.activated_at = None
        if api.expires_at:
            self.expires_at = new_datetime(api.expires_at)
        else:
            self.expires_at = None
        if api.next_assessment_at:
            self.next_assessment_at = new_datetime(api.next_assessment_at)
        else:
            self.next_assessment_at = None
        if api.created_at:
            self.created_at = new_datetime(api.created_at)
        if api.updated_at:
            self.updated_at = new_datetime(api.updated_at)
        try:
            c = Customer.objects.get(chargify_id = api.customer.id)
        except:
            c = Customer()
            c.load(api.customer)
        self.customer = c

        try:
            p = Product.objects.get(chargify_id = api.product.id)
        except:
            p = Product()
            p.load(api.product)
            p.save()
        self.product = p

        if self.credit_card:
            credit_card = self.credit_card
        else:
            credit_card = CreditCard()
            credit_card.load(api.credit_card)

        if commit:
            self.save()

        for subscomp in api.getComponents():
            # FIXME: remove the subscomp check when no longer needed
            if subscomp.enabled:
                try:
                    sc = SubscriptionComponent.objects.get(
                        component__chargify_id = subscomp.component_id,
                        subscription__chargify_id = subscomp.subscription_id
                    )
                except:
                    sc = SubscriptionComponent()
                    sc.load(subscomp)
                    sc.save()
        return self

    def update(self, commit=True):
        """ Update Subscription data from chargify """
        subscription = self.gateway.Subscription().getBySubscriptionId(self.chargify_id)

        if subscription:
            return self.load(subscription, commit)
        else:
            return None

    def charge(self, amount, memo):
        """ Create a one-time charge """
        return self.api.charge(amount, memo)

    def upgrade(self, product):
        """ Upgrade / Downgrade products """
        return self.update(self.api.upgrade(product.handle))

    def load_api(self):
        """ Load data into chargify api object """
        subscription = self.gateway.Subscription()
        if self.chargify_id:
            subscription.id = str(self.chargify_id)
        #subscription.product = self.product.api
        subscription.product_handle = self.product_handle
        subscription.balance_in_cents = self.balance_in_cents
        if self.next_assessment_at:
            subscription.next_assessment_at = new_datetime(self.next_assessment_at)
        if self.next_billing_at: #not passed back from chargify under this node, check for set
            subscription.next_billing_at = new_datetime(self.next_billing_at)
        if self.customer.chargify_id is None:
            subscription.customer = self.customer._api(nodename='customer_attributes')
        else:
            #subscription.customer = self.customer.api
            subscription.customer_reference = self.customer_reference
        if self.credit_card:
            subscription.credit_card = self.credit_card.api
        components = self.subscriptioncomponent_set.all()
        if len(components) > 0:
            subscription.components = map(lambda c: c.api, components)
        return subscription

    def _api(self):
        return self.load_api()
    api = property(_api)


class SubscriptionComponentManager(ChargifyBaseManager):
    def _api(self):
        return self.gateway.SubscriptionComponent()
    api = property(_api)


class SubscriptionComponent(models.Model, ChargifyBaseModel):
    component = models.ForeignKey(Component, null=True)
    subscription = models.ForeignKey(Subscription, null=True)
    unit_balance = models.DecimalField(
        decimal_places = 2, max_digits = 15, default=Decimal('0.00'))
    allocated_quantity = models.DecimalField(
        decimal_places = 2, max_digits = 15, default=Decimal('0.00'))
    enabled = models.BooleanField(default=False)
    objects = SubscriptionComponentManager()

    @property
    def name(self):
        return self.component.name

    @property
    def kind(self):
        return self.component.kind

    @property
    def unit_name(self):
        return self.component.unit_name

    @property
    def pricing_scheme(self):
        return self.component.pricing_scheme

    def __str__(self):
        return '%s - %s' % (self.subscription, self.component)

    def save(self, save_api=False, **kwargs):
        if save_api:
            try:
                saved, sc = self.api.save()
                if saved:
                    return self.load(sc, commit=True)
            except Exception as e:
                log.exception(e)
        return super(SubscriptionComponent, self).save(**kwargs)

    def load(self, api, commit=True):
        self.unit_balance = api.unit_balance
        self.allocated_quantity = api.allocated_quantity
        self.enabled = api.enabled

        try:
            s = Subscription.objects.get(chargify_id=api.subscription_id)
        except:
            aux = self.gateway.Subscription().getById(api.subscription_id)
            s = Subscription()
            s.load(aux)
            s.save()
        self.subscription = s

        try:
            c = Component.objects.get(chargify_id=api.component_id)
        except:
            aux = self.gateway.Component().getById(api.component_id)
            c = Component()
            c.load(aux)
            c.save()
        self.component = c

        if commit:
            self.save()
        return self

    def update(self, commit = True):
        """ Update subscription component data from chargify """
        api = self.api.getByCompoundKey(
            self.subscription.id, self.component.id)
        return self.load(api, commit = True)

    def _api(self):
        """ Load data into chargify api object """
        component = self.gateway.SubscriptionComponent()
        component.component_id = self.component.chargify_id
        if self.subscription:
            component.subscription_id = self.subscription.chargify_id
        component.name = self.name
        component.kind = self.kind
        component.unit_name = self.unit_name
        component.unit_balance = self.unit_balance
        component.allocated_quantity = self.allocated_quantity
        component.pricing_scheme = self.pricing_scheme
        component.enabled = self.enabled
        return component
    api = property(_api)
