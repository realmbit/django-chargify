# encoding: utf-8
import datetime
import traceback

from south.db import db
from south.v2 import SchemaMigration

from django.db import models
from django.conf import settings

from chargify.models import Subscription, Customer


class Migration(SchemaMigration):

    def forwards(self, orm):
        # Don't do anything. This migration used to reload all the data. There
        # is now a management commad to do this and it does not happen
        # automatically because it can take a long time.
        pass


    def backwards(self, orm):
        pass


    models = { }

    complete_apps = ['chargify']
