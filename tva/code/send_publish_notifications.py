def send_publish_notifications(grade_document_courses=None, evaluation_results_courses=None):
    grade_document_courses = grade_document_courses or []
    evaluation_results_courses = evaluation_results_courses or []

    publish_notifications = defaultdict(lambda: CourseLists(set(), set()))

    for course in evaluation_results_courses:
        # for published courses all contributors and participants get a notification
        if course.can_publish_grades:
            for participant in course.participants.all():
                publish_notifications[participant].evaluation_results_courses.add(course)
            for contribution in course.contributions.all():
                if contribution.contributor:
                    publish_notifications[contribution.contributor].evaluation_results_courses.add(course)
        # if a course was not published notifications are only sent for contributors who can see comments
        elif len(course.textanswer_set) > 0:
            for textanswer in course.textanswer_set:
                if textanswer.contribution.contributor:
                    publish_notifications[textanswer.contribution.contributor].evaluation_results_courses.add(course)
            publish_notifications[course.responsible_contributor].evaluation_results_courses.add(course)
    for course in grade_document_courses:
        # all participants who can download grades get a notification
        for participant in course.participants.all():
            if participant.can_download_grades:
                publish_notifications[participant].grade_document_courses.add(course)

    for user, course_lists in publish_notifications.items():
        EmailTemplate.send_publish_notifications_to_user(
            user,
            grade_document_courses=list(course_lists.grade_document_courses),
            evaluation_results_courses=list(course_lists.evaluation_results_courses)
        )
		