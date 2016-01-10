@transition(field=state, source=['new', 'editorApproved'], target='prepared')
    def ready_for_editors(self):
        pass

@transition(field=state, source='prepared', target='editorApproved')
def editor_approve(self):
    pass

@transition(field=state, source=['new', 'prepared', 'editorApproved'], target='approved', conditions=[has_enough_questionnaires])
def staff_approve(self):
    pass
