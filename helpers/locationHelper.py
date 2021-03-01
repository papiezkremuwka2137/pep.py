import json
import urllib.request

from common.log import logUtils as log
from objects import glob
	
def get_full(ip: str) -> tuple:
	"""Fetches the user's full geolocation data and returns the imperative
	info retrieved.

	Note:
		THIS IS A FULL API HTTP CALL. IT IS REALLY SLOW. USE SPARINGLY.
	
	Args:
		ip (str): The IP of the user to fetch the info for.
	
	Returns:
		Tuple of data in order of `(lat, long, country)`
	"""

	try:
		req = json.loads(
			urllib.request.urlopen(
				f'{glob.conf.config["localize"]["ipapiurl"]}/{ip}',
				timeout=1
			).read().decode()
		)

		loc = req["loc"].split(",")
		return float(req[0]), float(req[1]), req["country"]
	
	except Exception as e:
		log.error(f"There was an issue with localisation! Exception {e}.")
		return 0.0, 0.0, "XX"
