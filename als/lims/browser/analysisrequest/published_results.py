from bika.lims import api
from plone import api as ploneapi
from bika.lims.browser.analysisrequest.published_results import \
    AnalysisRequestPublishedResults as ARPR
from bika.lims import bikaMessageFactory as _
from bika.lims.browser.bika_listing import BikaListingView
from Products.CMFCore.utils import getToolByName
from ZODB.POSException import POSKeyError


class AnalysisRequestPublishedResults(ARPR):

    def __init__(self, context, request):
        super(AnalysisRequestPublishedResults, self).__init__(context, request)
        self.catalog = "portal_catalog"
        self.contentFilter = {'portal_type': ['ARReport', 'Link'],
                              'sort_order': 'reverse'}
        self.context_actions = {}
        self.show_select_column = True
        self.show_workflow_action_buttons = False
        self.form_id = 'published_results'
        self.icon = self.portal_url + "/++resource++bika.lims.images/report_big.png"
        self.title = self.context.translate(_("Published results"))
        self.columns = {
            'COANR': {'title': _('COA NR')},
            'Date': {'title': _('Date')},
            'PublishedBy': {'title': _('Published By')},
            'Recipients': {'title': _('Recipients')},
            'DownloadPDF': {'title': _('Download PDF')},
            'DownloadCSV': {'title': _('Download CSV')},
        }
        self.review_states = [
            {'id': 'default',
             'title': 'All',
             'contentFilter': {},
             'columns': [
                 'COANR',
                 'Date',
                 'PublishedBy',
                 'Recipients',
                 'DownloadPDF',
                 'DownloadCSV',
             ]
             },
        ]

    def __call__(self):
        ar = self.context
        workflow = getToolByName(ar, 'portal_workflow')
        # If is a retracted AR, show the link to child AR and show a warn msg
        if workflow.getInfoFor(ar, 'review_state') == 'invalid':
            childar = hasattr(ar, 'getChildAnalysisRequest') and \
                ar.getChildAnalysisRequest() or None
            childid = childar and childar.getId() or None
            message = _('This Analysis Request has been withdrawn and is '
                        'shown for trace-ability purposes only. Retest: '
                        '${retest_child_id}.',
                        mapping={'retest_child_id': safe_unicode(childid) or ''})
            self.context.plone_utils.addPortalMessage(
                self.context.translate(message), 'warning')
        # If is an AR automatically generated due to a Retraction, show it's
        # parent AR information
        if hasattr(ar, 'getParentAnalysisRequest') \
           and ar.getParentAnalysisRequest():
            par = ar.getParentAnalysisRequest()
            message = _('This Analysis Request has been '
                        'generated automatically due to '
                        'the retraction of the Analysis '
                        'Request ${retracted_request_id}.',
                        mapping={'retracted_request_id': par.getId()})
            self.context.plone_utils.addPortalMessage(
                self.context.translate(message), 'info')

        # Printing workflow enabled?
        # If not, remove the Column
        self.printwfenabled = self.context.bika_setup.getPrintingWorkflowEnabled()
        printed_colname = 'DatePrinted'
        if not self.printwfenabled and printed_colname in self.columns:
            # Remove "Printed" columns
            del self.columns[printed_colname]
            tmprvs = []
            for rs in self.review_states:
                tmprs = rs
                tmprs['columns'] = [c for c in rs.get('columns', []) if
                                    c != printed_colname]
                tmprvs.append(tmprs)
            self.review_states = tmprvs

        template = BikaListingView.__call__(self)
        return template

    def contentsMethod(self, contentFilter):
        """
        ARReport (or Link) objects associated to the current Analysis request.
        If the user is not a Manager or LabManager or Client, no items are
        displayed.
        """
        allowedroles = ['Manager', 'LabManager', 'Client', 'LabClerk']
        pm = getToolByName(self.context, "portal_membership")
        member = pm.getAuthenticatedMember()
        roles = member.getRoles()
        allowed = [a for a in allowedroles if a in roles]
        brains = ploneapi.content.find(
            context=self.context,
            portal_type=['ARReport', 'Link']) if allowed else []
        return [x.getObject() for x in brains]

    def folderitem(self, obj, item, index):

        if obj.portal_type == 'Link':
            # Grab the report object that the link points to
            obj = api.get_object_by_path(obj.remoteUrl)

        item['COANR'] = obj.id

        item['PublishedBy'] = self.user_fullname(obj.Creator())

        # Formatted creation date of report
        creation_date = obj.created()
        fmt_date = self.ulocalized_time(creation_date, long_format=1)
        item['Date'] = fmt_date

        # Links to recipient profiles
        recipients = obj.getRecipients()
        links = ["<a href='{Url}'>{Fullname}</a>".format(
            Fullname=r['Fullname'],
            Url=api.get_url(api.get_object_by_uid(r['UID'])))
            for r in recipients if r['EmailAddress']]
        if len(links) == 0:
            links = ["{Fullname}".format(**r) for r in recipients]
        item['replace']['Recipients'] = ', '.join(links)

        # download link 'Download PDF (size)'
        dll = []
        try:  #
            pdf_data = obj.getPdf()
            assert pdf_data
            z = pdf_data.get_size()
            z = z / 1024 if z > 0 else 0
            dll.append("<a href='{}/at_download/Pdf'>{}</a>".format(
                obj.absolute_url(), _("Download PDF"), z))
        except (POSKeyError, AssertionError):
            # POSKeyError: 'No blob file'
            pass
        item['DownloadPDF'] = ''
        item['after']['DownloadPDF'] = ', '.join(dll)

        # download link 'Download CSV (size)'
        dll = []
        if hasattr(obj, 'CSV'):
            try:
                dll.append("<a href='{}/at_download/CSV'>{}</a>".format(
                    obj.absolute_url(), _("Download CSV"), 0))
            except (POSKeyError, AssertionError):
                # POSKeyError: 'No blob file'
                pass
            item['DownloadCSV'] = ''
            item['after']['DownloadCSV'] = ', '.join(dll)

        return item
