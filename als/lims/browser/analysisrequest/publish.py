import App
import csv
import transaction
import StringIO
import os
import tempfile
from bika.lims import bikaMessageFactory as _, t
from bika.lims import logger
from bika.lims.browser import BrowserView
from DateTime import DateTime
from bika.lims.browser.analysisrequest.publish import \
    AnalysisRequestPublishView as ARPV
from bika.lims.browser.analysisrequest.publish import \
    AnalysisRequestDigester  # as ARD
from bika.lims.idserver import renameAfterCreation
from bika.lims.interfaces import IAnalysisRequest
from bika.lims.utils import encode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.Utils import formataddr
from smtplib import SMTPRecipientsRefused, SMTPServerDisconnected
from plone.app.content.browser.interfaces import IFolderContentsView
from plone.resource.utils import queryResourceDirectory
from Products.CMFCore.WorkflowCore import WorkflowException
from Products.CMFCore.utils import getToolByName
from Products.CMFPlone.utils import _createObjectByType, safe_unicode
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zope.interface import implements

from als.lims.vocabularies import getALSARReportTemplates
# attachPdf, createPdf in bika.als were different to that found in senaite.core
# using the versions sourced from bika.als

import re
import urllib2
import traceback
from bika.lims.utils import tmpID, to_utf8
from email import Encoders
from email.mime.base import MIMEBase
from pkg_resources import resource_filename
from weasyprint import HTML, CSS
from zope.component.hooks import getSite


def createPdf(htmlreport, outfile=None, css=None, images={}):
    """create a PDF from some HTML.
    htmlreport: rendered html
    outfile: pdf filename; if supplied, caller is responsible for creating
             and removing it.
    css: remote URL of css file to download
    images: A dictionary containing possible URLs (keys) and local filenames
            (values) with which they may to be replaced during rendering.
    # WeasyPrint will attempt to retrieve images directly from the URL
    # referenced in the HTML report, which may refer back to a single-threaded
    # (and currently occupied) zeoclient, hanging it.  All image source
    # URL's referenced in htmlreport should be local files.
    """
    # A list of files that should be removed after PDF is written
    htmlreport = to_utf8(htmlreport)
    cleanup, htmlreport = localize_images(htmlreport)
    css_def = ''
    if css:
        if css.startswith("http://") or css.startswith("https://"):
            # Download css file in temp dir
            u = urllib2.urlopen(css)
            _cssfile = tempfile.mktemp(suffix='.css')
            localFile = open(_cssfile, 'w')
            localFile.write(u.read())
            localFile.close()
            cleanup.append(_cssfile)
        else:
            _cssfile = css
        cssfile = open(_cssfile, 'r')
        css_def = cssfile.read()

    for (key, val) in images.items():
        htmlreport = htmlreport.replace(key, val)

    # render
    htmlreport = to_utf8(htmlreport)
    renderer = HTML(string=htmlreport, encoding='utf-8')
    pdf_fn = outfile if outfile else tempfile.mktemp(suffix=".pdf")
    if css:
        renderer.write_pdf(pdf_fn, stylesheets=[CSS(string=css_def)])
    else:
        renderer.write_pdf(pdf_fn)
    # return file data
    pdf_data = open(pdf_fn, "rb").read()
    if outfile is None:
        os.remove(pdf_fn)
    for fn in cleanup:
        os.remove(fn)
    return pdf_data


def attachPdf(mimemultipart, pdfdata, filename=None):
    """Attach a PDF file to a mime multipart message
    """
    part = MIMEBase('application', "pdf")
    fn = filename if filename else tmpID()
    part.add_header(
        'Content-Disposition', 'attachment; filename="{}.pdf"'.format(fn))
    part.set_payload(pdfdata)
    Encoders.encode_base64(part)
    mimemultipart.attach(part)


def localize_images(html):
    """The PDF renderer will attempt to retrieve attachments directly from the
    URL referenced in the HTML report, which may refer back to a single-threaded
    (and currently occupied) zeoclient, hanging it.  All images hosted via
    URLs that refer to the Plone site, must be converted to local file paths.
    This function modifies the URL of all images that can be resolved using
    traversal from the root of the Plone site (eg, Image or File fields).
    It also discovers images in 'bika' skins folder and modifies their URLs.
    Other images may need to be handled manually.

    Returns a list of files which were created, and a modified copy
    of html where all remote URL's have been replaced with file:///...
    """
    cleanup = []
    _html = html.decode('utf-8')

    # get site URL for traversal
    portal = getSite()
    skins = portal.portal_skins
    portal_url = portal.absolute_url().split("?")[0]

    # all src="" attributes
    for match in re.finditer("""src.*\=.*(http[^'"]*)""", _html, re.I):
        url = match.group(1)
        filename = url.split("/")[-1]
        if '++' in url:
            # Resource directories
            outfilename = resource_filename(
                'bika.lims', 'browser/images/' + filename)
        elif filename in skins['bika']:
            # portal_skins
            outfilename = skins['bika'][filename].filename
        else:
            # File/Image/Attachment fieldx
            att_path = url.replace(portal_url + "/", "").encode('utf-8')
            attachment = portal.unrestrictedTraverse(att_path)
            if hasattr(attachment, 'getAttachmentFile'):
                attachment = attachment.getAttachmentFile()

            filename = attachment.filename
            extension = "." + filename.split(".")[-1]
            outfile, outfilename = tempfile.mkstemp(suffix=extension)
            outfile = open(outfilename, 'wb')
            data = str(attachment.data)
            outfile.write(data)
            outfile.close()
            cleanup.append(outfilename)

        _html = _html.replace(url, "file://" + outfilename)
    return cleanup, _html


class AnalysisRequestPublishView(ARPV):
    implements(IFolderContentsView)
    template = ViewPageTemplateFile("templates/analysisrequest_publish.pt")

    def __init__(self, context, request, publish=False):
        BrowserView.__init__(self, context, request)
        self.context = context
        self.request = request
        self._publish = publish
        self._ars = [self.context]
        self._digester = AnalysisRequestDigester()
        # Simple caching hack.  Various templates can allow these functions
        # to be called many thousands of times for relatively simple reports.
        # To prevent bad code from causing this, we cache all analysis data
        # here.
        self._cache = {
            '_analysis_data': {},
            '_qcanalyses_data': {},
            '_ar_data': {}
        }

    def __call__(self):
        if self.context.portal_type == 'AnalysisRequest':
            self._ars = [self.context]
        elif self.context.portal_type in ('AnalysisRequestsFolder', 'Client') \
                and self.request.get('items', ''):
            uids = self.request.get('items').split(',')
            uc = getToolByName(self.context, 'uid_catalog')
            self._ars = [obj.getObject() for obj in uc(UID=uids)]
        else:
            # Do nothing
            self.destination_url = self.request.get_header(
                "referer", self.context.absolute_url())

        # Group ARs by client
        groups = {}
        for ar in self._ars:
            idclient = ar.aq_parent.id
            if idclient not in groups:
                groups[idclient] = [ar]
            else:
                groups[idclient].append(ar)
        self._arsbyclient = [group for group in groups.values()]

        # Report may want to print current date
        self.current_date = self.ulocalized_time(DateTime(), long_format=True)

        # Do publish?
        if self.request.form.get('publish', '0') == '1':
            self.publishFromPOST()
        else:
            return self.template()

    def getAvailableFormats(self):
        """Returns the available formats found in templates/reports
        """
        return getALSARReportTemplates()

    def _renderTemplate(self):
        """Returns the html template to be rendered in accordance with the
        template specified in the request ('template' parameter)
        """
        templates_dir = 'templates/reports'
        embedt = self.request.form.get('template', self._DEFAULT_TEMPLATE)
        if embedt.find(':') >= 0:
            prefix, template = embedt.split(':')
            templates_dir = queryResourceDirectory('reports', prefix).directory
            embedt = template
        embed = ViewPageTemplateFile(os.path.join(templates_dir, embedt))
        return embedt, embed(self)

    def getReportTemplate(self):
        """Returns the html template for the current ar and moves to
        the next ar to be processed. Uses the selected template
        specified in the request ('template' parameter)
        """
        embedt = ""
        try:
            embedt, reptemplate = self._renderTemplate()
        except:
            tbex = traceback.format_exc()
            arid = self._ars[self._current_ar_index].id
            reptemplate = \
                "<div class='error-report'>%s - %s '%s':<pre>%s</pre></div>" \
                % (arid, _("Unable to load the template"), embedt, tbex)
        self._nextAnalysisRequest()
        return reptemplate

    def getGroupedReportTemplate(self):
        """Returns the html template for the current group of ARs and moves to
        the next group to be processed. Uses the selected template
        specified in the request ('template' parameter)
        """
        embedt = ""
        try:
            embedt, reptemplate = self._renderTemplate()
        except:
            tbex = traceback.format_exc()
            reptemplate = \
                "<div class='error-report'>%s '%s':<pre>%s</pre></div>" \
                % (_("Unable to load the template"), embedt, tbex)
        self._nextAnalysisRequestGroup()
        return reptemplate

    def getReportStyle(self):
        """Returns the css style to be used for the current template.
        If the selected template is 'default.pt', this method will
        return the content from 'default.css'. If no css file found
        for the current template, returns empty string
        """
        template = self.request.form.get('template', self._DEFAULT_TEMPLATE)
        content = ''
        if template.find(':') >= 0:
            prefix, template = template.split(':')
            resource = queryResourceDirectory('reports', prefix)
            css = '{0}.css'.format(template[:-3])
            if css in resource.listDirectory():
                content = resource.readFile(css)
        else:
            this_dir = os.path.dirname(os.path.abspath(__file__))
            templates_dir = os.path.join(this_dir, 'templates/reports/')
            path = '%s/%s.css' % (templates_dir, template[:-3])
            with open(path, 'r') as content_file:
                content = content_file.read()
        return content

    def publishFromPOST(self):
        """The handler for the Publish button in the report preview page.
        """
        html = self.request.form.get('html')
        style = self.request.form.get('style')
        uids = self.request.form.get('uid').split(':')
        template = self.request.form.get('template', '')
        reporthtml = "<html><head>%s</head><body><div " \
                     "id='report'>%s</body></html>" % (
                         style, html)
        publishedars = []
        if 'multi_' in template.lower():
            publishedars = self.publishFromHTML(
                uids, safe_unicode(reporthtml).encode('utf-8'))
        else:
            for uid in uids:
                ars = self.publishFromHTML(
                    uid, safe_unicode(reporthtml).encode('utf-8'))
                publishedars.extend(ars)
        return publishedars

    def get_mail_subject(self, ars):
        """Returns the email subject in accordance with the client
        preferences
        """
        client = ars[0].aq_parent
        subject_items = client.getEmailSubject()
        ai = co = cr = cs = False
        if 'ar' in subject_items:
            ai = True
        if 'co' in subject_items:
            co = True
        if 'cr' in subject_items:
            cr = True
        if 'cs' in subject_items:
            cs = True
        ais = []
        cos = []
        crs = []
        css = []
        for ar in ars:
            blanks_found = False
            if ai:
                ais.append(ar.getId())
            if co:
                if ar.getClientOrderNumber():
                    if not ar.getClientOrderNumber() in cos:
                        cos.append(ar.getClientOrderNumber())
                else:
                    blanks_found = True
            if cr or cs:
                sample = ar.getSample()
                if cr:
                    if sample.getClientReference():
                        if not sample.getClientReference() in crs:
                            crs.append(sample.getClientReference())
                    else:
                        blanks_found = True
                if cs:
                    if sample.getClientSampleID():
                        if not sample.getClientSampleID() in css:
                            css.append(sample.getClientSampleID())
                    else:
                        blanks_found = True
            line_items = []
            if ais:
                ais.sort()
                li = t(_('ARs: ${ars}', mapping={'ars': ', '.join(ais)}))
                line_items.append(li)
            if cos:
                cos.sort()
                li = t(_('Orders: ${orders}', mapping={'orders': ', '.join(cos)}))
                line_items.append(li)
            if crs:
                crs.sort()
                li = t(_(
                    'Refs: ${references}', mapping={'references': ', '.join(crs)}))
                line_items.append(li)
            if css:
                css.sort()
                li = t(_(
                    'Samples: ${samples}', mapping={'samples': ', '.join(css)}))
                line_items.append(li)
        tot_line = ' '.join(line_items)
        if tot_line:
            subject = t(_('Analysis results for ${subject_parts}',
                          mapping={'subject_parts': tot_line}))
            if blanks_found:
                subject += (' ' + t(_('and others')))
        else:
            subject = t(_('Analysis results'))
        return subject, tot_line

    def publishFromHTML(self, ar_uids, results_html):
        """ar_uids can be a single UID or a list of AR uids.  The resulting
        ARs will be published together (ie, sent as a single outbound email)
        and the entire report will be saved in each AR's published-results
        tab.
        """
        debug_mode = App.config.getConfiguration().debug_mode
        wf = getToolByName(self.context, 'portal_workflow')

        # The AR can be published only and only if allowed
        uc = getToolByName(self.context, 'uid_catalog')
        ars = [p.getObject() for p in uc(UID=ar_uids)]
        if not ars:
            return []

        ar = ars[0]
        # Generate a ARReport only for the 1st AR (if multiple ARs have
        # been selected)
        reportid = ar.generateUniqueId('ARReport')
        # Modify the workflow state of each AR that's been published
        status = wf.getInfoFor(ar, 'review_state')
        transitions = {'verified': 'publish', 'published': 'republish'}
        transition = transitions.get(status, 'prepublish')
        try:
            wf.doActionFor(ar, transition)
        except WorkflowException:
            pass

        report = _createObjectByType("ARReport", ar, reportid)
        report.edit(
            AnalysisRequest=ar.UID(),
        )
        report.unmarkCreationFlag()
        renameAfterCreation(report)
        fn = report.getId()
        reports_link = "<a href='{}'>{}</a>".format(ar.absolute_url(), fn)
        coa_nr_text = 'COA ID is generated on publication'
        results_html = results_html.replace(coa_nr_text, reports_link)
        # Create the pdf report for the supplied HTML.
        pdf_report = createPdf(results_html, False)
        # PDF written to debug file?
        if debug_mode:
            pdf_fn = tempfile.mktemp(suffix=".pdf")
            logger.info("Writing PDF for {} to {}".format(
                ', '.join([ar.Title() for ar in ars]), pdf_fn))
            open(pdf_fn, 'wb').write(pdf_report)

        # ALS hack.  Create the CSV they desire here now
        csvdata = self.create_als_csv(ars)
        report.edit(
            Html=results_html,
            Recipients=self.get_arreport_recip_records(ar),
            Pdf=pdf_report,
            CSV=csvdata,
        )
        fld = report.getField('Pdf')
        fld.get(report).setFilename(fn + ".pdf")
        fld.get(report).setContentType('application/pdf')
        fld = report.getField('CSV')
        fld.get(report).setFilename(fn + ".csv")
        fld.get(report).setContentType('text/csv')
        transaction.commit()

        if len(ars) > 1:
            # publish and create links in the other ars
            for ar in ars[1:]:
                # Publish AR
                try:
                    wf.doActionFor(ar, transition)
                except WorkflowException:
                    pass

                # Link to first ARReport
                linkid = ar.generateUniqueId('Link')
                link = _createObjectByType("Link", ar, linkid)
                link.edit(
                    remoteUrl=report.absolute_url()
                )
                link.unmarkCreationFlag()
                renameAfterCreation(link)

        # compose and send email.
        # The managers of the departments for which the current AR has
        # at least one AS must receive always the pdf report by email.
        # https://github.com/bikalabs/Bika-LIMS/issues/1028
        lab = ars[0].bika_setup.laboratory
        mime_msg = MIMEMultipart('related')
        mime_msg['Subject'] = self.get_mail_subject(ars)[0]
        # mime_msg['Subject'] = "Published results for %s" % \
        #                       ",".join([ar.Title() for ar in ars])
        mime_msg['From'] = formataddr(
            (encode_header(lab.getName()), lab.getEmailAddress()))
        mime_msg.preamble = 'This is a multi-part MIME message.'
        msg_txt = MIMEText(results_html, _subtype='html')
        mime_msg.attach(msg_txt)

        to = []
        to_emails = []

        mngrs = []
        for ar in ars:
            resp = ar.getResponsible()
            if 'dict' in resp and resp['dict']:
                for mngrid, mngr in resp['dict'].items():
                    if mngr['email'] not in [m['email'] for m in mngrs]:
                        mngrs.append(mngr)
        for mngr in mngrs:
            name = mngr['name']
            email = mngr['email']
            to.append(formataddr((encode_header(name), email)))

        # Send report to recipients
        for ar in ars:
            recips = self.get_recipients(ar)
            for recip in recips:
                if 'email' not in recip.get('pubpref', []) \
                        or not recip.get('email', ''):
                    continue
                title = encode_header(recip.get('title', ''))
                email = recip.get('email')
                if email not in to_emails:
                    to.append(formataddr((title, email)))
                    to_emails.append(email)

        # Create the new mime_msg object, cause the previous one
        # has the pdf already attached
        mime_msg = MIMEMultipart('related')
        mime_msg['Subject'] = self.get_mail_subject(ars)[0]
        # mime_msg['Subject'] = "Published results for %s" % \
        #                       ",".join([ar.Title() for ar in ars])
        mime_msg['From'] = formataddr(
            (encode_header(lab.getName()), lab.getEmailAddress()))
        mime_msg.preamble = 'This is a multi-part MIME message.'
        msg_txt = MIMEText(results_html, _subtype='html')
        mime_msg.attach(msg_txt)
        mime_msg['To'] = ",".join(to)

        # Attach the pdf to the email
        # fn = "%s" % coanr
        attachPdf(mime_msg, pdf_report, fn)

        # Attach to email
        # fn = coanr if coanr else '_'.join([ar.Title() for ar in ars])
        part = MIMEBase('text', "csv")
        part.add_header('Content-Disposition',
                        'attachment; filename="{}.csv"'.format(fn))
        part.set_payload(csvdata)
        mime_msg.attach(part)

        msg_string = mime_msg.as_string()

        try:
            host = getToolByName(ars[0], 'MailHost')
            host.send(msg_string, immediate=True)
        except SMTPServerDisconnected as msg:
            logger.warn("SMTPServerDisconnected: %s." % msg)
        except SMTPRecipientsRefused as msg:
            raise WorkflowException(str(msg))

        return ars

    def get_arreport_recip_records(self, ar):
        recip_records = [
            {'UID': r.UID(),
             'Username': r.getUsername(),
             'Fullname': r.getFullname(),
             'EmailAddress': r.getEmailAddress(),
             'PublicationModes': ','.join(r.getPublicationPreference())}
            for r in [ar.getContact()] + ar.getCCContact()]
        return recip_records

    def create_als_csv(self, ars):
        analyses = []
        for ar in ars:
            analyses.extend(ar.getAnalyses(full_objects=True))
        #
        fieldnames = [
            t(_('Batch ID')),
            t(_('Client Batch ID')),
            t(_('Sample ID')),
            t(_('Client Sample ID')),
            t(_('Analysis Request ID')),
            t(_('Sample Type')),
            t(_('Sample Point')),
            t(_('Date/Time Sampled')),
            t(_('Analysis Service')),
            t(_('Method')),
            t(_('LOR')),
            t(_('Unit')),
            t(_('Value')),
        ]
        #
        output = StringIO.StringIO()
        dw = csv.DictWriter(output, fieldnames=fieldnames)
        dw.writerow(dict((fn, fn) for fn in fieldnames))
        #
        for analysis in analyses:
            service = analysis.getService()
            method = analysis.getMethod().Title() \
                if analysis.getMethod() else ''
            ar = analysis.aq_parent
            batch = ar.getBatch()
            l_batchid = batch.getBatchID() if batch else ''
            c_batchid = batch.getClientBatchID() if batch else ''
            date = analysis.getResultCaptureDate()
            date = self.ulocalized_time(date, long_format=True)
            sample = ar.getSample()
            l_sid = sample.getId()
            c_sid = sample.getClientSampleID()
            st_title = sample.getSampleType().Title()
            point = sample.getSamplePoint()
            sp_title = point.Title() if point else ''
            row = {
                t(_('Batch ID')):
                    safe_unicode(l_batchid).encode('utf-8'),
                t(_('Client Batch ID')):
                    safe_unicode(c_batchid).encode('utf-8'),
                t(_('Sample ID')):
                    safe_unicode(l_sid).encode('utf-8'),
                t(_('Client Sample ID')):
                    safe_unicode(c_sid).encode('utf-8'),
                t(_('Analysis Request ID')):
                    safe_unicode(ar.getId()).encode('utf-8'),
                t(_('Sample Type')):
                    safe_unicode(st_title).encode('utf-8'),
                t(_('Sample Point')):
                    safe_unicode(sp_title).encode('utf-8'),
                t(_('Date/Time Sampled')):
                    date,
                t(_('Analysis Service')):
                    safe_unicode(service.Title()).encode('utf-8'),
                t(_('Method')):
                    safe_unicode(method).encode('utf-8'),
                t(_('LOR')):
                    service.getLowerDetectionLimit(),
                t(_('Unit')):
                    safe_unicode(service.getUnit()).encode('utf-8'),
                t(_('Value')):
                    analysis.getResult(),
            }
            dw.writerow(row)

        retval = output.getvalue()

        return retval

    def _lab_address(self, lab):
        lab_address = lab.getPostalAddress() \
                      or lab.getBillingAddress() \
                      or lab.getPhysicalAddress()
        return _format_address(lab_address)

    def _client_data(self, ar):
        data = {}
        client = ar.aq_parent
        if client:
            data['obj'] = client
            data['id'] = client.id
            data['url'] = client.absolute_url()
            data['name'] = to_utf8(client.getName())
            data['phone'] = to_utf8(client.getPhone())
            data['fax'] = to_utf8(client.getFax())

            data['address'] = to_utf8(get_client_address(ar))
        return data

    def getAnalysisBasedTransposedMatrix(self, ars):
        """ Returns a dict with the following structure:
            {'category_1_name':
                {'service_1_title':
                    {'service_1_uid':
                        {'service': <AnalysisService-1>,
                         'ars': {'ar1_id': [<Analysis (for as-1)>,
                                           <Analysis (for as-1)>],
                                 'ar2_id': [<Analysis (for as-1)>]
                                },
                        },
                    },
                {'service_2_title':
                     {'service_2_uid':
                        {'service': <AnalysisService-2>,
                         'ars': {'ar1_id': [<Analysis (for as-2)>,
                                           <Analysis (for as-2)>],
                                 'ar2_id': [<Analysis (for as-2)>]
                                },
                        },
                    },
                ...
                },
            }
        """
        analyses = {}
        for ar in ars:
            ans = [an.getObject() for an in ar.getAnalyses()]
            for an in ans:
                service = an.getService()
                cat = service.getCategoryTitle()
                if cat not in analyses:
                    analyses[cat] = {
                        service.title: {
                            'service': service,
                            'accredited': service.getAccredited(),
                            'ars': {ar.id: an.getFormattedResult()}
                        }
                    }
                elif service.title not in analyses[cat]:
                    analyses[cat][service.title] = {
                        'service': service,
                        'accredited': service.getAccredited(),
                        'ars': {ar.id: an.getFormattedResult()}
                    }
                else:
                    d = analyses[cat][service.title]
                    d['ars'][ar.id] = an.getFormattedResult()
                    analyses[cat][service.title] = d
        return analyses


def get_client_address(context):
    if context.portal_type == 'AnalysisRequest':
        client = context.aq_parent
    else:
        client = context
    client_address = client.getPostalAddress()
    if not client_address:
        ar = context
        if not IAnalysisRequest.providedBy(ar):
            return ""
        # Data from the first contact
        contact = ar.getContact()
        if contact and contact.getBillingAddress():
            client_address = contact.getBillingAddress()
        elif contact and contact.getPhysicalAddress():
            client_address = contact.getPhysicalAddress()
    return _format_address(client_address)


def _format_address(address):
    """Takes a value from an AddressField, returns a div class=address
    with spans inside, containing the address field values.
    """
    addr = ''
    if address:
        # order of divs in output html
        keys = ['address', 'city', 'district', 'state', 'zip', 'country']
        addr = ''.join(["<div>%s</div>" % address.get(v) for v in keys
                        if address.get(v, None)])
    return "<div class='address'>%s</div>" % addr
