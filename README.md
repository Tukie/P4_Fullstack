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
| speakerName      | String    | Speaker fullname    |
| speakerProfession| String    | Speaker profession  |
| duration         | Integer   | in minutes          |
| typeOfSession    | String    | Session's type      |
| startDateTime    | DateTime  | Session start combine in date and time|

This approach is implemented to reduce the data store table. If date and start time are separated to two column. I see that even using time property the initial date is still shown in the start time column. Also in the date column, datastore shows the time as 00:00:00

The Speaker entity is implemented with user profile entity as the parent entity. I would like to map the speaker key to the session's speaker property. However, due to the Task 4 (getFeaturedSpeaker) I prefer to not implement the speaker as NDB key property. The reason is that having a key as property, a new entity of speaker has to be created first in order to put the session entity into the datastore. This means that the taask queue has to run and finish before `Session(**dict_data).put()`, which is not really significant.


## Task 2 Session Wishlist
Whishlist endpoints: 

*`addSessionToWishlist(self, request)`

*`getSessionsInWishlist(self, request)`

## Task 3
### Additional Query

- `getSessionsBySpeakerAndType`: This query posibbles user to list all session by particular speaker and type of session

- `getAvailableWishList`: This query can list all the availabe wishlist based on the available conference seat

###Query problem: Let’s say that you don't like workshops and you don't like sessions after 7 pm

The reason is the query restrictions:
1. An inequality filter can be applied to at most one property
2. A property with en inequality filter must be sorted first

There are two possible solutions:

1. One solution is by using ndb.ComputedProperty and repeated attribute as described in [stackoverflow][7]: `sessionTypeAndStartTime = ndb.ComputedProperty(lambda self: [self.typeOfSession, self.startDateTime], repeated=True)`
2. Since in my implementation startTime is included in startTimeDate (see my design choices), I cannot easly utilize the first solution. Thus, I iterate the query results from typeOfSession != Workshop and check if the time less than seven pm. My solution is implemented in endpoint: `getSessionNoWshopUptoSevenPM()`

## Task 4 Feature Speaker
Using task queue to implement this feature. The task queue runs after storing the Session data in the function of `_createSessionObject`

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