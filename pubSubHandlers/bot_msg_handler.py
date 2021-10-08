from common.redis import generalPubSubHandler
from helpers import chatHelper
from objects import glob

# Handles `peppy:bot_msg`
class handler(generalPubSubHandler.generalPubSubHandler):
    def __init__(self):
        super().__init__()
        self.structure = {
            "username": "",
            "message": ""
        }
    
    def handle(self, data):
        data = super().parseData(data)
        if data is None: return

        chatHelper.sendMessage(
            glob.BOT_NAME,
            data["username"],
            data["message"],
        )
