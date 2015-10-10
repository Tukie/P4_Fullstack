#!/usr/bin/env python

"""
main.py -- Udacity conference server-side Python App Engine
    HTTP controller handlers for memcache & task queue access

$Id$

created by wesc on 2014 may 24
Based on Udacity Building a Scalable App complete Solution Code

Author: Yongkie Wiyogo
date: 2015-10-10
"""

import webapp2
from google.appengine.api import app_identity
from google.appengine.api import mail
from google.appengine.ext import webapp
from conference import ConferenceApi

__author__ = 'Yongkie Wiyogo'


class SetAnnouncementHandler(webapp2.RequestHandler):
    def get(self):
        """Set Announcement in Memcache."""
        ConferenceApi._cacheAnnouncement()
        self.response.set_status(204)


class SendConfirmationEmailHandler(webapp2.RequestHandler):
    def post(self):
        """Send email confirming Conference creation."""
        mail.send_mail(
            'noreply@%s.appspotmail.com' % (
                app_identity.get_application_id()),     # from
            self.request.get('email'),                  # to
            'You created a new Conference!',            # subj
            'Hi, you have created a following '         # body
            'conference:\r\n\r\n%s' % self.request.get(
                'conferenceInfo')
        )


class GetFeaturedSpeaker(webapp2.RequestHandler):
    def post(self):
        """Safe feature speaker"""
        # the request properties are defined in _checkFeaturedSpeaker
        conference_key = self.request.get('conf_urlsafekey')
        sp_name = self.request.get('speaker_name')
        sp_prof = self.request.get('speaker_prof')
        ConferenceApi._checkFeaturedSpeaker(conference_key, sp_name, sp_prof)
        self.response.set_status(204)


app = webapp2.WSGIApplication([
    ('/crons/set_announcement', SetAnnouncementHandler),
    ('/tasks/send_confirmation_email', SendConfirmationEmailHandler),
    ('/tasks/get_featured_speaker', GetFeaturedSpeaker),
], debug=True)
