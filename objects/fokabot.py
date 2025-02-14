"""FokaBot related functions"""
import re

from common import generalUtils
from common.constants import actions
from common.ripple import userUtils
from constants import fokabotCommands
from constants import serverPackets
from objects import glob
from logger import log
from importlib import reload

def connect():
	"""
	Connect FokaBot to Bancho

	:return:
	"""
	glob.BOT_NAME = userUtils.getUsername(999)
	token = glob.tokens.addToken(999)
	token.actionID = actions.WATCHING
	token.actionText = "over RealistikOsu!"
	token.pp = 69
	token.accuracy = 0.69
	token.playcount = 69
	token.totalScore = 1337
	token.timeOffset = 0
	token.timezone = 24
	token.country = 2 #this is retared, fuck it im keeping it as europe, couldnt find the uk as its ordered stupidly
	token.location = (39.01955903386848, 125.75276158057767) # Pyongyang red square
	glob.streams.broadcast("main", serverPackets.userPanel(999))
	glob.streams.broadcast("main", serverPackets.userStats(999))

def reload_commands():
	"""Reloads the Fokabot commands module."""
	reload(fokabotCommands)

def disconnect():
	"""
	Disconnect FokaBot from Bancho

	:return:
	"""
	glob.tokens.deleteToken(glob.tokens.getTokenFromUserID(999))

def fokabotResponse(fro, chan, message):
	"""
	Check if a message has triggered FokaBot

	:param fro: sender username
	:param chan: channel name (or receiver username)
	:param message: chat mesage
	:return: FokaBot's response or False if no response
	"""
	for i in fokabotCommands.commands:
		# Loop though all commands
		if re.compile("^{}( (.+)?)?$".format(i["trigger"])).match(message.strip()):
			# message has triggered a command

			# Make sure the user has right permissions
			if i["privileges"] is not None:
				# Rank = x
				if userUtils.getPrivileges(userUtils.getID(fro)) & i["privileges"] == 0:
					return False

			# Check argument number
			message = message.split(" ")
			if i["syntax"] != "" and len(message) <= len(i["syntax"].split(" ")):
				return "Wrong syntax: {} {}".format(i["trigger"], i["syntax"])

			# Return response or execute callback
			try:
				if i["callback"] is None:
					return i["response"]
				else:
					return i["callback"](fro, chan, message[1:])
			except Exception as e:
				log.error(f"There was an exception executing command '{message}'. Exception {e}.")

	# No commands triggered
	return False
