from django.test import TestCase

from evap.evaluation.tools import send_publish_notifications
from evap.evaluation.models import UserProfile, Course, Contribution, TextAnswer

from model_mommy import mommy
from unittest.mock import patch, PropertyMock

class PublishNotificationTests(TestCase):

    @patch('evap.evaluation.tools.EmailTemplate')
    def test_no_courses(self, mockEmailTemplate):
        """ Tests whether sending notifications for no courses results in no notifications being sent. """
        send_publish_notifications()
        self.assertEqual(mockEmailTemplate.send_publish_notifications_to_user.call_count, 0)

    @patch('evap.evaluation.models.Course.can_publish_grades', new_callable=PropertyMock)
    @patch('evap.evaluation.tools.EmailTemplate')
    def test_course_with_results(self, mockEmailTemplate, can_publish_grades):
        """ Tests whether a course with results sends a notification to its participants and contributors. """

        can_publish_grades.return_value = True

        student = mommy.make(UserProfile, email="student@student.hpi.de")
        course1 = mommy.make(Course, participants=[student], state="published")
        course2 = mommy.make(Course, participants=[student], state="published")
        general_contribution = Contribution(course=course1, contributor=None)
        general_contribution.save()
        general_contribution = Contribution(course=course2, contributor=None)
        general_contribution.save()
        contributor = mommy.make(UserProfile, email="contributor@hpi.de")
        contribution = Contribution(course=course1, contributor=contributor)
        contribution.save()
        contribution = Contribution(course=course2, contributor=contributor)
        contribution.save()

        send_publish_notifications(evaluation_results_courses = [course1, course2])
        self.assertEqual(mockEmailTemplate.send_publish_notifications_to_user.call_count, 2)

    @patch('evap.evaluation.models.Course.can_publish_grades', new_callable=PropertyMock)
    @patch('evap.evaluation.tools.EmailTemplate')
    def test_course_with_textanswers(self, mockEmailTemplate, can_publish_grades):
        """ Tests whether a course with results sends a notification to its contributors. """

        can_publish_grades.return_value = False

        course = mommy.make(Course, state="reviewed")
        contributor = mommy.make(UserProfile, email="contributor@hpi.de")
        general_contribution = Contribution(course=course, contributor=None)
        general_contribution.save()
        mommy.make(TextAnswer, contribution__course=course, contribution=general_contribution)
        contribution1 = Contribution(course=course, contributor=contributor)
        contribution1.save()
        mommy.make(TextAnswer, contribution__course=course, contribution=contribution1)
        responsible = mommy.make(UserProfile, email="responsible@hpi.de")
        contribution2 = Contribution(course=course, contributor=responsible, responsible=True)
        contribution2.save()

        send_publish_notifications(evaluation_results_courses = [course])
        self.assertEqual(mockEmailTemplate.send_publish_notifications_to_user.call_count, 2)

    @patch('evap.evaluation.models.Course.can_publish_grades', new_callable=PropertyMock)
    @patch('evap.evaluation.tools.EmailTemplate')
    def test_course_without_results(self, mockEmailTemplate, can_publish_grades):
        """ Tests whether a course without results sends a notification. """

        can_publish_grades.return_value = False

        student = mommy.make(UserProfile, email="student@student.hpi.de")
        course = mommy.make(Course, participants=[student], state="published")
        contributor = mommy.make(UserProfile, email="contributor@hpi.de")
        contribution1 = Contribution(course=course, contributor=contributor)
        contribution1.save()
        responsible = mommy.make(UserProfile, email="responsible@hpi.de")
        contribution2 = Contribution(course=course, contributor=responsible, responsible=True)
        contribution2.save()

        send_publish_notifications(evaluation_results_courses = [course])
        mockEmailTemplate.send_publish_notifications_to_user.assert_not_called()
        self.assertEqual(mockEmailTemplate.send_publish_notifications_to_user.call_count, 0)

    @patch('evap.evaluation.tools.EmailTemplate')
    def test_course_with_documents(self, mockEmailTemplate):
        """ Tests whether a course with grade documents sends a notification to its participants. """

        student = mommy.make(UserProfile, email="student@student.hpi.de")
        course = mommy.make(Course, participants=[student], state="published")

        send_publish_notifications(grade_document_courses = [course])
        self.assertEqual(mockEmailTemplate.send_publish_notifications_to_user.call_count, 1)

    @patch('evap.evaluation.tools.EmailTemplate')
    def test_course_with_documents_external_participant(self, mockEmailTemplate):
        """ Tests whether a course with grade documents sends a notification to participants that are not allowed to download grade documents. """

        student = mommy.make(UserProfile, email="student@student.nothpi.de")
        course = mommy.make(Course, participants=[student], state="published")

        send_publish_notifications(grade_document_courses = [course])
        self.assertEqual(mockEmailTemplate.send_publish_notifications_to_user.call_count, 0)
