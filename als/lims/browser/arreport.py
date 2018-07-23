# -*- coding: utf-8 -*-
#
# This file is part of SENAITE.CORE
#
# Copyright 2018 by it's authors.
# Some rights reserved. See LICENSE.rst, CONTRIBUTORS.rst.

from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from bika.lims.browser import BrowserView
from plone import api
from plone.app.layout.globals.interfaces import IViewView
from zope.interface import implements


class ARReportViewView(BrowserView):

    """ AR View form
        The AR fields are printed in a table, using analysisrequest_view.py
    """

    implements(IViewView)
    template = ViewPageTemplateFile("templates/arreport_view.pt")
    messages = []

    def __init__(self, context, request):
        self.init__ = super(ARReportViewView, self).__init__(context, request)
        self.icon = self.portal_url + "/++resource++bika.lims.images/analysisrequest_big.png"
        self.icon_pdf = self.portal_url + "/pdf.png"
        self.icon_csv = self.portal_url + "/text.png"
        self.messages = []

    def __call__(self):
        arreport = self.context

        brains = api.content.find(SearchableText=self.context.id)
        #NOTE: don't know how to get aq_parent without using getObject on the Link
        ars = [l.getObject().aq_parent for l in brains if l.portal_type == 'Link']
        ars.insert(0, arreport.aq_parent)
        self.ars_ids = ', '.join([ar.id for ar in ars])
        self.ars_id_and_url = [{'ar_id': ar.id, 'url': ar.absolute_url()} for ar in ars]
        self.csids = ', '.join([ar.getClientSampleID() for ar in ars])
        return self.template()
