def __call__(self, context, mode, field, default):
    """ monkey patching this function as per issue
    https://jira.bikalabs.com/browse/AN-182 so that Sampler can be 
    shown on AR Create
    """
    fields = ['SamplingDate']
    state = default if default else 'invisible'
    fieldName = field.getName()
    if fieldName not in fields:
        return state

    # If object has been already created, get SWF statues from it.
    if hasattr(self.context, 'getSamplingWorkflowEnabled') and \
            context.getSamplingWorkflowEnabled() is not '':
        swf_enabled = context.getSamplingWorkflowEnabled()
    else:
        swf_enabled = context.bika_setup.getSamplingWorkflowEnabled()

    # If SWF Enabled, we mostly use the dictionary from the Field, but:
    # - DateSampled: invisible during creation.
    # - SamplingDate and Sampler: visible and editable until sample due.
    if swf_enabled:
        if fieldName in fields:
            if mode == 'header_table':
                state = 'prominent'
            elif mode == 'view':
                state = 'visible'
    # If SamplingWorkflow is Disabled:
    #  - DateSampled: visible,
    #                 not editable after creation (appears in header_table),
    #                 required in 'add' view.
    #  - 'SamplingDate' and 'Sampler': disabled everywhere.
    else:
        if fieldName in fields:
            state = 'invisible'
    return state
