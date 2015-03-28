from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Max
from django.forms.models import inlineformset_factory, modelformset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import ugettext as _
from django.http import HttpResponse, HttpResponseRedirect
from django.core.urlresolvers import reverse

from evap.evaluation.auth import staff_required
from evap.evaluation.models import Contribution, Course, Question, Questionnaire, Semester, \
                                   TextAnswer, UserProfile, FaqSection, FaqQuestion, EmailTemplate
from evap.evaluation.tools import STATES_ORDERED, user_publish_notifications, questionnaires_and_contributions, \
                                  get_filtered_answers, CommentSection, TextResult
from evap.staff.forms import ContributionForm, AtLeastOneFormSet, CourseForm, CourseEmailForm, EmailTemplateForm, \
                             IdLessQuestionFormSet, ImportForm, LotteryForm, QuestionForm, QuestionnaireForm, \
                             QuestionnairesAssignForm, SemesterForm, UserForm, ContributionFormSet, FaqSectionForm, \
                             FaqQuestionForm, UserImportForm, TextAnswerForm
from evap.staff.importers import EnrollmentImporter, UserImporter
from evap.staff.tools import custom_redirect
from evap.student.views import vote_preview
from evap.student.forms import QuestionsForm

from evap.rewards.tools import is_semester_activated

import random, datetime, ast

def raise_permission_denied_if_archived(archiveable):
    if archiveable.is_archived:
        raise PermissionDenied


@staff_required
def index(request):
    template_data = dict(semesters=Semester.objects.all(),
                         questionnaires_courses=Questionnaire.objects.filter(obsolete=False,is_for_contributors=False),
                         questionnaire_contributors=Questionnaire.objects.filter(obsolete=False,is_for_contributors=True),
                         templates=EmailTemplate.objects.all(),
                         sections=FaqSection.objects.all(),
                         disable_breadcrumb_staff=True)
    return render(request, "staff_index.html", template_data)


@staff_required
def semester_view(request, semester_id):
    semester = get_object_or_404(Semester, id=semester_id)
    rewards_active = is_semester_activated(semester)
    courses = semester.course_set.all()
    courses_by_state = []
    for state in STATES_ORDERED.keys():
        this_courses = [course for course in courses if course.state == state]
        courses_by_state.append((state, this_courses))

    # semester statistics
    num_enrollments_in_evaluation = 0
    num_votes = 0
    num_courses_evaluated = 0
    num_comments = 0
    num_comments_reviewed = 0
    first_start = datetime.date(9999, 1, 1)
    last_end = datetime.date(2000, 1, 1)
    for course in courses:
        if course.state in ['inEvaluation', 'evaluated', 'reviewed', 'published']:
            num_enrollments_in_evaluation += course.num_participants
        if course.state in ['evaluated', 'reviewed', 'published']:
            num_courses_evaluated += 1
        num_votes += course.num_voters
        first_start = min(first_start, course.vote_start_date)
        last_end = max(last_end, course.vote_end_date)
        num_comments += len(course.textanswer_set)
        num_comments_reviewed += len(course.reviewed_textanswer_set)

    template_data = dict(
        semester=semester, 
        courses_by_state=courses_by_state, 
        disable_breadcrumb_semester=True,
        disable_if_archived="disabled=disabled" if semester.is_archived else "",
        rewards_active=rewards_active,
        num_enrollments_in_evaluation=num_enrollments_in_evaluation,
        num_votes=num_votes,
        first_start=first_start,
        last_end=last_end,
        num_courses=len(courses),
        num_courses_evaluated=num_courses_evaluated,
        num_comments=num_comments,
        num_comments_reviewed=num_comments_reviewed,
    )
    return render(request, "staff_semester_view.html", template_data)


@staff_required
def semester_course_operation(request, semester_id):
    semester = get_object_or_404(Semester, id=semester_id)
    raise_permission_denied_if_archived(semester)

    course_ids = request.GET.getlist('course')
    operation = request.GET.get('operation')
    if operation not in ['revertToNew', 'prepare', 'reenableLecturerReview', 'approve', 'publish']:
        messages.error(request, _("Unsupported operation: ") + str(operation))
        return custom_redirect('evap.staff.views.semester_view', semester_id)
    courses = [get_object_or_404(Course, id=course_id) for course_id in course_ids]

    if request.method == 'POST':        
        if operation == 'revertToNew':
            for course in courses:
                course.revert_to_new()
                course.save()
            messages.success(request, _("Successfully reverted %d courses to new.") % (len(courses)))
        
        elif operation == 'prepare' or operation == 'reenableLecturerReview':
            for course in courses:
                course.ready_for_contributors()
                course.save()
            messages.success(request, _("Successfully enabled %d courses for lecturer review.") % (len(courses)))
            try:
                EmailTemplate.get_review_template().send_to_users_in_courses(courses, ['editors'])
            except Exception:
                messages.error(request, _("An error occured when sending the notification emails to the lecturers."))

        elif operation == 'approve':
            for course in courses:
                course.staff_approve()
                course.save()
            messages.success(request, _("Successfully approved %d courses.") % (len(courses)))

        elif operation == 'publish':
            for course in courses:
                course.publish()
                course.save()
            messages.success(request, _("Successfully published %d courses.") % (len(courses)))
            for user, user_courses in user_publish_notifications(courses).items():
                try:
                    EmailTemplate.get_publish_template().send_to_user(user, courses=list(user_courses))
                except Exception:
                    messages.error(request, _("An error occured when sending the notification email to %s.") % user.username)
        return custom_redirect('evap.staff.views.semester_view', semester_id)

    if not courses:
        messages.warning(request, _("Please select at least one course."))
        return custom_redirect('evap.staff.views.semester_view', semester_id)

    current_state_name = STATES_ORDERED[courses[0].state]
    if operation == 'revertToNew':
        new_state_name = STATES_ORDERED['new']
    elif operation == 'prepare' or operation == 'reenableLecturerReview':
        new_state_name = STATES_ORDERED['prepared']
    elif operation == 'approve':
        new_state_name = STATES_ORDERED['approved']
    elif operation == 'publish':
        new_state_name = STATES_ORDERED['published']

    template_data = dict(
        semester=semester,
        courses=courses,
        course_ids=course_ids,
        operation=operation,
        current_state_name=current_state_name,
        new_state_name=new_state_name,
    )
    return render(request, "staff_course_operation.html", template_data)


@staff_required
def semester_create(request):
    form = SemesterForm(request.POST or None)

    if form.is_valid():
        semester = form.save()

        messages.success(request, _("Successfully created semester."))
        return redirect('evap.staff.views.semester_view', semester.id)
    else:
        return render(request, "staff_semester_form.html", dict(form=form))


@staff_required
def semester_edit(request, semester_id):
    semester = get_object_or_404(Semester, id=semester_id)
    form = SemesterForm(request.POST or None, instance=semester)

    if form.is_valid():
        semester = form.save()

        messages.success(request, _("Successfully updated semester."))
        return redirect('evap.staff.views.semester_view', semester.id)
    else:
        return render(request, "staff_semester_form.html", dict(semester=semester, form=form))


@staff_required
def semester_delete(request, semester_id):
    semester = get_object_or_404(Semester, id=semester_id)

    if semester.can_staff_delete:
        if request.method == 'POST':
            semester.delete()
            messages.success(request, _("Successfully deleted semester."))
            return redirect('staff_root')
        else:
            return render(request, "staff_semester_delete.html", dict(semester=semester))
    else:
        messages.warning(request, _("The semester '%s' cannot be deleted, because it is still in use.") % semester.name)
        return redirect('evap.staff.views.semester_view', semester.id)


@staff_required
def semester_import(request, semester_id):
    semester = get_object_or_404(Semester, id=semester_id)
    raise_permission_denied_if_archived(semester)

    form = ImportForm(request.POST or None, request.FILES or None)

    if form.is_valid():
        operation = request.POST.get('operation')
        if operation not in ('test', 'import'):
            raise PermissionDenied

        # extract data from form
        excel_file = form.cleaned_data['excel_file']
        vote_start_date = form.cleaned_data['vote_start_date']
        vote_end_date = form.cleaned_data['vote_end_date']

        test_run = operation == 'test'

        # parse table
        EnrollmentImporter.process(request, excel_file, semester, vote_start_date, vote_end_date, test_run)
        if test_run:
            return render(request, "staff_import.html", dict(semester=semester, form=form))
        return redirect('evap.staff.views.semester_view', semester_id)
    else:
        return render(request, "staff_import.html", dict(semester=semester, form=form))


@staff_required
def semester_assign_questionnaires(request, semester_id):
    semester = get_object_or_404(Semester, id=semester_id)
    raise_permission_denied_if_archived(semester)
    courses = semester.course_set.filter(state='new')
    kinds = courses.values_list('kind', flat=True).order_by().distinct()
    form = QuestionnairesAssignForm(request.POST or None, semester=semester, kinds=kinds)

    if form.is_valid():
        for course in courses:
            if form.cleaned_data[course.kind]:
                course.general_contribution.questionnaires = form.cleaned_data[course.kind]
            if form.cleaned_data['Responsible contributor']:
                course.contributions.get(responsible=True).questionnaires = form.cleaned_data['Responsible contributor']
            course.save()

        messages.success(request, _("Successfully assigned questionnaires."))
        return redirect('evap.staff.views.semester_view', semester_id)
    else:
        return render(request, "staff_semester_assign_questionnaires.html", dict(semester=semester, form=form))


@staff_required
def semester_lottery(request, semester_id):
    semester = get_object_or_404(Semester, id=semester_id)

    form = LotteryForm(request.POST or None)

    if form.is_valid():
        eligible = []

        # find all users who have voted on all of their courses
        for user in UserProfile.objects.all():
            courses = user.course_set.filter(semester=semester,  state__in=['inEvaluation', 'evaluated', 'reviewed', 'published'])
            if not courses.exists():
                # user was not participating in any course in this semester
                continue
            if not courses.exclude(voters=user).exists():
                eligible.append(user)

        winners = random.sample(eligible, min([form.cleaned_data['number_of_winners'], len(eligible)]))
    else:
        eligible = None
        winners = None

    template_data =dict(semester=semester, form=form, eligible=eligible, winners=winners)
    return render(request, "staff_semester_lottery.html", template_data)

@staff_required
def semester_todo(request, semester_id):
    semester = get_object_or_404(Semester, id=semester_id)

    courses = semester.course_set.filter(state__in=['prepared', 'lecturerApproved']).all()

    prepared_courses = semester.course_set.filter(state__in=['prepared']).all()
    responsibles = (course.responsible_contributor for course in prepared_courses)
    responsibles = list(set(responsibles))
    responsibles.sort(key = lambda responsible: (responsible.last_name, responsible.first_name))

    responsible_list = [(responsible, [course for course in courses if course.responsible_contributor.id == responsible.id], responsible.delegates.all()) for responsible in responsibles]

    template_data = dict(semester=semester, responsible_list=responsible_list)
    return render(request, "staff_semester_todo.html", template_data)

@staff_required
def semester_archive(request, semester_id):
    semester = get_object_or_404(Semester, id=semester_id)

    if semester.is_archiveable:
        if request.method == 'POST':
            semester.archive()
            messages.success(request, _("Successfully archived semester '{}'.").format(semester.name))
            return redirect('evap.staff.views.semester_view', semester.id)
        else:
            return render(request, "staff_semester_archive.html", dict(semester=semester))
    else:
        messages.warning(request, _("The semester '%s' cannot be archived, "+
            "because it already is archived or has courses that are not archiveable.") % semester.name)
        return redirect('evap.staff.views.semester_view', semester.id)


@staff_required
def course_create(request, semester_id):
    semester = get_object_or_404(Semester, id=semester_id)
    raise_permission_denied_if_archived(semester)

    course = Course(semester=semester)
    InlineContributionFormset = inlineformset_factory(Course, Contribution, formset=ContributionFormSet, form=ContributionForm, extra=1, exclude=('course',))

    form = CourseForm(request.POST or None, instance=course)
    formset = InlineContributionFormset(request.POST or None, instance=course)

    if form.is_valid() and formset.is_valid():
        form.save(user=request.user)
        formset.save()

        messages.success(request, _("Successfully created course."))
        return redirect('evap.staff.views.semester_view', semester_id)
    else:
        return render(request, "staff_course_form.html", dict(semester=semester, form=form, formset=formset, staff=True))


@staff_required
def course_edit(request, semester_id, course_id):
    semester = get_object_or_404(Semester, id=semester_id)
    course = get_object_or_404(Course, id=course_id)
    raise_permission_denied_if_archived(course)
    InlineContributionFormset = inlineformset_factory(Course, Contribution, formset=ContributionFormSet, form=ContributionForm, extra=1, exclude=('course',))

    # check course state
    if not course.can_staff_edit:
        messages.warning(request, _("Editing not possible in current state."))
        return redirect('evap.staff.views.semester_view', semester_id)

    form = CourseForm(request.POST or None, instance=course)
    formset = InlineContributionFormset(request.POST or None, instance=course, queryset=course.contributions.exclude(contributor=None))

    if form.is_valid() and formset.is_valid():
        if course.state in ['evaluated', 'reviewed'] and course.is_in_evaluation_period:
            course.reopen_evaluation()
        form.save(user=request.user)
        formset.save()

        messages.success(request, _("Successfully updated course."))
        return custom_redirect('evap.staff.views.semester_view', semester_id)
    else:
        template_data = dict(semester=semester, course=course, form=form, formset=formset, staff=True)
        return render(request, "staff_course_form.html", template_data)


@staff_required
def course_delete(request, semester_id, course_id):
    semester = get_object_or_404(Semester, id=semester_id)
    course = get_object_or_404(Course, id=course_id)
    raise_permission_denied_if_archived(course)

    # check course state
    if not course.can_staff_delete:
        messages.warning(request, _("The course '%s' cannot be deleted, because it is still in use.") % course.name)
        return redirect('evap.staff.views.semester_view', semester_id)

    if request.method == 'POST':
        course.delete()
        messages.success(request, _("Successfully deleted course."))
        return custom_redirect('evap.staff.views.semester_view', semester_id)
    else:
        return render(request, "staff_course_delete.html", dict(semester=semester, course=course))


@staff_required
def course_email(request, semester_id, course_id):
    semester = get_object_or_404(Semester, id=semester_id)
    course = get_object_or_404(Course, id=course_id)
    form = CourseEmailForm(request.POST or None, instance=course)

    if form.is_valid():
        form.send()

        if form.all_recepients_reachable():
            messages.success(request, _("Successfully sent emails for '%s'.") % course.name)
        else:
            messages.warning(request, _("Successfully sent some emails for '{course}', but {count} could not be reached as they do not have an email address.").format(course=course.name, count=form.missing_email_addresses()))
        return custom_redirect('evap.staff.views.semester_view', semester_id)
    else:
        return render(request, "staff_course_email.html", dict(semester=semester, course=course, form=form))


@staff_required
def course_unpublish(request, semester_id, course_id):
    semester = get_object_or_404(Semester, id=semester_id)
    course = get_object_or_404(Course, id=course_id)
    raise_permission_denied_if_archived(course)

    # check course state
    if not course.state == "published":
        messages.warning(request, _("The course '%s' cannot be unpublished, because it is not published.") % course.name)
        return custom_redirect('evap.staff.views.semester_view', semester_id)

    if request.method == 'POST':
        course.revoke()
        course.save()
        return custom_redirect('evap.staff.views.semester_view', semester_id)
    else:
        return render(request, "staff_course_unpublish.html", dict(semester=semester, course=course))


@staff_required
def course_comments(request, semester_id, course_id):
    semester = get_object_or_404(Semester, id=semester_id)
    course = get_object_or_404(Course, id=course_id)
    
    filter = request.GET.get('filter', None)
    if filter == None: # if no parameter is given take session value
        filter = request.session.get('filter_comments', False) # defaults to False if no session value exists
    else:
        filter = {'true': True, 'false': False}.get(filter.lower()) # convert parameter to boolean
    request.session['filter_comments'] = filter # store value for session

    exclude_states = []
    if filter:
        exclude_states = [TextAnswer.PUBLISHED, TextAnswer.PRIVATE, TextAnswer.HIDDEN]

    course_sections = []
    contributor_sections = []
    for questionnaire, contribution in questionnaires_and_contributions(course):
        text_results = []
        for question in questionnaire.question_set.all():
            if question.is_text_question:
                answers = get_filtered_answers(course, contribution, question, exclude_text_answer_states=exclude_states)
                if answers:
                    text_results.append(TextResult(question=question, answers=answers))
        if not text_results:
            continue
        if contribution.is_general:
            course_sections.append(CommentSection(questionnaire, contribution.contributor, False, text_results))
        else:
            contributor_sections.append(CommentSection(questionnaire, contribution.contributor, contribution.responsible, text_results))

    template_data = dict(semester=semester, course=course, course_sections=course_sections, contributor_sections=contributor_sections, filter=filter)
    return render(request, "staff_course_comments.html", template_data)


@staff_required
def course_comments_update_publish(request):
    comment_id = request.POST["id"]
    action = request.POST["action"]
    course_id = request.POST["course_id"]

    course = Course.objects.get(pk=course_id)
    answer = TextAnswer.objects.get(pk=comment_id)

    if action == 'publish':
        answer.publish()
    elif action == 'make_private':
        answer.make_private()
    elif action == 'hide':
        answer.hide()
    elif action == 'unreview':
        answer.unreview()
    else:
        return HttpResponse(status=400) # 400 Bad Request
    answer.save()

    if course.state == "evaluated" and course.is_fully_reviewed():
        course.review_finished()
        course.save()
    if course.state == "reviewed" and not course.is_fully_reviewed():
        course.reopen_review()
        course.save()

    return HttpResponse() # 200 OK


@staff_required
def course_comment_edit(request, semester_id, course_id, text_answer_id):
    text_answer = get_object_or_404(TextAnswer, id=text_answer_id)
    semester = get_object_or_404(Semester, id=semester_id)
    course = get_object_or_404(Course, id=course_id)
    reviewed_answer = text_answer.reviewed_answer
    if reviewed_answer == None:
        reviewed_answer = text_answer.original_answer
    form = TextAnswerForm(request.POST or None, instance=text_answer, initial={'reviewed_answer': reviewed_answer})

    if form.is_valid():
        form.save()
        # jump to edited answer
        url = reverse('evap.staff.views.course_comments', args=[semester_id, course_id]) + '#' + str(text_answer.id)
        return HttpResponseRedirect(url)
    
    template_data = dict(semester=semester, course=course, form=form, text_answer=text_answer)
    return render(request, "staff_course_comment_edit.html", template_data)


@staff_required
def course_preview(request, semester_id, course_id):
    semester = get_object_or_404(Semester, id=semester_id)
    course = get_object_or_404(Course, id=course_id)

    return vote_preview(request, course)


@staff_required
def questionnaire_index(request):
    questionnaires = Questionnaire.objects.all()
    course_questionnaires = questionnaires.filter(is_for_contributors=False)
    contributor_questionnaires = questionnaires.filter(is_for_contributors=True)
    template_data = dict(course_questionnaires=course_questionnaires, contributor_questionnaires=contributor_questionnaires)
    return render(request, "staff_questionnaire_index.html", template_data)


@staff_required
def questionnaire_view(request, questionnaire_id):
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)

    # build forms
    contribution = Contribution(contributor=request.user)
    form = QuestionsForm(request.POST or None, contribution=contribution, questionnaire=questionnaire)

    return render(request, "staff_questionnaire_view.html", dict(forms=[form], questionnaire=questionnaire))


@staff_required
def questionnaire_create(request):
    questionnaire = Questionnaire()
    InlineQuestionFormset = inlineformset_factory(Questionnaire, Question, formset=AtLeastOneFormSet, form=QuestionForm, extra=1, exclude=('questionnaire',))

    form = QuestionnaireForm(request.POST or None, instance=questionnaire)
    formset = InlineQuestionFormset(request.POST or None, instance=questionnaire)

    if form.is_valid() and formset.is_valid():
        newQuestionnaire = form.save(commit=False)
        # set index according to existing questionnaires
        newQuestionnaire.index = Questionnaire.objects.all().aggregate(Max('index'))['index__max'] + 1
        newQuestionnaire.save()
        form.save_m2m()

        formset.save()

        messages.success(request, _("Successfully created questionnaire."))
        return redirect('evap.staff.views.questionnaire_index')
    else:
        return render(request, "staff_questionnaire_form.html", dict(form=form, formset=formset))


@staff_required
def questionnaire_edit(request, questionnaire_id):
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)
    InlineQuestionFormset = inlineformset_factory(Questionnaire, Question, formset=AtLeastOneFormSet, form=QuestionForm, extra=1, exclude=('questionnaire',))

    form = QuestionnaireForm(request.POST or None, instance=questionnaire)
    formset = InlineQuestionFormset(request.POST or None, instance=questionnaire)

    if not questionnaire.can_staff_edit:
        messages.info(request, _("Questionnaires that are already used cannot be edited."))
        return redirect('evap.staff.views.questionnaire_index')

    if form.is_valid() and formset.is_valid():
        form.save()
        formset.save()

        messages.success(request, _("Successfully updated questionnaire."))
        return redirect('evap.staff.views.questionnaire_index')
    else:
        template_data = dict(questionnaire=questionnaire, form=form, formset=formset)
        return render(request, "staff_questionnaire_form.html", template_data)


@staff_required
def questionnaire_copy(request, questionnaire_id):
    if request.method == "POST":
        questionnaire = Questionnaire()
        InlineQuestionFormset = inlineformset_factory(Questionnaire, Question, formset=AtLeastOneFormSet, form=QuestionForm, extra=1, exclude=('questionnaire',))

        form = QuestionnaireForm(request.POST, instance=questionnaire)
        formset = InlineQuestionFormset(request.POST.copy(), instance=questionnaire, save_as_new=True)

        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()

            messages.success(request, _("Successfully created questionnaire."))
            return redirect('evap.staff.views.questionnaire_index')
        else:
            return render(request, "staff_questionnaire_form.html", dict(form=form, formset=formset))
    else:
        questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)
        InlineQuestionFormset = inlineformset_factory(Questionnaire, Question, formset=IdLessQuestionFormSet, form=QuestionForm, extra=1, exclude=('questionnaire',))

        form = QuestionnaireForm(instance=questionnaire)
        formset = InlineQuestionFormset(instance=Questionnaire(), queryset=questionnaire.question_set.all())

        return render(request, "staff_questionnaire_form.html", dict(form=form, formset=formset))


@staff_required
def questionnaire_delete(request, questionnaire_id):
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)

    if questionnaire.can_staff_delete:
        if request.method == 'POST':
            questionnaire.delete()
            messages.success(request, _("Successfully deleted questionnaire."))
            return redirect('evap.staff.views.questionnaire_index')
        else:
            return render(request, "staff_questionnaire_delete.html", dict(questionnaire=questionnaire))
    else:
        messages.warning(request, _("The questionnaire '%s' cannot be deleted, because it is still in use.") % questionnaire.name)
        return redirect('evap.staff.views.questionnaire_index')


@staff_required
def questionnaire_update_indices(request):
    updated_indices = request.POST
    for questionnaire_id, new_index in updated_indices.items():
        questionnaire = Questionnaire.objects.get(pk=questionnaire_id)
        questionnaire.index = new_index
        questionnaire.save()
    return HttpResponse()


@staff_required
def user_index(request):
    users = UserProfile.objects.order_by("last_name", "first_name", "username").prefetch_related('contributions', 'groups', 'course_set')

    return render(request, "staff_user_index.html", dict(users=users))


@staff_required
def user_create(request):
    form = UserForm(request.POST or None, instance=UserProfile())

    if form.is_valid():
        form.save()
        messages.success(request, _("Successfully created user."))
        return redirect('evap.staff.views.user_index')
    else:
        return render(request, "staff_user_form.html", dict(form=form))


@staff_required
def user_import(request):
    form = UserImportForm(request.POST or None, request.FILES or None)
    operation = request.POST.get('operation')

    if form.is_valid():
        if operation not in ('test', 'import'):
            raise PermissionDenied

        test_run = operation == 'test'
        excel_file = form.cleaned_data['excel_file']
        UserImporter.process(request, excel_file, test_run)
        if test_run:
            return render(request, "staff_user_import.html", dict(form=form))
        return redirect('evap.staff.views.user_index')       
    else:
        return render(request, "staff_user_import.html", dict(form=form))


@staff_required
def user_edit(request, user_id):
    user = get_object_or_404(UserProfile, id=user_id)
    form = UserForm(request.POST or None, request.FILES or None, instance=user)

    courses_contributing_to = Course.objects.filter(semester=Semester.active_semester, contributions__contributor=user)

    if form.is_valid():
        form.save()
        messages.success(request, _("Successfully updated user."))
        return redirect('evap.staff.views.user_index')
    else:
        return render(request, "staff_user_form.html", dict(form=form, object=user, courses_contributing_to=courses_contributing_to))


@staff_required
def user_delete(request, user_id):
    user = get_object_or_404(UserProfile, id=user_id)

    if user.can_staff_delete:
        if request.method == 'POST':
            user.delete()
            messages.success(request, _("Successfully deleted user."))
            return redirect('evap.staff.views.user_index')
        else:
            return render(request, "staff_user_delete.html", dict(user_to_delete=user))
    else:
        messages.warning(request, _("The user '%s' cannot be deleted, because he lectures courses.") % user.full_name)
        return redirect('evap.staff.views.user_index')


@staff_required
def template_edit(request, template_id):
    template = get_object_or_404(EmailTemplate, id=template_id)
    form = EmailTemplateForm(request.POST or None, request.FILES or None, instance=template)

    if form.is_valid():
        form.save()

        messages.success(request, _("Successfully updated template."))
        return redirect('staff_root')
    else:
        return render(request, "staff_template_form.html", dict(form=form, template=template))


@staff_required
def faq_index(request):
    sections = FaqSection.objects.all()

    sectionFS = modelformset_factory(FaqSection, form=FaqSectionForm, can_order=False, can_delete=True, extra=1)
    formset = sectionFS(request.POST or None, queryset=sections)

    if formset.is_valid():
        formset.save()

        messages.success(request, _("Successfully updated the FAQ sections."))
        return custom_redirect('evap.staff.views.faq_index')
    else:
        return render(request, "staff_faq_index.html", dict(formset=formset, sections=sections))


@staff_required
def faq_section(request, section_id):
    section = get_object_or_404(FaqSection, id=section_id)
    questions = FaqQuestion.objects.filter(section=section)

    InlineQuestionFormset = inlineformset_factory(FaqSection, FaqQuestion, form=FaqQuestionForm, can_order=False, can_delete=True, extra=1, exclude=('section',))
    formset = InlineQuestionFormset(request.POST or None, queryset=questions, instance=section)

    if formset.is_valid():
        formset.save()

        messages.success(request, _("Successfully updated the FAQ questions."))
        return custom_redirect('evap.staff.views.faq_index')
    else:
        template_data = dict(formset=formset, section=section, questions=questions)
        return render(request, "staff_faq_section.html", template_data)
