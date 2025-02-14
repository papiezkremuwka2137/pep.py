import sys
import time
import traceback

from common.constants import privileges
from logger import log
from common.ripple import userUtils
from constants import exceptions
from constants import serverPackets
from helpers import chatHelper as chat
from helpers import countryHelper
from objects import glob
from datetime import datetime
from helpers.realistik_stuff import Timer
from objects import glob
import random

# We have our own hashing things. We'd like to keep what they are a secret.
# This is an issue with an open sec project, so we keep it in a private module.
try: from realistik.user_utils import verify_password
except ImportError:
	log.warning("Using Ripple password hash!")
	from common.ripple.userUtils import checkLogin as verify_password

# Let people use this without our private module.
try:
	from realistik.localise import get_full
except ImportError:
	log.warning("Using RippleAPI geolocation.")
	from helpers.locationHelper import get_full

UNFREEZE_NOTIF = serverPackets.notification("Thank you for providing a liveplay! You have proven your legitemacy and have subsequently been unfrozen. Have fun playing RealistikOsu!")
FREEZE_RES_NOTIF = serverPackets.notification("Your window for liveplay sumbission has expired! Your account has been restricted as per our cheating policy. Please contact staff for more information on what can be done. This can be done via the RealistikCentral Discord server.")

def handle(tornadoRequest):
	# I wanna benchmark!
	t = Timer()
	t.start()
	# Data to return
	responseToken = None
	responseTokenString = ""
	responseData = bytearray()

	# Get IP from tornado request
	requestIP = tornadoRequest.getRequestIP()

	# Avoid exceptions
	clientData = ("unknown", "unknown", "unknown", "unknown", "unknown")
	osuVersion = "unknown"

	# Split POST body so we can get username/password/hardware data
	# 2:-3 thing is because requestData has some escape stuff that we don't need
	loginData = str(tornadoRequest.request.body)[2:-3].split("\\n")
	try:
		# Make sure loginData is valid
		if len(loginData) < 3:
			log.error("Login error (invalid login data)!")
			raise exceptions.invalidArgumentsException()

		# Get HWID, MAC address and more
		# Structure (new line = "|", already split)
		# [0] osu! version
		# [1] plain mac addressed, separated by "."
		# [2] mac addresses hash set
		# [3] unique ID
		# [4] disk ID
		splitData = loginData[2].split("|")
		osuVersion = splitData[0]
		timeOffset = int(splitData[1])
		clientData = splitData[3].split(":")[:5]
		if len(clientData) < 4:
			raise exceptions.forceUpdateException()

		# Try to get the ID from username
		username = str(loginData[0])
		safe_username = username.rstrip().replace(" ", "_").lower()

		# Set stuff from single query rather than many userUtils calls.
		user_db = glob.db.fetch(
			"SELECT id, privileges, silence_end, donor_expire, frozen, "
			"firstloginafterfrozen, freezedate FROM users "
			"WHERE username_safe = %s LIMIT 1",
			(safe_username,)
		)

		if not user_db:
			# Invalid username
			log.error(f"Login failed for user {username} (user not found)!")
			responseData += serverPackets.notification("RealistikOsu: This user does not exist!")
			raise exceptions.loginFailedException()

		userID = user_db["id"]
		priv = int(user_db["privileges"])
		silence_end = int(user_db["silence_end"])
		donor_expire = int(user_db["donor_expire"])
		
		if not verify_password(userID, loginData[1]):
			# Invalid password
			log.error(f"Login failed for user {username} (invalid password)!")
			responseData += serverPackets.notification("RealistikOsu: Invalid password!")
			raise exceptions.loginFailedException()

		# Make sure we are not banned or locked
		if (not priv & 3 > 0) and (not priv & privileges.USER_PENDING_VERIFICATION):
			log.error(f"Login failed for user {username} (user is banned)!")
			raise exceptions.loginBannedException()

		# No login errors!

		# Verify this user (if pending activation)
		firstLogin = False
		if priv & privileges.USER_PENDING_VERIFICATION or not userUtils.hasVerifiedHardware(userID):
			if userUtils.verifyUser(userID, clientData):
				# Valid account
				log.info(f"Account {userID} verified successfully!")
				glob.verifiedCache[str(userID)] = 1
				firstLogin = True
			else:
				# Multiaccount detected
				log.info(f"Account {userID} NOT verified!")
				glob.verifiedCache[str(userID)] = 0
				raise exceptions.loginBannedException()


		# Save HWID in db for multiaccount detection
		hwAllowed = userUtils.logHardware(userID, clientData, firstLogin)

		# This is false only if HWID is empty
		# if HWID is banned, we get restricted so there's no
		# need to deny bancho access
		if not hwAllowed:
			raise exceptions.haxException()

		# Log user IP
		userUtils.logIP(userID, requestIP)

		# Log user osuver
		glob.db.execute("UPDATE users SET osuver = %s WHERE id = %s LIMIT 1", [osuVersion, userID])

		# Delete old tokens for that user and generate a new one
		isTournament = "tourney" in osuVersion
		if not isTournament:
			glob.tokens.deleteOldTokens(userID)
		responseToken = glob.tokens.addToken(userID, requestIP, timeOffset=timeOffset, tournament=isTournament)
		responseTokenString = responseToken.token

		# Check restricted mode (and eventually send message)
		# Cache this for less db queries
		user_restricted = (priv & privileges.USER_NORMAL) and not (priv & privileges.USER_PUBLIC)

		if user_restricted: responseToken.setRestricted()
		#responseToken.checkRestricted()

		# Check if frozen
		frozen = user_db["frozen"]

		present = datetime.now()
		readabledate = datetime.utcfromtimestamp(user_db["freezedate"]).strftime('%d-%m-%Y %H:%M:%S')
		date2 = datetime.utcfromtimestamp(user_db["freezedate"]).strftime('%d/%m/%Y')
		date3 = present.strftime('%d/%m/%Y')
		passed = date2 < date3
		if frozen and not passed:
				responseToken.enqueue(serverPackets.notification(f"The RealistikOsu staff team has found you suspicious and would like to request a liveplay. You have until {readabledate} (UTC) to provide a liveplay to the staff team. This can be done via the RealistikCentral Discord server. Failure to provide a valid liveplay will result in your account being automatically restricted."))
		elif frozen and passed:
				responseToken.enqueue(FREEZE_RES_NOTIF)
				userUtils.restrict(responseToken.userID)

		#we thank unfrozen people		
		if not frozen and user_db["firstloginafterfrozen"]:
			responseToken.enqueue(UNFREEZE_NOTIF)
			glob.db.execute(f"UPDATE users SET firstloginafterfrozen = 0 WHERE id = {userID}")

		# Send message if donor expires soon
		if responseToken.privileges & privileges.USER_DONOR:
			if donor_expire-int(time.time()) <= 86400*3:
				expireDays = round((donor_expire-int(time.time()))/86400)
				expireIn = "{} days".format(expireDays) if expireDays > 1 else "less than 24 hours"
				responseToken.enqueue(serverPackets.notification("Your supporter status expires in {}! Following this, you will lose your supporter privileges (such as the further profile customisation options, name changes or profile wipes) and will not be able to access supporter features. If you wish to keep supporting RealistikOsu and you don't want to lose your donor privileges, you can donate again by clicking on 'Donate' on our website.".format(expireIn)))

		# Get only silence remaining seconds
		responseToken.silenceEndTime = silence_end
		silenceSeconds = responseToken.getSilenceSecondsLeft()
		# Get supporter/GMT
		userGMT = False
		userSupporter = not user_restricted
		userTournament = False
		userGMT = responseToken.admin
		userTournament = bool(responseToken.privileges & privileges.USER_TOURNAMENT_STAFF)

		# Server restarting check
		if glob.restarting: raise exceptions.banchoRestartingException()

		# Maintenance check
		if glob.banchoConf.config["banchoMaintenance"]:
			if not userGMT:
				# We are not mod/admin, delete token, send notification and logout
				glob.tokens.deleteToken(responseTokenString)
				raise exceptions.banchoMaintenanceException()
			else:
				# We are mod/admin, send warning notification and continue
				responseToken.enqueue(serverPackets.notification("Bancho is in maintenance mode. Only mods/admins have full access to the server.\nType !system maintenance off in chat to turn off maintenance mode."))

		# BAN CUSTOM CHEAT CLIENTS
		# 0Ainu = First Ainu build
		# b20190326.2 = Ainu build 2 (MPGH PAGE 10)
		# b20190401.22f56c084ba339eefd9c7ca4335e246f80 = Ainu Aoba's Birthday Build
		# b20191223.3 = Unknown Ainu build? (Taken from most users osuver in cookiezi.pw)
		# b20190226.2 = hqOsu (hq-af)

		# TODO: Rewrite this mess
		# Ainu Client 2020 update
		if tornadoRequest.request.headers.get("ainu"):
			log.info(f"Account {userID} tried to use Ainu Client 2020!")
			if user_restricted:
				responseToken.enqueue(serverPackets.notification("Note: AINU CLIENT IS DETECTED EVERYWHERE... ITS CREATORS LITERALLY ADDED A WAY TO EASILY DETECT."))
			else:
				glob.tokens.deleteToken(userID)
				userUtils.restrict(userID)
				userUtils.appendNotes(userID, "User restricted on login for Ainu Client 2020.")
				raise exceptions.loginCheatClientsException()
		# Ainu Client 2019
		elif osuVersion in ("0Ainu", "b20190326.2", "b20190401.22f56c084ba339eefd9c7ca4335e246f80", "b20191223.3"):
			log.info(f"Account {userID} tried to use Ainu Client!")
			if user_restricted:
				responseToken.enqueue(serverPackets.notification("Note: AINU CLIENT IS DETECTED EVERYWHERE..."))
			else:
				glob.tokens.deleteToken(userID)
				userUtils.restrict(userID)
				userUtils.appendNotes(userID, "User restricted on login for Ainu Client 2019 (or older).")
				raise exceptions.loginCheatClientsException()
		# hqOsu
		elif osuVersion == "b20190226.2":
			log.info(f"Account {userID} tried to use hqOsu!")
			if user_restricted:
				responseToken.enqueue(serverPackets.notification("Comedian."))
			else:
				glob.tokens.deleteToken(userID)
				userUtils.restrict(userID)
				userUtils.appendNotes(userID, "User restricted on login for HQOsu (normal).")
				raise exceptions.loginCheatClientsException()
		
		#hqosu legacy
		elif osuVersion == "b20190716.5":
			log.info(f"Account {userID} tried to use hqOsu legacy!")
			if user_restricted:
				responseToken.enqueue(serverPackets.notification("Comedian."))
			else:
				glob.tokens.deleteToken(userID)
				userUtils.restrict(userID)
				userUtils.appendNotes(userID, "User restricted on login for HQOsu (legacy).")
				raise exceptions.loginCheatClientsException()
		# Budget Hacked client.
		elif osuVersion.startswith("skoot"):
			if user_restricted: responseToken.enqueue(serverPackets.notification("Comedian."))
			else:
				glob.tokens.deleteToken(userID)
				userUtils.restrict(userID)
				userUtils.appendNotes(userID, "Wack 2016 Scooter client.")
				raise exceptions.loginCheatClientsException()
		
		# Blanket cover for most retard clients, force update.
		elif osuVersion[0] != "b":
			glob.tokens.deleteToken(userID)
			raise exceptions.haxException()

		# Send all needed login packets
		responseToken.enqueue(
			bytearray(serverPackets.silenceEndTime(silenceSeconds)) + # Fast addition
			serverPackets.userID(userID) +
			serverPackets.protocolVersion() +
			serverPackets.userSupporterGMT(userSupporter, userGMT, userTournament) +
			serverPackets.userPanel(userID, True) +
			serverPackets.userStats(userID, True) +
			serverPackets.channelInfoEnd()
		)

		# Default opened channels
		# TODO: Configurable default channels
		chat.joinChannel(token=responseToken, channel="#osu")
		chat.joinChannel(token=responseToken, channel="#announce")

		# Join admin channel if we are an admin
		if responseToken.admin:
			chat.joinChannel(token=responseToken, channel="#admin")

		# Output channels info
		for key, value in glob.channels.channels.items():
			if value.publicRead and not value.hidden:
				responseToken.enqueue(serverPackets.channelInfo(key))

		# Send friends list
		responseToken.enqueue(serverPackets.friendList(userID))

		# Send main menu icon
		if glob.banchoConf.config["menuIcon"] != "":
			responseToken.enqueue(serverPackets.mainMenuIcon(glob.banchoConf.config["menuIcon"]))

		# Send online users' panels
		with glob.tokens:
			for _, token in glob.tokens.tokens.items():
				if not token.restricted:
					responseToken.enqueue(serverPackets.userPanel(token.userID))

		# Localise the user based off IP.
		if glob.localize:
			# Get location and country from IP
			latitude, longitude, countryLetters = get_full(requestIP)

			country = countryHelper.getCountryID(countryLetters)
		else:
			# Set location to 0,0 and get country from db
			log.warning("Localisation of user skipped! If this was not intended, please check your pep.py configuration.")
			latitude = 0
			longitude = 0
			countryLetters = "XX"
			country = countryHelper.getCountryID(userUtils.getCountry(userID))

		# Set location and country
		responseToken.setLocation(latitude, longitude)
		responseToken.country = country

		# Set country in db if user has no country (first bancho login)
		if userUtils.getCountry(userID) == "XX": userUtils.setCountry(userID, countryLetters)

		# Send to everyone our userpanel if we are not restricted or tournament
		if not responseToken.restricted:
			glob.streams.broadcast("main", serverPackets.userPanel(userID))
		
		#creating notification
		t.end()
		t_str = t.time_str()
		online_users = len(glob.tokens.tokens)
		# Wylie has his own quote he gets to enjoy only himself lmfao. UPDATE: Electro gets it too.
		if userID in (4674, 3277): quote = "I lost an S because I saw her lewd"
		# Ced also gets his own AS HE DOESNT WANT TO CHECK FAST SPEED.
		elif userID == 1002: quote = "juSt Do iT"
		else: quote = random.choice(glob.banchoConf.config['Quotes'])
		notif = f"""- Online Users: {online_users}\n- {quote}"""
		if responseToken.admin: notif += f"\nAuthentication attempt took {t_str}!"
		responseToken.enqueue(serverPackets.notification(notif))
		
		log.info(f"Authentication attempt took {t_str}!")

		# Set reponse data to right value and reset our queue
		responseData = responseToken.fetch_queue()
	except exceptions.loginFailedException:
		# Login failed error packet
		# (we don't use enqueue because we don't have a token since login has failed)
		responseData += serverPackets.loginFailed()
	except exceptions.invalidArgumentsException:
		# Invalid POST data
		# (we don't use enqueue because we don't have a token since login has failed)
		responseData += serverPackets.loginFailed()
		responseData += serverPackets.notification("I have eyes y'know?")
	except exceptions.loginBannedException:
		# Login banned error packet
		responseData += serverPackets.loginBanned()
	except exceptions.loginLockedException:
		# Login banned error packet
		responseData += serverPackets.loginLocked()
	except exceptions.loginCheatClientsException:
		# Banned for logging in with cheats
		responseData += serverPackets.loginCheats()
	except exceptions.banchoMaintenanceException:
		# Bancho is in maintenance mode
		responseData = bytes()
		if responseToken is not None:
			responseData = responseToken.fetch_queue()
		responseData += serverPackets.notification("Our bancho server is in maintenance mode. Please try to login again later.")
		responseData += serverPackets.loginFailed()
	except exceptions.banchoRestartingException:
		# Bancho is restarting
		responseData += serverPackets.notification("Bancho is restarting. Try again in a few minutes.")
		responseData += serverPackets.loginFailed()
	except exceptions.need2FAException:
		# User tried to log in from unknown IP
		responseData += serverPackets.needVerification()
	except exceptions.haxException:
		# Using oldoldold client, we don't have client data. Force update.
		# (we don't use enqueue because we don't have a token since login has failed)
		responseData += serverPackets.forceUpdate()
		responseData += serverPackets.notification("What...")
	except:
		log.error("Unknown error!\n```\n{}\n{}```".format(sys.exc_info(), traceback.format_exc()))
	finally:
		# Console and discord log
		if len(loginData) < 3:
			log.info("Invalid bancho login request from **{}** (insufficient POST data)".format(requestIP), "bunker")

		# Return token string and data
		return responseTokenString, bytes(responseData)
