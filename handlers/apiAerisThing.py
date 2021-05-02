from objects import glob
import tornado.web
import tornado.gen
import json
import random

class handler(requestsManager.asyncRequestHandler):
    @tornado.web.asynchronous
    @tornado.gen.engine
    def asyncGet(self):
        """Handles the server info endpoint for the Aeris client."""
        resp_dict = {
            "version": 0,
            "motd": f"RealistikOsu | " + random.choice(glob.banchoConf.config['Quotes']),
            "onlineUsers": len(glob.tokenList),
            "icon": "https://ussr.pl/static/image/newlogo2.png",
            "botID": 999
        }
        self.write(json.dumps(resp_dict))

