# -*- coding: utf-8 -*-
'''
This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA


Created on Nov 20, 2009
Author: Paul Trippett (paul@pyhub.com)
'''

import httplib
import base64
import time
import datetime
import iso8601
import inspect
import logging

from itertools import chain
from xml.dom import minidom

log = logging.getLogger("pychargify")


try:
    import json
except Exception, e:
    try:
        import simplejson as json
    except Exception, e:
        try:
            # For AppEngine users
            import django.utils.simplejson as json
        except Exception, e:
            log.error("No Json library found... Exiting.")
            exit()


class ChargifyError(Exception):
    """
    A Chargify Releated error
    @license    GNU General Public License
    """
    pass


class ChargifyUnAuthorized(ChargifyError):
    """
    Returned when API authentication has failed.
    @license    GNU General Public License
    """
    pass


class ChargifyForbidden(ChargifyError):
    """
    Returned by valid endpoints in our application that have not been
    enabled for API use.
    @license    GNU General Public License
    """
    pass


class ChargifyNotFound(ChargifyError):
    """
    The requested resource was not found.
    @license    GNU General Public License
    """
    pass


class ChargifyUnProcessableEntity(ChargifyError):
    """
    Sent in response to a POST (create) or PUT (update) request
    that is invalid.
    @license    GNU General Public License
    """
    pass


class ChargifyServerError(ChargifyError):
    """
    Signals some other error
    @license    GNU General Public License
    """
    pass


class ChargifyBase(object):
    """
    The ChargifyBase class provides a common base for all classes
    in this module
    @license    GNU General Public License
    """

    class Meta:
        listing = None
        paged = False

    __ignore__ = ['api_key', 'sub_domain', 'base_host', 'request_host',
        'id', '__xmlnodename__', 'Meta']

    api_key = ''
    sub_domain = ''
    base_host = '.chargify.com'
    request_host = ''

    def __init__(self, apikey, subdomain):
        """
        Initialize the Class with the API Key and SubDomain for Requests
        to the Chargify API
        """
        self.api_key = apikey
        self.sub_domain = subdomain
        self.request_host = self.sub_domain + self.base_host

    def __get_xml_value(self, nodelist):
        """
        Get the Text Value from an XML Node
        """
        rc = ""
        for node in nodelist:
            if node.nodeType == node.TEXT_NODE:
                rc = rc + node.data
        return rc

    def __get_object_from_node(self, node, obj_type=''):
        """
        Copy values from a node into a new Object
        """
        if obj_type == '':
            constructor = globals()[self.__name__]
        else:
            constructor = globals()[obj_type]
        obj = constructor(self.api_key, self.sub_domain)

        for childnodes in node.childNodes:
            if childnodes.nodeType == 1 and not childnodes.nodeName == '':
                if childnodes.nodeName in self.__attribute_types__:

                    obj.__setattr__(childnodes.nodeName,
                        self._applyS(childnodes.toxml(encoding='utf-8'),
                        self.__attribute_types__[childnodes.nodeName],
                            childnodes.nodeName))
                else:
                    node_value = self.__get_xml_value(childnodes.childNodes)
                    if "type" in  childnodes.attributes.keys():
                        node_type = childnodes.attributes["type"]
                        if node_value:
                            if node_type.nodeValue == 'datetime':
                                node_value = datetime.datetime.fromtimestamp(
                                    iso8601.parse(node_value))
                    obj.__setattr__(childnodes.nodeName, node_value)
        return obj

    def fix_xml_encoding(self, xml):
        """
        Chargify encodes non-ascii characters in CP1252.
        Decodes and re-encodes with xml characters.
        Strips out whitespace "text nodes".
        """
        return unicode(''.join([i.strip() for i in xml.split('\n')])
                .encode('utf-8', 'xmlcharrefreplace'), 'utf-8')

    def _applyS(self, xml, obj_type, node_name):
        """
        Apply the values of the passed xml data to the a class
        """
        dom = minidom.parseString(xml)
        nodes = dom.getElementsByTagName(node_name)
        if nodes.length == 1:
            return self.__get_object_from_node(nodes[0], obj_type)

    def _applyA(self, xml, obj_type, node_name):
        """
        Apply the values of the passed data to a new class of the current type
        """
        dom = minidom.parseString(xml)
        nodes = dom.getElementsByTagName(node_name)
        objs = []
        for node in nodes:
            objs.append(self.__get_object_from_node(node, obj_type))
        return objs

    def _toxml(self, dom):
        """
        Return a XML Representation of the object
        """
        element = minidom.Element(self.__xmlnodename__)
        for property, value in self.__dict__.iteritems():
            if not property in self.__ignore__ and not inspect.isfunction(value):
                if property in self.__attribute_types__:
                    if type(value) == list:
                        node = minidom.Element(property)
                        node.setAttribute('type', 'array')
                        for v in value:
                            child = v._toxml(dom)
                            if child is not None:
                                node.appendChild(child)
                        element.appendChild(node)
                    else:
                        element.appendChild(value._toxml(dom))
                else:
                    node = minidom.Element(property)
                    node_txt = dom.createTextNode(str(value).encode('ascii', 'xmlcharrefreplace'))
                    node.appendChild(node_txt)
                    element.appendChild(node)
        return element

    def _get(self, url):
        """
        Handle HTTP GETs to the API
        """
        return self._request('GET', url)

    def _post(self, url, data):
        """
        Handle HTTP POST's to the API
        """
        return self._request('POST', url, data)

    def _put(self, url, data):
        """
        Handle HTTP PUT's to the API
        """
        return self._request('PUT', url, data)

    def _delete(self, url, data):
        """
        Handle HTTP DELETE's to the API
        """
        return self._request('DELETE', url, data)

    def _request(self, method, url, data=None):
        """
        Handled the request and sends it to the server
        """
        http = httplib.HTTPSConnection(self.request_host)

        http.putrequest(method, url)
        http.putheader("Authorization", "Basic %s" % self._get_auth_string())
        http.putheader("User-Agent", "pychargify")
        http.putheader("Host", self.request_host)
        http.putheader("Accept", "application/xml")

        if data:
            http.putheader("Content-Length", str(len(data)))

        http.putheader("Content-Type", 'text/xml; charset="UTF-8"')
        http.endheaders()

        log.debug('url: %s' % url)
        log.debug('sending: %s' % data)

        if data:
            http.send(data)

        response = http.getresponse()
        r = response.read()

        log.debug('got: %s' % r)

        # Unauthorized Error
        if response.status == 401:
            raise ChargifyUnAuthorized()

        # Forbidden Error
        elif response.status == 403:
            raise ChargifyForbidden()

        # Not Found Error
        elif response.status == 404:
            raise ChargifyNotFound()

        # Unprocessable Entity Error
        elif response.status == 422:
            raise ChargifyUnProcessableEntity()

        # Generic Server Errors
        elif response.status in [405, 500]:
            log.debug('response status: %s' % response.status)
            log.debug('response reason: %s' % response.reason)
            raise ChargifyServerError()

        return self.fix_xml_encoding(r)

    def _save(self, url, node_name):
        """
        Save the object using the passed URL as the API end point
        """
        dom = minidom.Document()
        dom.appendChild(self._toxml(dom))

        request_made = {
            'day': datetime.datetime.today().day,
            'month': datetime.datetime.today().month,
            'year': datetime.datetime.today().year
        }
        if self.id not in [None, 'None']:
            id = str(self.id)
            obj = self._applyS(self._put('/' + url + '/' + id + '.xml', dom.toxml(encoding="utf-8")), self.__name__, node_name)
            if obj:
                if type(obj.updated_at) == datetime.datetime:
                    if (obj.updated_at.day == request_made['day']) and \
                        (obj.updated_at.month == request_made['month']) and \
                        (obj.updated_at.year == request_made['year']):
                        self.saved = True
                        return (True, obj)
            return (False, obj)
        else:
            obj = self._applyS(self._post('/' + url + '.xml',
                dom.toxml(encoding="utf-8")), self.__name__, node_name)
            if obj:
                if type(obj.updated_at) == datetime.datetime:
                    if (obj.updated_at.day == request_made['day']) and \
                        (obj.updated_at.month == request_made['month']) and \
                        (obj.updated_at.year == request_made['year']):
                        return (True, obj)
            return (False, obj)

    def _get_auth_string(self):
        return base64.encodestring('%s:%s' % (self.api_key, 'x'))[:-1]

    def getAll(self):
        if self.Meta.listing:
            rv = []
            do_paging = getattr(self.Meta, "paged", False)
            page = 1
            while True:
                url = '/%s.xml' % self.Meta.listing
                if do_paging:
                    url += '?page=%s' % page
                    page += 1
                vals = self._applyA(self._get(url), self.__name__, self.__xmlnodename__)
                rv.extend(vals)
                if not do_paging or not vals: break
            return rv
        raise NotImplementedError('Subclass is missing Meta class attribute listing')

    def getById(self, id):
        if self.Meta.listing:
            return self._applyS(self._get('/%s/%s.xml' % (self.Meta.listing, str(id))),
                self.__name__, self.__xmlnodename__)
        raise NotImplementedError('Subclass is missing Meta class attribute listing')

    def __get_by_attribute__(self, key, value):
        if self.Meta.listing:
            return self._applyS(self._get('/%s/lookup.xml?%s=%s' %(self.Meta.listing,
                str(key), str(value))), self.__name__, self.__xmlnodename__)
        raise NotImplementedError('Subclass is missing Meta class attribute listing')

    def save(self):
        if self.Meta.listing:
            return self._save(self.Meta.listing, self.__xmlnodename__)
        raise NotImplementedError('Subclass is missing Meta class attribute listing')


class CompoundKeyMixin:
    def getByCompoundKey(self, parent_id, sub_id):
        if 'compound_key' in self.Meta.__dict__.keys():
            _cb, _a = (self._applyA, ('/%s' % self.Meta.compound_key[2])) \
                if len(self.Meta.compound_key) == 3 else (self._applyS, '')

            return _cb(self._get('/%s.xml' % ('/'.join(['%s/%s' % i
                for i in zip(self.Meta.compound_key[:2],
                (str(parent_id), str(sub_id)))]) + _a)),
                    self.__name__, self.__xmlnodename__)

        raise NotImplementedError('Subclass is missing Meta class attribute compound key')


class ChargifyCustomer(ChargifyBase):
    """
    Represents Chargify Customers
    @license    GNU General Public License
    """

    class Meta:
        listing = 'customers'

    __name__ = 'ChargifyCustomer'
    __attribute_types__ = {}
    __xmlnodename__ = 'customer'

    id = None
    first_name = ''
    last_name = ''
    email = ''
    organization = ''
    reference = ''
    created_at = None
    modified_at = None

    def __init__(self, apikey, subdomain):
        super(ChargifyCustomer, self).__init__(apikey, subdomain)
        self.getByReference = lambda v: self.__get_by_attribute__('reference', v)

    def getSubscriptions(self):
        obj = ChargifySubscription(self.api_key, self.sub_domain)
        return obj.getByCustomerId(self.id)


class CustomerAttributes(ChargifyCustomer):
    __xmlnodename__ = 'customer_attributes'


class ChargifyProductFamily(ChargifyBase):
    """
    Represents Chargify Product Families
    @license    GNU General Public License
    """

    class Meta:
        listing = 'product_families'

    __name__ = 'ChargifyProductFamily'
    __attribute_types__ = {}
    __xmlnodename__ = 'product_family'

    id = None
    accounting_code = None
    description = ''
    handle = ''
    name = ''

    def getComponents(self):
        obj = ChargifyProductFamilyComponent(self.api_key, self.sub_domain)
        return obj.getByProductFamilyId(self.id)


class ChargifyProductFamilyComponent(ChargifyBase):

    __name__ = 'ChargifyProductFamilyComponent'
    __attribute_types__ = {}
    __xmlnodename__ = 'component'
    class Meta:
        listing = 'components'

    id = None
    name = ''
    kind = ''
    product_family_id = 0
    price_per_unit_in_cents = 0
    pricing_scheme = ''
    unit_name = None
    updated_at = None
    created_at = None

    def getByProductFamilyId(self, id):
        return self._applyA(self._get('/product_families/' + str(id) + '/components.xml'),
            self.__name__, self.__xmlnodename__)

    def getByIds(self, product_family_id, id):
        result = None
        url = '/product_families/' + str(product_family_id) + '/components.xml'
        components = self._applyA(
            self._get(url), self.__name__, self.__xmlnodename__)
        if components:
            filtered = filter(lambda c: c.id==str(id), components)
            if len(filtered) > 0:
                result = filtered[0]
        return result


class ChargifyProduct(ChargifyBase):
    """
    Represents Chargify Products
    @license    GNU General Public License
    """

    class Meta:
        listing = 'products'

    __name__ = 'ChargifyProduct'
    __attribute_types__ = {
        'product_family': 'ChargifyProductFamily',
    }
    __xmlnodename__ = 'product'

    id = None
    price_in_cents = 0
    name = ''
    handle = ''
    product_family = None
    accounting_code = ''
    interval_unit = ''
    interval = 0

    def getByHandle(self, handle):
        return self._applyS(self._get('/products/handle/' + str(handle) +
            '.xml'), self.__name__, self.__xmlnodename__)

    def getPaymentPageUrl(self):
        return ('https://' + self.request_host + '/h/' +
            self.id + '/subscriptions/new')

    def getPriceInDollars(self):
        return round(float(self.price_in_cents) / 100, 2)

    def getFormattedPrice(self):
        return "$%.2f" % (self.getPriceInDollars())


class ChargifySubscription(ChargifyBase):
    """
    Represents Chargify Subscriptions
    @license    GNU General Public License
    """

    class Meta:
        listing = 'subscriptions'
        paged = True

    __name__ = 'ChargifySubscription'
    __attribute_types__ = {
        'customer': 'ChargifyCustomer',
        'product': 'ChargifyProduct',
        'credit_card': 'ChargifyCreditCard',
        'components': 'ChargifySubscriptionComponent',
    }
    __xmlnodename__ = 'subscription'

    id = None
    state = ''
    balance_in_cents = 0
    current_period_started_at = None
    current_period_ends_at = None
    trial_started_at = None
    trial_ended_attrial_ended_at = None
    activated_at = None
    expires_at = None
    created_at = None
    updated_at = None
    customer = None
    customer_reference = ''
    product = None
    product_handle = ''
    credit_card = None
    components = None

    def getComponents(self):
        """
        Gets the subscription components
        """
        if self.id is not None:
            obj = ChargifySubscriptionComponent(self.api_key, self.sub_domain)
            return obj.getBySubscriptionId(self.id)

    def getComponent(self, component_id):
        """
        Gets a subscription component..
        """
        obj = ChargifySubscriptionComponent(self.api_key, self.sub_domain)
        return obj.getByCompoundKey(self.id, component_id)

    def getByCustomerId(self, customer_id):
        return self._applyA(self._get('/customers/' + str(customer_id) +
            '/subscriptions.xml'), self.__name__, 'subscription')

    def getBySubscriptionId(self, subscription_id):
        #Throws error if more than element is returned
        i, = self._applyA(self._get('/subscriptions/' + str(subscription_id) +
            '.xml'), self.__name__, 'subscription')
        return i

    def resetBalance(self):
        self._put("/subscriptions/" + self.id + "/reset_balance.xml", '')

    def reactivate(self):
        self._put("/subscriptions/" + self.id + "/reactivate.xml", "")

    def upgrade(self, toProductHandle):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
  <subscription>
    <product_handle>%s</product_handle>
  </subscription>""" % (toProductHandle)
        #end improper indentation

        return self._applyS(self._put("/subscriptions/" + self.id + ".xml",
            xml), self.__name__, "subscription")

    def unsubscribe(self, message):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<subscription>
  <cancellation_message>
    %s
  </cancellation_message>
</subscription>""" % (message)

        self._delete("/subscriptions/" + self.id + ".xml", xml)


class ChargifyCreditCard(ChargifyBase):
    """
    Represents Chargify Credit Cards
    """
    __name__ = 'ChargifyCreditCard'
    __attribute_types__ = {}
    __xmlnodename__ = 'credit_card_attributes'

    first_name = ''
    last_name = ''
    full_number = ''
    masked_card_number = ''
    expiration_month = ''
    expiration_year = ''
    cvv = ''
    type = ''
    billing_address = ''
    billing_city = ''
    billing_state = ''
    billing_zip = ''
    billing_country = ''

    def save(self, subscription):
        path = "/subscriptions/%s.xml" % (subscription.id)
        data = u'<?xml version="1.0" encoding="UTF-8"?><subscription><credit_card_attributes>%s</credit_card_attributes></subscription>' % (
                ''.join([u'<%s>%s</%s>' % (k, v, k) for (k, v) in self.__dict__.items()
            if not k.startswith('_') and k not in self.__ignore__]))
        return self._applyS(self._put(path, data),
            self.__name__, "subscription")


class ChargifySubscriptionComponent(ChargifyBase, CompoundKeyMixin):
    """
    Represents Chargify Subscription Component
    """

    class Meta:
        compound_key = ('subscriptions', 'components')

    __name__ = 'ChargifySubscriptionComponent'
    __attribute_types__ = {}
    __xmlnodename__ = 'component'

    component_id = None
    subscription_id = None
    name = ''
    kind = ''
    unit_name = None
    unit_balance = 0 # metered-component
    allocated_quantity = 0 # quantity-based-component
    pricing_scheme = '' # quantity-based-component
    enabled = False # on-off-component

    def _toxml(self, dom):
        """
        Return a XML Representation of the object
        """
        if self.kind == 'metered_component':
            return None

        if self.kind == 'on_off_component':
            property = 'enabled'
        else:
            property = 'allocated_quantity'

        value = getattr(self, property)
        if not value:
            return None

        element = minidom.Element(self.__xmlnodename__)
        node = minidom.Element('component_id')
        node_txt = dom.createTextNode(str(self.component_id))
        node.appendChild(node_txt)
        element.appendChild(node)
        node = minidom.Element(property)
        node_txt = dom.createTextNode(str(value))
        node.appendChild(node_txt)
        element.appendChild(node)
        return element

    def getBySubscriptionId(self, id):
        return self._applyA(self._get('/subscriptions/' + str(id) + '/components.xml'),
            self.__name__, self.__xmlnodename__)

    def updateQuantity(self, quantity):
        """
        Sets the quantity allocation for a given component id.
        """
        if self.component_id is None or self.subscription_id is None:
            raise ChargifyError()

        if self.kind != 'quantity_based_component':
            raise ChargifyError()

        self.allocated_quantity = quantity
        data = '''<?xml version="1.0" encoding="UTF-8"?><component>
            <allocated_quantity type="integer">%d</allocated_quantity>
          </component>''' % self.allocated_quantity

        dom = minidom.parseString(self.fix_xml_encoding(
        self._put('/subscriptions/%s/components/%s.xml' % (
                str(self.subscription_id), str(self.component_id)), data)
        ))

    def updateOnOff(self, enable):
        """
        Sets the enabled attr for a given component id.
        """
        if self.component_id is None or self.subscription_id is None:
            raise ChargifyError()

        if self.kind != 'on_off_component':
            raise ChargifyError()

        self.enabled = enabled
        data = '''<?xml version="1.0" encoding="UTF-8"?><component>
            <allocated_quantity>%s</allocated_quantity>
          </component>''' % self.enabled

        dom = minidom.parseString(self.fix_xml_encoding(
        self._put('/subscriptions/%s/components/%s.xml' % (
                str(self.subscription_id), str(self.component_id)), data)
        ))

    def getUsages(self):
        """
        Gets the subscription component usages
        """
        if self.component_id is None or self.subscription_id is None:
            raise ChargifyError()

        if self.kind != 'metered_component':
            raise ChargifyError()

        obj = ChargifyComponentUsage(self.api_key, self.sub_domain)
        return obj.getByCompoundKey(self.subscription_id, self.component_id)

    def createUsage(self, quantity, memo=None):
        """
        Creates metered usage for a given component id.
        """
        if self.component_id is None or self.subscription_id is None:
            raise ChargifyError()

        if self.kind != 'metered_component':
            raise ChargifyError()

        data = '''<?xml version="1.0" encoding="UTF-8"?><usage>
            <quantity>%d</quantity><memo>%s</memo></usage>''' % (
                quantity, memo or "")

        return self._applyA(
            self._post('/subscriptions/%s/components/%s/usages.xml' % (
                str(self.subscription_id), str(self.component_id)), data),
            ChargifyComponentUsage.__name__,
            ChargifyComponentUsage.__xmlnodename__)


class ChargifyComponentUsage(ChargifyBase, CompoundKeyMixin):
    """
    Represents Chargify Subscription Component Usage
    """

    class Meta:
        compound_key = ('subscriptions', 'components', 'usages')

    __name__ = 'ChargifyComponentUsage'
    __attribute_types__ = {}
    __xmlnodename__ = 'usage'

    id = None
    quantity = 0
    memo = ''


class ChargifyPostBack(ChargifyBase):
    """
    Represents Chargify API Post Backs
    @license    GNU General Public License
    """
    subscriptions = []

    def __init__(self, apikey, subdomain, postback_data):
        ChargifyBase.__init__(apikey, subdomain)
        if postback_data:
            self._process_postback_data(postback_data)

    def _process_postback_data(self, data):
        """
        Process the Json array and fetches the Subscription Objects
        """
        csub = ChargifySubscription(self.api_key, self.sub_domain)
        postdata_objects = json.loads(data)
        for obj in postdata_objects:
            self.subscriptions.append(csub.getBySubscriptionId(obj))


class Chargify:
    """
    The Chargify class provides the main entry point to the Charify API
    @license    GNU General Public License
    """
    api_key = ''
    sub_domain = ''

    def __init__(self, apikey, subdomain):
        self.api_key = apikey
        self.sub_domain = subdomain

    def Customer(self):
        return ChargifyCustomer(self.api_key, self.sub_domain)

    def CustomerAttributes(self):
        return CustomerAttributes(self.api_key, self.sub_domain)

    def Product(self):
        return ChargifyProduct(self.api_key, self.sub_domain)

    def Component(self):
        return ChargifyProductFamilyComponent(self.api_key,
            self.sub_domain)

    def ProductFamily(self):
        return ChargifyProductFamily(self.api_key, self.sub_domain)

    def Subscription(self):
        return ChargifySubscription(self.api_key, self.sub_domain)

    def SubscriptionComponent(self):
        return ChargifySubscriptionComponent(self.api_key,
            self.sub_domain)

    def ComponentUsage(self):
        return ChargifyComponentUsage(self.api_key, self.sub_domain)

    def CreditCard(self):
        return ChargifyCreditCard(self.api_key, self.sub_domain)

    def PostBack(self, postbackdata):
        return ChargifyPostBack(self.api_key, self.sub_domain, postbackdata)

    @property
    def Customers(self):
        return ChargifyCustomer(self.api_key, self.sub_domain)

    @property
    def Products(self):
        return ChargifyProduct(self.api_key, self.sub_domain)

    @property
    def Components(self):
        return ChargifyProductFamilyComponent(self.api_key, self.sub_domain)

    @property
    def ProductFamilies(self):
        return ChargifyProductFamily(self.api_key, self.sub_domain)

    @property
    def Subscriptions(self):
        return ChargifySubscription(self.api_key, self.sub_domain)

    @property
    def SubscriptionComponents(self):
        return ChargifySubscriptionComponent(self.api_key, self.sub_domain)

    @property
    def ComponentUsages(self):
        return ChargifyComponentUsage(self.api_key, self.sub_domain)
