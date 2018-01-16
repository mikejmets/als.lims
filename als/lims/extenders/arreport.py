import sys
from archetypes.schemaextender.interfaces import IOrderableSchemaExtender
from archetypes.schemaextender.interfaces import ISchemaModifier
from bika.lims import bikaMessageFactory as _
from bika.lims.browser.widgets import SelectionWidget as BikaSelectionWidget
from bika.lims.browser.widgets import ReferenceWidget as BikaReferenceWidget
from bika.lims.browser.fields import ProxyField
from bika.lims.fields import ExtensionField
from bika.lims.content.arreport import ARReport
from bika.lims.permissions import EditARContact
from bika.lims.permissions import SampleSample
from plone.app.blob.field import BlobField
from Products.Archetypes.atapi import StringField
from Products.Archetypes.public import *
from Products.Archetypes.references import HoldingReference
from Products.CMFCore import permissions
from zope.component import adapts
from zope.interface import implements

class ExtBlobField(ExtensionField, BlobField):

    "Field extender"

class CSVField(ExtBlobField):
    """
    """


class ARReportSchemaExtender(object):
    adapts(ARReport)
    implements(IOrderableSchemaExtender)

    fields = [
        CSVField('CSV')
    ]

    def __init__(self, context):
        self.context = context

    def getOrder(self, schematas):
        return schematas

    def getFields(self):
        return self.fields
