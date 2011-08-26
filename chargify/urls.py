from django.conf.urls.defaults import patterns, include, url

from views import ChargifyWebhookView
urlpatterns = patterns('',
    url(r'^hook/(?P<signature>[0-9a-f]+)/$', ChargifyWebhookView.as_view(), name='chargify-webhook'),
)
