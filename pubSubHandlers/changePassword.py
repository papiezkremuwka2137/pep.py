# This handles removing cached passwords from cache when the user has their pass
# changed.
from common.redis import generalPubSubHandler
from objects import glob
try:
	from realistik.user_utils import cached_passwords
	has_pass = True
except ImportError: has_pass = False

class handler(generalPubSubHandler.generalPubSubHandler):
	def __init__(self):
		super().__init__()
		self.structure = {
			"user_id": 0 # Essentially everything that uses snake case in this pep.py fork is done by me lol
		}

	def handle(self, data):
		if not has_pass: return
		data = super().parseData(data)
		if data is None:
			return
		cached_passwords.pop(data["user_id"], None)
