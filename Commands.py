# coding=utf8
import sys, os, time, math, pprint, traceback, operator
import Irc, Transactions, Blocknotify, Logger, Global, Hooks, Config
from collections import OrderedDict

commands = {}

def ping(req, _):
	"""%ping - Pong"""
	req.reply("Pong")
commands["ping"] = ping

def balance(req, _):
	"""%balance - Displays your confirmed and unconfirmed balance"""
	acct = Irc.account_names([req.nick])[0]
	if not acct:
		return req.reply_private("You are not identified with freenode services (see /msg NickServ help)")
	confirmed = Transactions.balance(acct)
	pending = Transactions.balance_unconfirmed(acct)
	if pending:
		req.reply("Your balance is Ɖ%i (+Ɖ%i unconfirmed)" % (confirmed, pending))
	else:
		req.reply("Your balance is Ɖ%i" % (confirmed))
commands["balance"] = balance

def deposit(req, _):
	"""%deposit - Displays your deposit address"""
	acct = Irc.account_names([req.nick])[0]
	if not acct:
		return req.reply_private("You are not identified with freenode services (see /msg NickServ help)")
	req.reply_private("To deposit, send coins to %s (transactions will be credited after %d confirmations)" % (Transactions.deposit_address(acct), Config.config["confirmations"]))
commands["deposit"] = deposit

def parse_amount(s, acct, all_offset = 0, min_amount = 1, integer_only = True):
	if s.lower() == "all":
		return max(Transactions.balance(acct) + all_offset, 1)
	else:
		try:
			amount = float(s)
			if math.isnan(amount):
				raise ValueError
		except ValueError:
			raise ValueError(repr(s) + " - invalid amount")
		if amount > 1e12:
			raise ValueError(repr(s) + " - invalid amount (value too large)")
		if amount < min_amount:
			raise ValueError(repr(s) + " - invalid amount (must be 1 or more)")
		if integer_only and not int(amount) == amount:
			raise ValueError(repr(s) + " - invalid amount (should be integer)")
		if len(str(float(amount)).split(".")[1]) > 8:
			raise ValueError(repr(s) + " - invalid amount (max 8 digits)")
		if integer_only:
			return int(amount)
		else:
			return amount

def is_soak_ignored(account):
	if "soakignore" in Config.config:
		return Config.config["soakignore"].get(account.lower(), False)
	else:
		return False

def withdraw(req, arg):
	"""%withdraw <address> [amount] - Sends 'amount' coins to the specified dogecoin address. If no amount specified, sends the whole balance"""
	if len(arg) == 0:
		return req.reply(gethelp("withdraw"))
	acct = Irc.account_names([req.nick])[0]
	if not acct:
		return req.reply_private("You are not identified with freenode services (see /msg NickServ help)")
	if Transactions.lock(acct):
		return req.reply_private("Your account is currently locked")
	if len(arg) == 1:
		amount = max(Transactions.balance(acct) - 1, 1)
	else:
		try:
			amount = parse_amount(arg[1], acct, all_offset = -1)
		except ValueError as e:
			return req.reply_private(str(e))
	to = arg[0]
	if not Transactions.verify_address(to):
		return req.reply_private(to + " doesn't seem to be a valid dogecoin address")
	token = Logger.token()
	try:
		tx = Transactions.withdraw(token, acct, to, amount)
		req.reply("Coins have been sent, see http://dogechain.info/tx/%s [%s]" % (tx, token))
	except Transactions.NotEnoughMoney:
		req.reply_private("You tried to withdraw Ɖ%i (+Ɖ1 TX fee) but you only have Ɖ%i" % (amount, Transactions.balance(acct)))
	except Transactions.InsufficientFunds:
		req.reply("Something went wrong, report this to mniip [%s]" % (token))
		Logger.irclog("InsufficientFunds while executing '%s' from '%s'" % (req.text, req.nick))
commands["withdraw"] = withdraw

def target_nick(target):
	return target.split("@", 1)[0]

def target_verify(target, accname):
	s = target.split("@", 1)
	if len(s) == 2:
		return Irc.equal_nicks(s[1], accname)
	else:
		return True

def tip(req, arg):
	"""%tip <target> <amount> - Sends 'amount' coins to the specified nickname. Nickname can be suffixed with @ and an account name, if you want to make sure you are tipping the correct person"""
	if len(arg) < 2:
		return req.reply(gethelp("tip"))
	to = arg[0]
	acct, toacct = Irc.account_names([req.nick, target_nick(to)])
	if not acct:
		return req.reply_private("You are not identified with freenode services (see /msg NickServ help)")
	if Transactions.lock(acct):
		return req.reply_private("Your account is currently locked")
	if not toacct:
		if toacct == None:
			return req.reply_private(target_nick(to) + " is not online")
		else:
			return req.reply_private(target_nick(to) + " is not identified with freenode services")
	if not target_verify(to, toacct):
		return req.reply_private("Account name mismatch")
	try:
		amount = parse_amount(arg[1], acct)
	except ValueError as e:
		return req.reply_private(str(e))
	token = Logger.token()
	try:
		Transactions.tip(token, acct, toacct, amount)
		if Irc.equal_nicks(req.nick, req.target):
			req.reply("Done [%s]" % (token))
		else:
			req.say("Such %s tipped much Ɖ%i to %s! (to claim /msg %s help) [%s]" % (req.nick, amount, target_nick(to), req.instance, token))
		req.privmsg(target_nick(to), "Such %s has tipped you Ɖ%i (to claim /msg %s help) [%s]" % (req.nick, amount, req.instance, token), priority = 10)
	except Transactions.NotEnoughMoney:
		req.reply_private("You tried to tip Ɖ%i but you only have Ɖ%i" % (amount, Transactions.balance(acct)))
commands["tip"] = tip

def mtip(req, arg):
	"""%mtip <targ1> <amt1> [<targ2> <amt2> ...] - Send multiple tips at once"""
	if not len(arg) or len(arg) % 2:
		return req.reply(gethelp("mtip"))
	acct = Irc.account_names([req.nick])[0]
	if not acct:
		return req.reply_private("You are not identified with freenode services (see /msg NickServ help)")
	if Transactions.lock(acct):
		return req.reply_private("Your account is currently locked")
	for i in range(0, len(arg), 2):
		try:
			arg[i + 1] = parse_amount(arg[i + 1], acct)
		except ValueError as e:
			return req.reply_private(str(e))
	targets = []
	amounts = []
	total = 0
	for i in range(0, len(arg), 2):
		target = arg[i]
		amount = arg[i + 1]
		found = False
		for i in range(len(targets)):
			if Irc.equal_nicks(targets[i], target):
				amounts[i] += amount
				total += amount
				found = True
				break
		if not found:
			targets.append(target)
			amounts.append(amount)
			total += amount
	balance = Transactions.balance(acct)
	if total > balance:
		return req.reply_private("You tried to tip Ɖ%i but you only have Ɖ%i" % (total, balance))
	accounts = Irc.account_names([target_nick(target) for target in targets])
	totip = {}
	failed = ""
	tipped = ""
	for i in range(len(targets)):
		if accounts[i] == None:
			failed += " %s (offline)" % (target_nick(targets[i]))
		elif accounts[i] == False:
			failed += " %s (unidentified)" % (target_nick(targets[i]))
		elif not target_verify(targets[i], accounts[i]):
			failed += " %s (mismatch)" % (targets[i])
		else:
			totip[accounts[i]] = totip.get(accounts[i], 0) + amounts[i]
			tipped += " %s %d" % (target_nick(targets[i]), amounts[i])
	token = Logger.token()
	try:
		Transactions.tip_multiple(token, acct, totip)
		tipped += " [%s]" % (token)
	except Transactions.NotEnoughMoney:
		return req.reply_private("You tried to tip Ɖ%i but you only have Ɖ%i" % (total, Transactions.balance(acct)))
	output = "Tipped:" + tipped
	if len(failed):
		output += "  Failed:" + failed
	req.reply(output)
commands["mtip"] = mtip

def active(req, arg):
        """%active [minutes] - Lists out number of active users over past [x] minutes (default 10)"""
        acct = Irc.account_names([req.nick])[0]
        if not acct:
                return req.reply_private("You are not identified with freenode services (see /msg NickServ help)")
        for i in range(0, len(arg), 1):
                try:
                        arg[i] = parse_amount(arg[i], acct)
                except ValueError as e:
                        return req.reply_private(str(e))
        activeseconds = 600
        if len(arg) > 0:
                activeseconds = int(arg[0]) * 60
        if activeseconds < 60:
                activeseconds = 600
        elif activeseconds > 86400:
                activeseconds = 86400
        curtime = time.time()
        targets = []
        for oneactive in Global.account_cache[req.target].keys():
                try:
                        curactivetime = curtime - Global.active_list[req.target][oneactive]
                except:
                        curactivetime = -1
                if oneactive != None and oneactive != acct and oneactive != req.nick and oneactive not in targets and not is_soak_ignored(oneactive) and curactivetime > 0 and curactivetime < activeseconds:
                        targets.append(oneactive)
        output = "I see %d eligible active users in the past %d minutes." % (len(targets),int(activeseconds/60))
        req.reply(output)
commands["active"] = active

def soak(req, arg):
        """%soak <amt> [minutes] - Sends each active user an equal share of soaked amount"""
        if not len(arg) or len(arg) % 1:
                return req.reply(gethelp("soak"))
        acct = Irc.account_names([req.nick])[0]
        if not acct:
                return req.reply_private("You are not identified with freenode services (see /msg NickServ help)")
        if Transactions.lock(acct):
                return req.reply_private("Your account is currently locked")
        for i in range(0, len(arg), 1):
                try:
                        arg[i] = parse_amount(arg[i], acct)
                except ValueError as e:
                        return req.reply_private(str(e))
        activeseconds = 600
        if len(arg) > 1:
                activeseconds = int(arg[1]) * 60
        if activeseconds < 60:
                activeseconds = 600
        elif activeseconds > 86400:
                activeseconds = 86400
        curtime = time.time()
        targets = []
        targetnicks = []
        failed = ""
        for oneactive in Global.account_cache[req.target].keys():
                try:
                        curactivetime = curtime - Global.active_list[req.target][oneactive]
                except:
                        curactivetime = -1 # if not found default to expired
                target = oneactive
                if target != None and target != acct and target != req.nick and target != req.instance and target not in targets and not is_soak_ignored(target) and curactivetime > 0 and curactivetime < activeseconds:
                        targets.append(target)
                        if Irc.getacctnick(target) and not Global.acctnick_list[target] == None:
                                targetnicks.append(str(Global.acctnick_list[target]))
                        else:
                                targetnicks.append(str(target))

        MinActive = 1
        if len(targets) < MinActive:
                return req.reply("This place seems dead. (Maybe try specifying more minutes..)")
        accounts = Irc.account_names(targetnicks)
        failedcount = 0
        # we need a count of how many will fail to do calculations so pre-loop list
        for i in range(len(accounts)):
                if not accounts[i] or accounts[i] == None:
                        Global.account_cache.setdefault(req.target, {})[targetnicks[i]] = None
                        failedcount += 1
        scraps = 0
        amount = int(arg[0] / (len(targets) - failedcount))
        total = (len(targets) - failedcount) * amount
        scraps = int(arg[0]) - total
        if scraps <= 0:
                scraps = 0
        balance = Transactions.balance(acct)
        if total <= 0:
                return req.reply("Unable to soak (Not enough to go around, Ɖ%d Minimum)" % (len(targets) - failedcount))
        if total + scraps > balance:
                return req.reply_private("You tried to soak %.0f %s but you only have %.0f %s" % (total+scraps, Config.config["coinab"], balance, Config.config["coinab"]))
        totip = {}
        tipped = ""
        for i in range(len(accounts)):
                if accounts[i]:
                        totip[accounts[i]] = amount
                        tipped += " %s" % (targetnicks[i])
                elif accounts[i] == None:
                        failed += " %s (o)" % (targetnicks[i])
                else:
                        failed += " %s (u)" % (targetnicks[i])

        # special case where bot isn't included in soak but there are scraps
        if req.instance not in accounts and scraps > 0:
                totip[req.instance] = scraps
                tipped += " %s (%d scraps)" % (req.instance, scraps)

        token = Logger.token()
        try:
                Transactions.tip_multiple(token, acct, totip)
        except Transactions.NotEnoughMoney:
                return req.reply_private("You tried to soak %.0f %s but you only have %.0f %s" % (total, Config.config["coinab"], Transactions.balance(acct), Config.config["coinab"]))
        output = "%s is soaking %d users with %d %s:" % (req.nick, len(targets), amount, Config.config["coinab"])
        tippednicks = tipped.strip().split(" ")
        # only show nicks if not too many active, if large enough total (default 1 to always show or change), if nick list changed or if enough time has passed
        if len(tippednicks) > 100 or total + scraps < 1 or ((acct in Global.nicks_last_shown and Global.nicks_last_shown[acct] == tipped) and (acct+":last" in Global.nicks_last_shown and curtime < Global.nicks_last_shown[acct+":last"] + 600)):
                output += " (See previous nick list ) [%s]" % (token)
        else:
                for onetipped in tippednicks:
                        if onetipped:
                                if len(output) < 250:
                                        output += " " + onetipped
                                else:
                                        req.reply(output)
                                        output = " " + onetipped
                Global.nicks_last_shown[acct] = tipped
                Global.nicks_last_shown[acct+":last"] = curtime
        req.say(output)
        Logger.log("c","SOAK %s %s skipped: %s" % (token, repr(targetnicks), repr(failed)))
commands["soak"] = soak

def soakignore(req, arg):
        """%soakignore <acct> [add/del] - Ignore ACCOUNT (not nick) from soak/rain/etc. Requires manual admin save to be perm"""
        if not len(arg) or len(arg) % 1:
                return req.reply(gethelp("soakignore"))
        acct = Irc.account_names([req.nick])[0]
        if not acct:
                return req.reply_private("You are not identified with freenode services (see /msg NickServ help)")
        if not Irc.is_admin(req.source):
                return req.reply_private("You are not authorized to use this command")
        if not "soakignore" in Config.config:
                Config.config['soakignore'] = {}
        if len(arg) > 1 and arg[1] == "del":
                Config.config["soakignore"].pop(arg[0].lower(), False)
        elif len(arg) > 1 and arg[1] == "add":
                Config.config['soakignore'].update({arg[0].lower():True})
        if not is_soak_ignored(arg[0]):
                output = arg[0] + " is NOT ignored."
        else:
                output = arg[0] + " is ignored."
        req.reply(output)
commands["soakignore"] = soakignore

def donate(req, arg):
	"""%donate <amount> - Donate 'amount' coins to help fund the server Doger is running on"""
	if len(arg) < 1:
		return req.reply(gethelp("donate"))
	acct = Irc.account_names([req.nick])[0]
	if not acct:
		return req.reply_private("You are not identified with freenode services (see /msg NickServ help)")
	if Transactions.lock(acct):
		return req.reply_private("Your account is currently locked")
	toacct = "@DONATIONS"
	try:
		amount = parse_amount(arg[0], acct)
	except ValueError as e:
		return req.reply_private(str(e))
	token = Logger.token()
	try:
		Transactions.tip(token, acct, toacct, amount)
		req.reply("Donated Ɖ%i, thank you very much for your donation [%s]" % (amount, token))
	except Transactions.NotEnoughMoney:
		req.reply_private("You tried to donate Ɖ%i but you only have Ɖ%i" % (amount, Transactions.balance(acct)))
commands["donate"] = donate

def gethelp(name):
	if name[0] == Config.config["prefix"]:
		name = name[1:]
	cmd = commands.get(name, None)
	if cmd and cmd.__doc__:
		return cmd.__doc__.split("\n")[0].replace("%", Config.config["prefix"])

def _help(req, arg):
	"""%help - list of commands; %help <command> - help for specific command"""
	if len(arg):
		h = gethelp(arg[0])
		if h:
			req.reply(h)
	else:
		if not Irc.equal_nicks(req.target, req.nick):
			return req.reply("I'm " + req.instance + ", an IRC dogecoin tipbot. For more info do /msg " + req.instance + " help")
		acct = Irc.account_names([req.nick])[0]
		if acct:
			ident = "you're identified as \2" + acct + "\2"
		else:
			ident = "you're not identified"
		# List of commands to not show users in help
		hidecmd = ["as", "admin"]
		allcmd = ""
		sortedcmd = OrderedDict(sorted(commands.items(), key=operator.itemgetter(0)))
		for onecmd in sortedcmd:
			if not onecmd in hidecmd:
				allcmd += Config.config["prefix"][0] + onecmd + " "
		req.say("I'm " + req.instance + ", I'm an IRC dogecoin tipbot. To get help about a specific command, say \2%help <command>\2  Commands: ".replace("%", Config.config["prefix"])+ allcmd)
		req.say(("Note that to receive or send tips you should be identified with freenode services (%s). Please consider donating with %%donate. For any support questions, including those related to lost coins, join ##doger" % (ident)).replace("%", Config.config["prefix"]))
commands["help"] = _help

def admin(req, arg):
	"""
	admin"""
	if len(arg):
		command = arg[0]
		arg = arg[1:]
		if command == "reload":
			for mod in arg:
				reload(sys.modules[mod])
			req.reply("Reloaded")
		elif command == "exec" and Config.config.get("enable_exec", None):
			try:
				exec(" ".join(arg).replace("$", "\n"))
			except Exception as e:
				type, value, tb = sys.exc_info()
				Logger.log("ce", "ERROR in " + req.instance + " : " + req.text)
				Logger.log("ce", repr(e))
				Logger.log("ce", "".join(traceback.format_tb(tb)))
				req.reply(repr(e))
				req.reply("".join(traceback.format_tb(tb)).replace("\n", " || "))
				del tb
		elif command == "ignore":
			Irc.ignore(arg[0], int(arg[1]))
			req.reply("Ignored")
		elif command == "die":
			for instance in Global.instances:
				Global.manager_queue.put(("Disconnect", instance))
			Global.manager_queue.join()
			Blocknotify.stop()
			Global.manager_queue.put(("Die",))
		elif command == "restart":
			for instance in Global.instances:
				Global.manager_queue.put(("Disconnect", instance))
			Global.manager_queue.join()
			Blocknotify.stop()
			os.execv(sys.executable, [sys.executable] + sys.argv)
		elif command == "manager":
			for cmd in arg:
				Global.manager_queue.put(cmd.split("$"))
			req.reply("Sent")
		elif command == "raw":
			Irc.instance_send(req.instance, eval(" ".join(arg)))
		elif command == "config":
			if arg[0] == "save":
				os.rename("Config.py", "Config.py.bak")
				with open("Config.py", "w") as f:
					f.write("config = " + pprint.pformat(Config.config) + "\n")
				req.reply("Done")
			elif arg[0] == "del":
				exec("del Config.config " + " ".join(arg[1:]))
				req.reply("Done")
			else:
				try:
					req.reply(repr(eval("Config.config " + " ".join(arg))))
				except SyntaxError:
					exec("Config.config " + " ".join(arg))
					req.reply("Done")
		elif command == "join":
			Irc.instance_send(req.instance, ("JOIN", arg[0]), priority = 0.1)
		elif command == "part":
			Irc.instance_send(req.instance, ("PART", arg[0]), priority = 0.1)
		elif command == "caches":
			acsize = 0
			accached = 0
			with Global.account_lock:
				for channel in Global.account_cache:
					for user in Global.account_cache[channel]:
						acsize += 1
						if Global.account_cache[channel][user] != None:
							accached += 1
			acchannels = len(Global.account_cache)
			whois = " OK"
			whoisok = True
			for instance in Global.instances:
				tasks = Global.instances[instance].whois_queue.unfinished_tasks
				if tasks:
					if whoisok:
						whois = ""
						whoisok = False
					whois += " %s:%d!" % (instance, tasks)
			req.reply("Account caches: %d user-channels (%d cached) in %d channels; Whois queues:%s" % (acsize, accached, acchannels, whois))
		elif command == "channels":
			inss = ""
			for instance in Global.instances:
				chans = []
				with Global.account_lock:
					for channel in Global.account_cache:
						if instance in Global.account_cache[channel]:
							chans.append(channel)
				inss += " %s:%s" % (instance, ",".join(chans))
			req.reply("Instances:" + inss)
		elif command == "balances":
			database, dogecoind = Transactions.balances()
			req.reply("Dogecoind: %.8f; Database: %.8f" % (dogecoind, database))
		elif command == "blocks":
			info, hashd = Transactions.get_info()
			hashb = Transactions.lastblock.encode("ascii")
			req.reply("Best block: " + hashd + ", Last tx block: " + hashb + ", Blocks: " + str(info.blocks) + ", Testnet: " + str(info.testnet))
		elif command == "lock":
			if len(arg) > 1:
				if arg[1] == "on":
					Transactions.lock(arg[0], True)
				elif arg[1] == "off":
					Transactions.lock(arg[0], False)
				req.reply("Done")
			elif len(arg):
				req.reply("locked" if Transactions.lock(arg[0]) else "not locked")
		elif command == "ping":
			t = time.time()
			Irc.account_names(["."])
			pingtime = time.time() - t
			acc = Irc.account_names([req.nick])[0]
			t = time.time()
			Transactions.balance(acc)
			dbreadtime = time.time() - t
			t = time.time()
			Transactions.lock(acc, False)
			dbwritetime = time.time() - t
			t = time.time()
			Transactions.ping()
			rpctime = time.time() - t
			req.reply("Ping: %f, DB read: %f, DB write: %f, RPC: %f" % (pingtime, dbreadtime, dbwritetime, rpctime))

commands["admin"] = admin

def _as(req, arg):
	"""
	admin"""
	_, target, text = req.text.split(" ", 2)
	if target[0] == '@':
		Global.account_cache[""] = {"@": target[1:]}
		target = "@"
	if text.find(" ") == -1:
		command = text
		args = []
	else:
		command, args = text.split(" ", 1)
		args = [a for a in args.split(" ") if len(a) > 0]
	if command[0] != '_':
		cmd = commands.get(command.lower(), None)
		if not cmd.__doc__ or cmd.__doc__.find("admin") == -1 or Irc.is_admin(source):
			if cmd:
				req = Hooks.FakeRequest(req, target, text)
				Hooks.run_command(cmd, req, args)
	if Global.account_cache.get("", None):
		del Global.account_cache[""]
commands["as"] = _as
