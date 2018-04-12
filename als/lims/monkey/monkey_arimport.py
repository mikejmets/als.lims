# -*- coding: utf-8 -*-
#
# This file is part of Bika LIMS
#
# Copyright 2011-2017 by it's authors.
# Some rights reserved. See LICENSE.txt, AUTHORS.txt.

import transaction
from bika.lims.content.analysisrequest import schema as ar_schema
from bika.lims.content.sample import schema as sample_schema
from bika.lims.utils import getUsers
from bika.lims.utils.analysisrequest import create_analysisrequest
from Products.Archetypes.utils import addStatusMessage
from Products.CMFCore.utils import getToolByName
from zope.i18nmessageid import MessageFactory

from plone import api as ploneapi

from copy import deepcopy
from bika.lims import bikaMessageFactory as _
from collective.progressbar.events import InitialiseProgressBar
from collective.progressbar.events import ProgressBar
from collective.progressbar.events import ProgressState
from collective.progressbar.events import UpdateProgressEvent
from zope.event import notify


_p = MessageFactory(u"plone")


def workflow_before_validate(self):
    """This function transposes values from the provided file into the
    ARImport object's fields, and checks for invalid values.

    If errors are found:
        - Validation transition is aborted.
        - Errors are stored on object and displayed to user.

    """
    # Re-set the errors on this ARImport each time validation is attempted.
    # When errors are detected they are immediately appended to this field.
    self.setErrors([])

    def item_empty(gridrow, key):
        if not gridrow.get(key, False):
            return True
        return len(gridrow[key]) == 0

    row_nr = 0
    for gridrow in self.getSampleData():
        row_nr += 1
        if item_empty(gridrow, 'Sampler'):
            self.error("Row %s: %s is required" % (row_nr, 'Sampler'))

    self.validate_headers()
    self.validate_samples()

    if self.getErrors():
        addStatusMessage(self.REQUEST, _p('Validation errors.'), 'error')
        transaction.commit()
        self.REQUEST.response.write(
            '<script>document.location.href="%s/edit"</script>' % (
                self.absolute_url()))
    self.REQUEST.response.write(
        '<script>document.location.href="%s/view"</script>' % (
            self.absolute_url()))


def save_sample_data(self):
    """Save values from the file's header row into the DataGrid columns
    after doing some very basic validation
    """
    bsc = getToolByName(self, 'bika_setup_catalog')
    keywords = self.bika_setup_catalog.uniqueValuesFor('getKeyword')
    profiles = []
    for p in bsc(portal_type='AnalysisProfile'):
        p = p.getObject()
        profiles.append(p.Title())
        profiles.append(p.getProfileKey())

    sample_data = self.get_sample_values()
    if not sample_data:
        return False

    # columns that we expect, but do not find, are listed here.
    # we report on them only once, after looping through sample rows.
    missing = set()

    # This contains all sample header rows that were not handled
    # by this code
    unexpected = set()

    # Save other errors here instead of sticking them directly into
    # the field, so that they show up after MISSING and before EXPECTED
    errors = []

    # This will be the new sample-data field value, when we are done.
    grid_rows = []

    row_nr = 0
    for row in sample_data['samples']:
        row = dict(row)
        row_nr += 1

        # sid is just for referring the user back to row X in their
        # in put spreadsheet
        gridrow = {'sid': row['Samples']}
        del (row['Samples'])

        # We'll use this later to verify the number against selections
        if 'Total number of Analyses or Profiles' in row:
            nr_an = row['Total number of Analyses or Profiles']
            del (row['Total number of Analyses or Profiles'])
        else:
            nr_an = 0
        try:
            nr_an = int(nr_an)
        except ValueError:
            nr_an = 0

        # TODO this is ignored and is probably meant to serve some purpose.
        del (row['Price excl Tax'])

        if 'Sampler' in row.keys():
            gridrow['Sampler'] = row['Sampler']
            del (row['Sampler'])

        # ContainerType - not part of sample or AR schema
        if 'ContainerType' in row:
            title = row['ContainerType']
            if title:
                obj = self.lookup(('ContainerType',),
                                  Title=row['ContainerType'])
                if obj:
                    gridrow['ContainerType'] = obj[0].UID
            del (row['ContainerType'])

        if 'SampleMatrix' in row:
            # SampleMatrix - not part of sample or AR schema
            title = row['SampleMatrix']
            if title:
                obj = self.lookup(('SampleMatrix',),
                                  Title=row['SampleMatrix'])
                if obj:
                    gridrow['SampleMatrix'] = obj[0].UID
            del (row['SampleMatrix'])

        # match against sample schema
        for k, v in row.items():
            if k in ['Analyses', 'Profiles']:
                continue
            if k in sample_schema:
                del (row[k])
                if v:
                    try:
                        value = self.munge_field_value(
                            sample_schema, row_nr, k, v)
                        gridrow[k] = value
                    except ValueError as e:
                        errors.append(e.message)

        # match against ar schema
        for k, v in row.items():
            if k in ['Analyses', 'Profiles']:
                continue
            if k in ar_schema:
                del (row[k])
                if v:
                    try:
                        value = self.munge_field_value(
                            ar_schema, row_nr, k, v)
                        gridrow[k] = value
                    except ValueError as e:
                        errors.append(e.message)

        # Count and remove Keywords and Profiles from the list
        gridrow['Analyses'] = []
        for k, v in row.items():
            if k in keywords:
                del (row[k])
                if str(v).strip().lower() not in ('', '0', 'false'):
                    gridrow['Analyses'].append(k)
        gridrow['Profiles'] = []
        for k, v in row.items():
            if k in profiles:
                del (row[k])
                if str(v).strip().lower() not in ('', '0', 'false'):
                    gridrow['Profiles'].append(k)
        if len(gridrow['Analyses']) + len(gridrow['Profiles']) != nr_an:
            errors.append(
                "Row %s: Number of analyses does not match provided value" %
                row_nr)

        grid_rows.append(gridrow)

    self.setSampleData(grid_rows)

    if missing:
        self.error("SAMPLES: Missing expected fields: %s" %
                   ','.join(missing))

        for thing in errors:
            self.error(thing)

        if unexpected:
            self.error("Unexpected header fields: %s" %
                       ','.join(unexpected))


def workflow_script_import(self):
    """Create objects from valid ARImport
    """
    bsc = getToolByName(self, 'bika_setup_catalog')
    client = self.aq_parent

    title = _('Submitting AR Import')
    description = _('Creating and initialising objects')
    bar = ProgressBar(self, self.REQUEST, title, description)
    notify(InitialiseProgressBar(bar))

    profiles = [x.getObject() for x in bsc(portal_type='AnalysisProfile')]

    gridrows = self.schema['SampleData'].get(self)
    row_cnt = 0
    for therow in gridrows:
        row = deepcopy(therow)
        row_cnt += 1

        # Profiles are titles, profile keys, or UIDS: convert them to UIDs.
        newprofiles = []
        for title in row['Profiles']:
            objects = [x for x in profiles
                       if title in (x.getProfileKey(), x.UID(), x.Title())]
            for obj in objects:
                newprofiles.append(obj.UID())
        row['Profiles'] = newprofiles

        # Same for analyses
        newanalyses = set(self.get_row_services(row) +
                          self.get_row_profile_services(row))
        # get batch
        batch = self.schema['Batch'].get(self)
        if batch:
            row['Batch'] = batch.UID()
        # Add AR fields from schema into this row's data
        row['ClientReference'] = self.getClientReference()
        row['ClientOrderNumber'] = self.getClientOrderNumber()
        contact_uid =\
            self.getContact().UID() if self.getContact() else None
        row['Contact'] = contact_uid
        # row['DateSampled'] = convert_date_string(row['DateSampled'])
        if row['Sampler']:
            row['Sampler'] = lookup_sampler_uid(row['Sampler'])
        # Creating analysis request from gathered data
        ar = create_analysisrequest(
            client,
            self.REQUEST,
            row,
            analyses=list(newanalyses),
            partitions=None,)

        # Container is special... it could be a containertype.
        container = self.get_row_container(row)
        if container:
            if container.portal_type == 'ContainerType':
                containers = container.getContainers()
            # TODO: Since containers don't work as is expected they
            # should work, I am keeping the old logic for AR import...
            part = ar.getPartitions()[0]
            # XXX And so we must calculate the best container for this partition
            part.edit(Container=containers[0])

        # progress marker update
        progress_index = float(row_cnt) / len(gridrows) * 100
        progress = ProgressState(self.REQUEST, progress_index)
        notify(UpdateProgressEvent(progress))

    # document has been written to, and redirect() fails here
    self.REQUEST.response.write(
        '<script>document.location.href="%s"</script>' % (
            self.absolute_url()))


def lookup_sampler_uid(import_user):
    # Lookup sampler's uid
    found = False
    userid = None
    user_ids = []
    portal = ploneapi.portal.get()
    users = getUsers(portal, ['LabManager', 'Sampler']).items()
    for (samplerid, samplername) in users:
        if import_user == samplerid:
            found = True
            userid = samplerid
            break
        if import_user == samplername:
            user_ids.append(samplerid)
    if found:
        return userid
    if len(user_ids) == 1:
        return user_ids[0]
    if len(user_ids) > 1:
        # raise ValueError('Sampler %s is ambiguous' % import_user)
        return ''
    # Otherwise
    # raise ValueError('Sampler %s not found' % import_user)
    return ''
