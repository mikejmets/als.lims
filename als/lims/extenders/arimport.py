from archetypes.schemaextender.interfaces import ISchemaModifier
from bika.lims.interfaces import IARImport
from zope.component import adapts
from zope.interface import implements

from Products.DataGridField import Column


class ARImportSchemaModifier(object):
    adapts(IARImport)
    implements(ISchemaModifier)

    def __init__(self, context):
        self.context = context

    def fiddle(self, schema):
        """
        """

        dgf = schema['SampleData']
        temp_var = [i for i in dgf.columns]
        # Not in list - add
        if "Sampler" not in temp_var:
            temp_var.append("Sampler")

        dgf.columns = tuple(temp_var)
        dgf.widget.columns["Sampler"] = Column('Sampler')

        return schema
