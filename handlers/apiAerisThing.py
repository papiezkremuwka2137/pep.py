from objects import glob
import tornado.web
import tornado.gen
from common.web import requestsManager
from common.sentry import sentry
import json
import random

class handler(requestsManager.asyncRequestHandler):
    @tornado.web.asynchronous
    @tornado.gen.engine
    @sentry.captureTornado
    def asyncGet(self):
        """Handles the server info endpoint for the Aeris client."""
        resp_dict = {
            "version": 0,
            "motd": f"RealistikOsu\n" + random.choice(glob.banchoConf.config['Quotes']),
            "onlineUsers": int(glob.redis.get("ripple:online_users").decode("utf-8")),
            "icon": "https://ussr.pl/static/image/newlogo2.png",
            "botID": 999
        }
        self.write(json.dumps(resp_dict))

