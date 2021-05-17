from common.redis import generalPubSubHandler
from objects import glob

class handler(generalPubSubHandler.generalPubSubHandler):
	def __init__(self):
		super().__init__()
		self.structure = {
			"user_id": 0 # Essentially everything that uses snake case in this pep.py fork is done by me lol
		}

	def handle(self, data):
		data = super().parseData(data)
		if data is None:
			return
		targetToken = glob.tokens.getTokenFromUserID(data["userID"])
		if targetToken is not None:
			targetToken.refresh_privs()
