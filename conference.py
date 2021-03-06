#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints
Based on Udacity Building a Scalable App complete Solution Code
created by wesc on 2014 apr 21

Author: Yongkie Wiyogo
date: 2015-10-10
"""

from datetime import datetime
import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from models import ConflictException, Profile, ProfileMiniForm, ProfileForm
from models import StringMessage, BooleanMessage
from models import Conference, ConferenceForm, ConferenceForms
from models import ConferenceQueryForm, ConferenceQueryForms, TeeShirtSize
from models import Session, SessionForm, SessionForms
from models import Speaker, SpeakerForm, SpeakerForms
from models import WishList, WishListForm, WishListForms

from settings import WEB_CLIENT_ID, ANDROID_CLIENT_ID, IOS_CLIENT_ID
from settings import ANDROID_AUDIENCE
from utils import getUserId

__author__ = 'Yongkie Wiyogo'

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
ANNOUNCEMENT_TPL = ('Last chance to attend! The following conferences '
                    'are nearly sold out: %s')
MEMCACHE_FEATURED_SPEAKER = "FEATURED_SPEAKER"
FEATURED_SPEAKER_TPL = ('Featured speaker of this conference is %s. His/her session names are %s')
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [ "Default", "Topic" ],
}

SESSION_DEFAULTS = {
    "duration": 0,
    "typeOfSession": "NOT_SPECIFIED"
}

OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
            }

FIELDS ={
        'CITY': 'city',
        'TOPIC': 'topics',
        'MONTH': 'month',
        'MAX_ATTENDEES': 'maxAttendees',
        }

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1)
)

SESSION_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1)
)

SESSION_GET_REQUEST_BY_TYPE = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    typeOfSession=messages.StringField(2)
)
SESSION_GET_REQUEST_BY_SPEAKER = endpoints.ResourceContainer(
    message_types.VoidMessage,
    speakerFullname=messages.StringField(1)
)
SESSION_GET_REQUEST_BY_SPEAKER_TYPE = endpoints.ResourceContainer(
    message_types.VoidMessage,
    speakerFullname=messages.StringField(1),
    typeOfSession=messages.StringField(2)
)
WISHLIST_POST_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    sessionKey=messages.StringField(1),
)


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(name='conference', version='v1', audiences=[ANDROID_AUDIENCE],
               allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID,
                                   ANDROID_CLIENT_ID, IOS_CLIENT_ID],
               scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf


    def _createConferenceObject(self, request):
        """Create or update Conference object, returning ConferenceForm."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (data model&outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings->Date objects;set month basedon start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]

        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID. See Lesson 4
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
                              'conferenceInfo': repr(request)},
                               url='/tasks/send_confirmation_email'
        )
        return request

    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name)
                for field in request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException('No conference found with key: %s'
                                              % request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
            http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)

    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
                      path='conference/{websafeConferenceKey}',
                      http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)

    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='getConferencesCreated',
                      http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, getattr(prof, 'displayName')) for conf in confs]
        )

    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q

    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException("Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous
                # filters disallow the filter if inequality was performed on a
                # different field before track the field on which the inequality
                # operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException(
                        "Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)


    @endpoints.method(ConferenceQueryForms, ConferenceForms,
                      path='queryConferences', http_method='POST',
                      name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [(ndb.Key(Profile, conf.organizerUserId))
                      for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            if profile:
                names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
                items=[self._copyConferenceToForm(conf, names[conf.organizerUserId])
                       for conf in conferences]
        )

# - - - Profile objects - - - - - - - - - - - - - - - - - - -
    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize,
                                                    getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf


    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if
        non-existent."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            profile = Profile(
                key = p_key,
                displayName = user.nickname(),
                mainEmail= user.email(),
                teeShirtSize = str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put()

        return profile      # return Profile

    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
                        #if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        #else:
                        #    setattr(prof, field, val)
                        prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)


    @endpoints.method(message_types.VoidMessage, ProfileForm,
                      path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()


    @endpoints.method(ProfileMiniForm, ProfileForm,
                      path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)


# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5, Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = ANNOUNCEMENT_TPL % (
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement

    @endpoints.method(message_types.VoidMessage, StringMessage,
                      path='conference/announcement/get',
                      http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        return StringMessage(data=memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY) or
                                  "")


# - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser() # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='conferences/attending',
                      http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser() # get user Profile
        conf_keys = [ndb.Key(urlsafe=wsck) for wsck in prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf, names[conf.organizerUserId])\
         for conf in conferences]
        )

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
                      path='conference/{websafeConferenceKey}',
                      http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
                      path='conference/{websafeConferenceKey}',
                      http_method='DELETE', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='filterPlayground',
                      http_method='GET', name='filterPlayground')
    def filterPlayground(self, request):
        """Filter Playground"""
        q = Conference.query()
        # field = "city"
        # operator = "="
        # value = "London"
        # f = ndb.query.FilterNode(field, operator, value)
        # q = q.filter(f)
        q = q.filter(Conference.city=="London")
        q = q.filter(Conference.topics=="Medical Innovations")
        q = q.filter(Conference.month==6)

        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") for conf in q]
        )

# --------- Sessions ---------------
    #@ndb.transactional(xg=True)
    
    def _createSessionObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request.
           A session can only be created by a user who has created a conference"""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        #request object is a SessionForm, see class Session in models.py
        if not request.confwebsafekey:
            raise endpoints.BadRequestException("Session 'confwebsafekey' field required")
        if not request.name:
            raise endpoints.BadRequestException("Session 'name' field required")

        # Get the conference from websafeConferenceKey
        conf = ndb.Key(urlsafe=request.confwebsafekey).get()

        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID. See Lesson 4
        conf_key = conf.key

        #Check for exissting session to avoid double entry
        squery = Session.query(ancestor=conf.key)
        sessions = squery.filter(Session.name == request.name)
        
        if not sessions.get():
            # create a new session if the session name does not exist yet
            sess_id = Session.allocate_ids(size=1, parent=conf_key)[0]
            sess_key = ndb.Key(Session, sess_id, parent=conf_key)

            # copy SessionForm/ProtoRPC Message into dict data
            dict_data = {field.name: getattr(request, field.name) for field in request.all_fields()}
            del dict_data['confwebsafekey']
            dict_data['key'] = sess_key

            # add default values for those missing
            # (both data model & outbound Message)
            for df in SESSION_DEFAULTS:
                if dict_data[df] in (None, []):
                    dict_data[df] = SESSION_DEFAULTS[df]
                    setattr(request, df, SESSION_DEFAULTS[df])
            print "Request date: "
            # Fill date using current date UTC time zone
            # if date is not exist, user can add it later
            if request.date:
                # convert d tes from strings to Date objects and combine with start time
                # remove date and starttime from request SessionForm because Session
                # has only a startDataTime property
                dict_data['date'] = datetime.strptime(request.date, "%Y-%m-%d").date()

            if request.startTime:
                dict_data['startTime'] = datetime.strptime(request.startTime, "%H:%M").time()
            # check for existing speaker before create a new one
            if request.speakerName:
                qspeaker = Speaker.query()
                qspeaker = qspeaker.filter(Speaker.fullname == request.speakerName)
                if not qspeaker.get():
                    # Create speaker. Speaker entity does not have parent
                    # because speakers can give talks in different conferences
                    speaker_id = Speaker.allocate_ids(size=1)[0]
                    speaker_key = ndb.Key(Speaker, speaker_id)
                    speaker_data = {'fullname': request.speakerName, 
                                    'profession': request.speakerProfession}    
                    Speaker(**speaker_data).put()
                    dict_data['speakerKey'] = speaker_key
                else:
                    dict_data['speakerKey'] = qspeaker.get().key
            sp_name = dict_data['speakerName']
            sp_profession = dict_data['speakerProfession']
            del dict_data['speakerName']
            del dict_data['speakerProfession']
            del dict_data['sessionWebsafeKey']
            # Save session data to datastore
            Session(**dict_data).put()

            # Task 4 check for featured speaker call task queue
            # get the existing session and compare to dict_data['speaker']
            taskqueue.add(url='/tasks/get_featured_speaker',
                          params={'conf_urlsafekey': request.confwebsafekey,
                                  'speaker_name': sp_name,
                                  'speaker_prof': sp_profession})
        return request


    def _copySessionToForm(self, session):
        """Copy relevant fields from Session to SessionForm."""
        sform = SessionForm()
        print session
        setattr(sform, 'sessionWebsafeKey', session.key.urlsafe() )
        # get speaker properties
        speaker = getattr(session, 'speakerKey').get()

        if speaker:
            setattr(sform, 'speakerName', str(speaker.fullname) )
            setattr(sform, 'speakerProfession', str(speaker.profession) )
        else:
            setattr(sform, 'speakerName', "None" )
            setattr(sform, 'speakerProfession', "None" )

        for field in sform.all_fields():
            if hasattr(session, field.name):
                if field.name.endswith('date') or field.name.endswith('startTime'):
                    setattr(sform, field.name, str(getattr(session, field.name)))
                elif field.name.endswith('speakerKey'):
                    # extract the name entity to string
                    print "Speaker KEy found"
                    fullname = session.speakerKey.get().fullname
                    profession = session.speakerKey.get().profession
                    setattr(sform, 'speakerName', "Test1234")
                    setattr(sform, 'speakerProfession', str(getattr(session, profession)))
                else:
                    setattr(sform, field.name, getattr(session, field.name))

        sform.check_initialized()
        return sform

    def _copySpeakerToForm(self, speaker):
        """Copy relevant fields from Speaker to SpeakerForm."""
        spform = SpeakerForm()
        for field in spform.all_fields():
            if hasattr(speaker, field.name):
                setattr(spform, field.name, getattr(speaker, field.name))

        spform.check_initialized()
        return spform

    # 1 endpoint
    @endpoints.method(SessionForm, SessionForm, path="session", 
                      http_method='POST', name='createSession'  )
    def createSession(self, request):
        """Create a new session."""
        return self._createSessionObject(request)

    # 2. endpoint
    @endpoints.method(SESSION_GET_REQUEST, SessionForms,
            path='session/getConferenceSessions',
            http_method='GET', name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """ Given a conference, return all sessions"""
        user = endpoints.get_current_user()

        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # create query and its filter
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        squery = Session.query(ancestor=conf.key)

        return SessionForms(
            items=[self._copySessionToForm(session) for session in squery]
        )

    # 3. endpoint
    @endpoints.method(SESSION_GET_REQUEST_BY_TYPE, SessionForms,
            path='session/{websafeConferenceKey}/types',
            http_method='GET', name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
        """ Given a conference, return all sessions of a specified type"""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        squery = Session.query(ancestor=conf.key)

        sessions = squery.filter(Session.typeOfSession == request.typeOfSession).fetch()
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )
    # Exceed req add speaker as an entity
    @endpoints.method(SESSION_GET_REQUEST_BY_SPEAKER, SessionForms,
            path='session/{speakerFullname}',
            http_method='GET', name='getSessionsBySpeaker')
    def getSessionsBySpeaker(self, request):
        """ Given a speaker, return all sessions given by this particular
         speaker, across all conferences"""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        squery = Session.query(ancestor=conf.key)
        sessions = [sess for sess in squery if getattr(ses, 'speakerKey').get().fullname == request.speakerFullname ]

        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

# ------- Wish List ------------

    def _createWishListObject(self, request):
        """Create or update WishList object, returning WishListForm/request.
           A session can only be created by a user who has created a conference"""
        # preload necessary data items
        user = endpoints.get_current_user()

        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)
        # Get the conference from websafeConferenceKey
        p_key = ndb.Key(Profile, user_id)
        session = ndb.Key(urlsafe=request.sessionKey).get()

        wlquery = WishList.query(ancestor=p_key)
        wlist = wlquery.filter(WishList.sessionKey == session.key).fetch()

        is_wishlist_not_exist = True
        if wlist is not None:
            for wl in wlist:
                if wl.sessionKey == session.key:
                    is_wishlist_not_exist = False

        if is_wishlist_not_exist:
            # generate Profile Key based on user ID and Conference

            wishlist_id = WishList.allocate_ids(size=1, parent=p_key)[0]
            wishlist_key = ndb.Key(WishList, wishlist_id, parent=p_key)

            # copy WishlistForm/ProtoRPC Message into dict data
            dict_data = {field.name: getattr(request, field.name)
                         for field in request.all_fields()}
            # convert session key to key property
            if dict_data['sessionKey']:
                dict_data['sessionKey'] = ndb.Key(urlsafe=request.sessionKey)
            else:
                print ("Something is wrong with the session key")

            dict_data['userID'] = user_id
            # Save session data to datastore
            WishList(**dict_data).put()

        return request

    def _copyWishListToForm(self, wishlist):
        """Copy relevant fields from Wishlist to WishlistForm."""
        wlform = WishListForm()

        for field in wlform.all_fields():
            if hasattr(wishlist, field.name):
                # convert Key to key string and just copy others
                if field.name.endswith('sessionKey'):
                    setattr(wlform, field.name, str(getattr(wishlist, field.name)))
                else:
                    print "[_copyWishListToForm] No sessionKey but: ",field.name
                    setattr(wlform, field.name, getattr(wishlist, field.name))

        wlform.check_initialized()
        return wlform

    # addSessionToWishlist(SessionKey)
    @endpoints.method(WishListForm, WishListForm,
            path='session/addwishlist',
            http_method='POST', name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """adds the session to the user's list of sessions they are interested
         in attending"""
        return self._createWishListObject(request)

    @endpoints.method(message_types.VoidMessage, SessionForms,
            path='session/wishlists',
            http_method='GET', name='getSessionsInWishlist')
    def getSessionsInWishlist(self, request):
        """query for all the sessions in a conference that the user is
         interested in"""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)
        # Get the conference from websafeConferenceKey
        p_key = ndb.Key(Profile, user_id)
        wlquery = WishList.query()
        wishlists = wlquery.filter(WishList.userID == user_id).fetch()
        sessions =[]
        for wl in wishlists:
            sessions.append(wl.sessionKey.get())

        return SessionForms(
            items=[self._copySessionToForm(sess) for sess in sessions]
        )

    # ----- Task 3: Create 2 Queries -----
    @endpoints.method(SESSION_GET_REQUEST_BY_SPEAKER_TYPE, SessionForms,
            path='session/speakertype',
            http_method='GET', name='getSessionsBySpeakerAndType')
    def getSessionsBySpeakerAndType(self, request):
        """ Given a speaker and type, return all sessions given by this particular
         speaker and type, across all conferences"""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        # get the key of the input speaker
        spquery = Speaker.query(Speaker.fullname == request.speakerFullname)
        speakerkey =  spquery.get().key

        squery = Session.query()
        squery2 = squery.filter(ndb.AND(Session.speakerKey == speakerkey,
                                        Session.typeOfSession == request.typeOfSession))
        return SessionForms(
            items=[self._copySessionToForm(session) for session in squery2]
        )

    @endpoints.method(message_types.VoidMessage, SpeakerForms,
            path='session/allspeakers',
            http_method='GET', name='getAllSpeakers')
    def getAllSpeakers(self, request):
        """ Get all registered speakers"""
        speakers = Speaker.query()

        return SpeakerForms(
            items= [self._copySpeakerToForm(speaker) for speaker in speakers]
        )

    @endpoints.method(message_types.VoidMessage, SessionForms,
                      path='session/not_workshop_not_after_seven_pm',
                http_method='GET', name='getSessionNoWshopUptoSevenPM')
    def getSessionNoWshopUptoSevenPM(self, request):
        """Get all session that not a workshop and not over seven p.m"""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        # get the date information

        sevenpm = datetime.strptime("19:00:00", '%H:%M:%S')
        sevenpm = sevenpm.time()
        sessions = Session.query(Session.typeOfSession != "Workshop").fetch()

        # search for each session, get the time information and compare the time
        filtered_sessions = [session for session in sessions if session.startTime < sevenpm]

        return SessionForms(
            items=[self._copySessionToForm(session) for session in filtered_sessions]
        )

    # ----- Task 4 ------
    @staticmethod
    def _checkFeaturedSpeaker(conf_urlsafekey, speaker_name, speaker_prof):
        """Add Task push queue for checking feature speaker. 
        When a new session is added to a conference, check the speaker. 
        If there is more than one session by this speaker at this conference,
        also add a new Memcache entry that features the speaker and
        session names. """

        if (not conf_urlsafekey):
            raise endpoints.BadRequestException("Invalid uslsafekey")
        conf = ndb.Key(urlsafe=conf_urlsafekey).get()
        squery = Session.query(ancestor=conf.key)

        # check if Speaker entity has already existed
        q_speaker = Speaker.query(Speaker.fullname == speaker_name)
        existed_speaker = q_speaker.get()
        profession = speaker_prof
        if existed_speaker:
            if existed_speaker.fullname == speaker_name:
                # Search all session from the speaker
                squery = Session.query(Session.speakerKey == existed_speaker.key)
                featSessions = squery.fetch() 
                sessNames = [sess.name for sess in featSessions ]
                # add a new memcache
                fspeaker = FEATURED_SPEAKER_TPL %(speaker_name, sessNames )
                memcache.set(MEMCACHE_FEATURED_SPEAKER, fspeaker)
        else:
            print "speaker does not exist yet"

    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='session/featured_speaker/get',
            http_method='GET', name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """Return featured speaker in a conference from memcache"""
        fspeaker= memcache.get(MEMCACHE_FEATURED_SPEAKER)
        if not fspeaker:
            fspeaker = ""
        return StringMessage(data=fspeaker)

api = endpoints.api_server([ConferenceApi])# register API
