App Engine application for the Udacity training course.

## Products
- [App Engine][1]

## Language
- [Python][2]

## APIs
- [Google Cloud Endpoints][3]

## Setup Instructions
1. Update the value of `application` in `app.yaml` to the app ID you
   have registered in the App Engine admin console and would like to use to host
   your instance of this sample.
1. Update the values at the top of `settings.py` to
   reflect the respective client IDs you have registered in the
   [Developer Console][4].
1. Update the value of CLIENT_ID in `static/js/app.js` to the Web client ID
1. (Optional) Mark the configuration files as unchanged as follows:
   `$ git update-index --assume-unchanged app.yaml settings.py static/js/app.js`
1. Run the app with the devserver using `dev_appserver.py DIR`, and ensure it's running by visiting your local server's address (by default [localhost:8080][5].)
1. (Optional) Generate your client library(ies) with [the endpoints tool][6].
1. Deploy your application.


## Task 1 Design Choices
Session NDB Model is implemented with conference entity as the parent entity. The session has the following properties:

| Session          | NDB Type  | Explaination        |
| -------------    |:---------:| :-----------------: |
| name             | String    | Session's name      |
| highlights       | String    | Session's highlights|
| speakerKey       | Key       | Speaker Key         |
| duration         | Integer   | in minutes          |
| typeOfSession    | String    | Session's type      |
| date             | Date      | Session start date  | 
| startTime        | Time      | Session start time  |  

A websafeSessionKey is included in the SessionForm, but not in Session class. This will allow the API to return a unique identifier for each Session and allow the API users to identify individual Sessions - which is very useful for things like adding Sessions to a wishlist.

| Speaker          | NDB Type  | Explaination        |
| -------------    |:---------:| :-----------------: |
| fullname         | String    | Speaker's fullname  |
| profession       | String    | Speaker's profession|

To normalize the database, the Session entity stores a link (a speaker NDB key) to the Speaker that will be speaking at the Session.

| WishList     | NDB Type  | Explaination           |
| -------------|:---------:| :---------------------:|
| sessionKey   | String    | Link to a Session key  |
| userID       | String    | User ID of the wishlist|

The wishlist contains a session key that links to a session class and an userID to indentify the user of the wishlist.

## Task 2 Session Wishlist
Whishlist endpoints: 

*`addSessionToWishlist(self, request)` is provided in order to add a session into the user's wishlist

*`getSessionsInWishlist(self, request)` prints all the sessions that are included in the user's wishlist. 

## Task 3
### Additional Query

- `getSessionsBySpeakerAndType`: This query posibbles user to list all session by particular speaker and type of session

- `getAllSpeakers`: This query shows all registered speakers independent from any sessions and any conferences

###Query problem: Let’s say that you don't like workshops and you don't like sessions after 7 pm

The reason is the query restrictions:
1. An inequality filter can be applied to at most one property
2. A property with en inequality filter must be sorted first

The solution is:
By iterating the query results from typeOfSession != Workshop and check if the time less than seven pm. My solution is implemented in endpoint: `getSessionNoWshopUptoSevenPM()`

Note in case of equality filters, we can use ndb.ComputedProperty as described in [stackoverflow][7]: `sessionTypeAndStartTime = ndb.ComputedProperty(lambda self: [self.typeOfSession, self.startDateTime], repeated=True)`

## Task 4 Featured Speaker
Using task queue to implement this feature. The task queue runs after storing the Session data in the function `_createSessionObject`
Firstly, we check if a speaker entity has already existed. Then, we search all sessions from the speaker by utilze the session query:
```python
squery = Session.query(Session.speakerKey == existed_speaker.key)
```


```python
@staticmethod
    def _checkFeaturedSpeaker(conf_urlsafekey, speaker_name, speaker_prof):
```
[1]: https://developers.google.com/appengine
[2]: http://python.org
[3]: https://developers.google.com/appengine/docs/python/endpoints/
[4]: https://console.developers.google.com/
[5]: https://localhost:8080/
[6]: https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool
[7]: https://stackoverflow.com/questions/26399767/filter-two-property-vs-filtering-one-computed-property-datastore-google-app-en