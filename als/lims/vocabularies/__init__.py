from pkg_resources import resource_filename
from plone.resource.utils import iterDirectoriesOfType

import os
import glob


def getALSARReportTemplates():
    """ Returns an array with the AR Templates available in Bika LIMS  plus the
        templates from the 'reports' resources directory type from each
        additional product.

        Each array item is a dictionary with the following structure:
            {'id': <template_id>,
             'title': <template_title>}

        If the template lives outside the bika.lims add-on, both the template_id
        and template_title include a prefix that matches with the add-on
        identifier. template_title is the same name as the id, but with
        whitespaces and without extension.

        As an example, for a template from the my.product add-on located in
        templates/reports dir, and with a filename "My_cool_report.pt", the
        dictionary will look like:
            {'id': 'my.product:My_cool_report.pt',
             'title': 'my.product: My cool report'}
    """
    resdirname = 'reports'
    p = os.path.join("browser", "analysisrequest", "templates", resdirname)
    return getTemplates(p, resdirname)


def getTemplates(bikalims_path, restype, filter_by_type=False):
    """ Returns an array with the Templates available in the Bika LIMS path
        specified plus the templates from the resources directory specified and
        available on each additional product (restype).

        Each array item is a dictionary with the following structure:
            {'id': <template_id>,
             'title': <template_title>}

        If the template lives outside the bika.lims add-on, both the template_id
        and template_title include a prefix that matches with the add-on
        identifier. template_title is the same name as the id, but with
        whitespaces and without extension.

        As an example, for a template from the my.product add-on located in
        <restype> resource dir, and with a filename "My_cool_report.pt", the
        dictionary will look like:
            {'id': 'my.product:My_cool_report.pt',
             'title': 'my.product: My cool report'}

        :param bikalims_path: the path inside bika lims to find the stickers.
        :type bikalims_path: an string as a path
        :param restype: the resource directory type to search for inside
            an addon.
        :type restype: string
        :param filter_by_type: the folder name to look for inside the
        templates path
        :type filter_by_type: string/boolean
    """
    # Retrieve the templates from bika.lims add-on
    templates_dir = resource_filename("als.lims", bikalims_path)
    tempath = os.path.join(templates_dir, '*.pt')
    templates = [os.path.split(x)[-1] for x in glob.glob(tempath)]

    # Retrieve the templates from other add-ons
    for templates_resource in iterDirectoriesOfType(restype):
        prefix = templates_resource.__name__
        if prefix == 'bika.lims':
            continue
        directory = templates_resource.directory
        # Only use the directory asked in 'filter_by_type'
        if filter_by_type:
            directory = directory + '/' + filter_by_type
        if os.path.isdir(directory):
            dirlist = os.listdir(directory)
            exts = ['{0}:{1}'.format(prefix, tpl) for tpl in dirlist if
                    tpl.endswith('.pt')]
            templates.extend(exts)

    out = []
    templates.sort()
    for template in templates:
        title = template[:-3]
        title = title.replace('_', ' ')
        title = title.replace(':', ': ')
        out.append({'id': template,
                    'title': title})

    return out
