# This handles removing cached passwords from cache when the user has their pass
# changed.
from common.redis import generalPubSubHandler
from objects import glob
from helpers.realistik_stuff import cached_passwords

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
		cached_passwords.pop(data["user_id"], None)
