from archetypes.schemaextender.interfaces import ISchemaModifier
from bika.lims.utils import getUsers
from bika.lims.interfaces import IARImport
from zope.component import adapts
from zope.interface import implements

from plone import api as ploneapi

from Products.Archetypes.interfaces.vocabulary import IVocabulary
from Products.Archetypes.utils import DisplayList
from Products.DataGridField import SelectColumn


class Vocabulary_Sampler(object):
    implements(IVocabulary)

    def getDisplayList(self, context):
        """ returns an object of class DisplayList as defined in
            Products.Archetypes.utils.

            The instance of the content is given as parameter.
        """
        portal = ploneapi.portal.get()
        samplers = getUsers(portal, ['LabManager', 'Sampler']).items()
        items = [['', ''], ]
        for sampler in samplers:
            items.append([sampler[1], sampler[1]])
        return DisplayList(items)


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
        sampler_vocab = Vocabulary_Sampler()
        dgf.widget.columns["Sampler"] = SelectColumn('Sampler',
                                                     vocabulary=sampler_vocab,
                                                     required=True)

        return schema
