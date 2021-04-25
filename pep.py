import os
import sys
import threading
from multiprocessing.pool import ThreadPool
import tornado.gen
import tornado.httpserver
import tornado.ioloop
import tornado.web
from raven.contrib.tornado import AsyncSentryClient
import redis

import json
import shutil

from common import generalUtils, agpl
from common.constants import bcolors
from common.db import dbConnector
from common.ddog import datadogClient
from logger import log
from common.redis import pubSub
from common.web import schiavo
from handlers import apiFokabotMessageHandler
from handlers import apiGetTheFuckOuttaHere
from handlers import apiIsOnlineHandler
from handlers import apiOnlineUsersHandler
from handlers import apiServerStatusHandler
from handlers import apiVerifiedStatusHandler
from handlers import ciTriggerHandler
from handlers import mainHandler
from handlers import apiUserStatusHandler
from helpers import configHelper
from helpers import consoleHelper
from helpers import systemHelper as system
from irc import ircserver
from objects import banchoConfig
from objects import chatFilters
from objects import fokabot
from objects import glob
from pubSubHandlers import changeUsernameHandler, setMainMenuIconHandler

from pubSubHandlers import disconnectHandler
from pubSubHandlers import banHandler
from pubSubHandlers import notificationHandler
from pubSubHandlers import updateSilenceHandler
from pubSubHandlers import updateStatsHandler

# WE GOT DELTA.
try:
	from realistik import delta
except ImportError:
	log.info("Not using Realistik Delta implementation.")
	from handlers import apiGetTheFuckOuttaHere as deltaApi

def make_app():
	return tornado.web.Application([
		(r"/", mainHandler.handler),
		(r"/api/v1/isOnline", apiIsOnlineHandler.handler),
		(r"/api/v1/onlineUsers", apiOnlineUsersHandler.handler),
		(r"/api/v1/serverStatus", apiServerStatusHandler.handler),
		(r"/api/v1/ciTrigger", ciTriggerHandler.handler),
		(r"/api/v1/verifiedStatus", apiVerifiedStatusHandler.handler),
		(r"/api/v1/fokabotMessage", apiFokabotMessageHandler.handler),
		(r"/api/yes/userstats", apiUserStatusHandler.handler),
		(r"/api/v2/clients/(.*)", deltaApi.handler)
	])


if __name__ == "__main__":
	# AGPL license agreement
	try:
		agpl.check_license("ripple", "pep.py")
	except agpl.LicenseError as e:
		print(str(e))
		sys.exit(1)

	try:
		# Server start
		consoleHelper.printServerStartHeader(True)

		# Read config.ini
		log.info("Loading config file... ")
		glob.conf = configHelper.config("config.ini")

		if glob.conf.default:
			# We have generated a default config.ini, quit server
			log.warning("config.ini not found. A default one has been generated.")
			log.warning("Please edit your config.ini and run the server again.")
			sys.exit()

		# If we haven't generated a default config.ini, check if it's valid
		if not glob.conf.checkConfig():
			log.error("Invalid config.ini. Please configure it properly")
			log.error("Delete your config.ini to generate a default one")
			sys.exit()
		else:
			log.info("Complete!")

		# Read additional config file
		log.info("Loading additional config file... ")
		try:
			if not os.path.isfile(glob.conf.config["custom"]["config"]):
				log.warning("Missing config file at {}; A default one has been generated at this location.".format(glob.conf.config["custom"]["config"]))
				shutil.copy("common/default_config.json", glob.conf.config["custom"]["config"])

			with open(glob.conf.config["custom"]["config"], "r") as f:
				glob.conf.extra = json.load(f)

			log.info("Complete!")
		except:
			log.error("Unable to load custom config at {}".format(glob.conf.config["custom"]["config"]))
			sys.exit()

		# Create data folder if needed
		log.info("Checking folders... ")
		paths = [".data"]
		for i in paths:
			if not os.path.exists(i):
				os.makedirs(i, 0o770)
		log.info("Complete!")

		# Connect to db
		try:
			log.info("Connecting to MySQL database... ")
			glob.db = dbConnector.db(glob.conf.config["db"]["host"], glob.conf.config["db"]["username"], glob.conf.config["db"]["password"], glob.conf.config["db"]["database"], int(glob.conf.config["db"]["workers"]))
			log.info("Complete!")
		except:
			# Exception while connecting to db
			log.error("Error while connection to database. Please check your config.ini and run the server again")
			raise

		# Connect to redis
		try:
			log.info("Connecting to redis... ")
			glob.redis = redis.Redis(glob.conf.config["redis"]["host"], glob.conf.config["redis"]["port"], glob.conf.config["redis"]["database"], glob.conf.config["redis"]["password"])
			glob.redis.ping()
			log.info("Complete!")
		except:
			# Exception while connecting to db
			log.error("Error while connection to redis. Please check your config.ini and run the server again")
			raise

		# Empty redis cache
		try:
			# TODO: Make function or some redis meme
			glob.redis.set("ripple:online_users", 0)
			glob.redis.eval("return redis.call('del', unpack(redis.call('keys', ARGV[1])))", 0, "peppy:*")
		except redis.exceptions.ResponseError:
			# Script returns error if there are no keys starting with peppy:*
			pass

		# Save peppy version in redis
		glob.redis.set("peppy:version", glob.VERSION)

		# Load bancho_settings
		try:
			log.info("Loading bancho settings from DB... ")
			glob.banchoConf = banchoConfig.banchoConfig()
			log.info("Complete!")
		except:
			consoleHelper.printError()
			consoleHelper.printColored("Error while loading bancho_settings. Please make sure the table in DB has all the required rows", bcolors.RED)
			raise

		# Delete old bancho sessions
		log.info("Deleting cached bancho sessions from DB... ")
		glob.tokens.deleteBanchoSessions()
		log.info("Complete!")

		# Create threads pool
		try:
			log.info("Creating threads pool... ")
			glob.pool = ThreadPool(int(glob.conf.config["server"]["threads"]))
			log.info("Complete!")
		except ValueError:
			consoleHelper.printError()
			consoleHelper.printColored("Error while creating threads pool. Please check your config.ini and run the server again", bcolors.RED)

		try:
			log.info("Loading chat filters... ")
			glob.chatFilters = chatFilters.chatFilters()
			log.info("Complete!")
		except:
			consoleHelper.printError()
			consoleHelper.printColored("Error while loading chat filters. Make sure there is a filters.txt file present", bcolors.RED)
			raise

		# Start fokabot
		log.info("Connecting RealistikBot...")
		fokabot.connect()
		log.info("Complete!")

		# Initialize chat channels
		log.info("Initializing chat channels... ")
		glob.channels.loadChannels()
		log.info("Complete!")

		# Initialize stremas
		log.info("Creating packets streams... ")
		glob.streams.add("main")
		glob.streams.add("lobby")
		log.info("Complete!")

		# Initialize user timeout check loop
		log.info("Initializing user timeout check loop... ")
		glob.tokens.usersTimeoutCheckLoop()
		log.info("Complete!")

		# Initialize spam protection reset loop
		log.info("Initializing spam protection reset loop... ")
		glob.tokens.spamProtectionResetLoop()
		log.info("Complete!")

		# Initialize multiplayer cleanup loop
		log.info("Initializing multiplayer cleanup loop... ")
		glob.matches.cleanupLoop()
		log.info("Complete!")

		# Localize warning
		glob.localize = generalUtils.stringToBool(glob.conf.config["localize"]["enable"])
		if not glob.localize:
			log.warning("Users localization is disabled!")

		# Discord
		if generalUtils.stringToBool(glob.conf.config["discord"]["enable"]):
			glob.schiavo = schiavo.schiavo(glob.conf.config["discord"]["boturl"], "**pep.py**")
		else:
			log.warning("Discord logging is disabled!")

		# Gzip
		glob.gzip = generalUtils.stringToBool(glob.conf.config["server"]["gzip"])
		glob.gziplevel = int(glob.conf.config["server"]["gziplevel"])
		if not glob.gzip:
			log.warning("Gzip compression is disabled!")

		# Debug mode
		glob.debug = generalUtils.stringToBool(glob.conf.config["debug"]["enable"])
		glob.outputPackets = generalUtils.stringToBool(glob.conf.config["debug"]["packets"])
		glob.outputRequestTime = generalUtils.stringToBool(glob.conf.config["debug"]["time"])
		if glob.debug:
			log.warning("Server running in debug mode!")

		# Make app
		glob.application = make_app()

		# Set up sentry
		try:
			glob.sentry = generalUtils.stringToBool(glob.conf.config["sentry"]["enable"])
			if glob.sentry:
				glob.application.sentry_client = AsyncSentryClient(glob.conf.config["sentry"]["banchodsn"], release=glob.VERSION)
			else:
				log.warning("Sentry logging is disabled!")
		except:
			log.error("Error while starting sentry client! Please check your config.ini and run the server again")

		# Set up datadog
		try:
			if generalUtils.stringToBool(glob.conf.config["datadog"]["enable"]):
				glob.dog = datadogClient.datadogClient(
					glob.conf.config["datadog"]["apikey"],
					glob.conf.config["datadog"]["appkey"],
					[
						datadogClient.periodicCheck("online_users", lambda: len(glob.tokens.tokens)),
						datadogClient.periodicCheck("multiplayer_matches", lambda: len(glob.matches.matches)),

						#datadogClient.periodicCheck("ram_clients", lambda: generalUtils.getTotalSize(glob.tokens)),
						#datadogClient.periodicCheck("ram_matches", lambda: generalUtils.getTotalSize(glob.matches)),
						#datadogClient.periodicCheck("ram_channels", lambda: generalUtils.getTotalSize(glob.channels)),
						#datadogClient.periodicCheck("ram_file_buffers", lambda: generalUtils.getTotalSize(glob.fileBuffers)),
						#datadogClient.periodicCheck("ram_file_locks", lambda: generalUtils.getTotalSize(glob.fLocks)),
						#datadogClient.periodicCheck("ram_datadog", lambda: generalUtils.getTotalSize(glob.datadogClient)),
						#datadogClient.periodicCheck("ram_verified_cache", lambda: generalUtils.getTotalSize(glob.verifiedCache)),
						#datadogClient.periodicCheck("ram_irc", lambda: generalUtils.getTotalSize(glob.ircServer)),
						#datadogClient.periodicCheck("ram_tornado", lambda: generalUtils.getTotalSize(glob.application)),
						#datadogClient.periodicCheck("ram_db", lambda: generalUtils.getTotalSize(glob.db)),
					])
			else:
				log.warning("Datadog stats tracking is disabled!")
		except:
			log.warning("Error while starting Datadog client! Please check your config.ini and run the server again")

		# IRC start message and console output
		glob.irc = generalUtils.stringToBool(glob.conf.config["irc"]["enable"])
		if glob.irc:
			# IRC port
			ircPort = 0
			try:
				ircPort = int(glob.conf.config["irc"]["port"])
			except ValueError:
				log.error("Invalid IRC port! Please check your config.ini and run the server again")
			log.logMessage("IRC server started!", discord="bunker", of="info.txt", stdout=False)
			log.info("IRC server listening on 127.0.0.1:{}...".format(ircPort))
			threading.Thread(target=lambda: ircserver.main(port=ircPort)).start()
		else:
			log.warning("IRC server is disabled!", bcolors.YELLOW)

		# Server port
		serverPort = 0
		try:
			serverPort = int(glob.conf.config["server"]["port"])
		except ValueError:
			log.error("Invalid server port! Please check your config.ini and run the server again")

		# Server start message and console output
		log.logMessage("Server started!", discord="bunker", of="info.txt", stdout=False)
		log.info("Tornado listening for HTTP(s) clients on 127.0.0.1:{}...".format(serverPort))

		# Connect to pubsub channels
		pubSub.listener(glob.redis, {
			"peppy:disconnect": disconnectHandler.handler(),
			"peppy:change_username": changeUsernameHandler.handler(),
			"peppy:reload_settings": lambda x: x == b"reload" and glob.banchoConf.reload(),
			"peppy:update_cached_stats": updateStatsHandler.handler(),
			"peppy:silence": updateSilenceHandler.handler(),
			"peppy:ban": banHandler.handler(),
			"peppy:notification": notificationHandler.handler(),
			"peppy:set_main_menu_icon": setMainMenuIconHandler.handler(),
		}).start()

		# Start tornado
		glob.application.listen(serverPort)
		tornado.ioloop.IOLoop.instance().start()
	finally:
		system.dispose()