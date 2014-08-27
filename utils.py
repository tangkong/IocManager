######################################################################
#
# Exported API routines:
#
# getBaseName(iocName)
#     Return the basename of the iocAdmin PVs for a particular IOC.
#
# fixdir(rundir, iocName)
#     Abbreviate the running directory of an IOC by making it relative
#     to EPICS_SITE_TOP and removing the final "build" or "iocBoot"
#     portion of the path.
#
# check_status(host, port, id)
#     Check the health of an IOC, returning a dictionary with status,
#     pid, id, autorestart, and rdir.
#
# killProc(host, port)
#     Kill the IOC at the given location.
#
# restartProc(host, port)
#     Restart the IOC at the given location.
#
# startProc(hutch, entry)
#     entry is a configuration dictionary entry that should be started
#     for a particular hutch.
#
# readConfig(hutch, time=None)
#     Read the configuration file for a given hutch if newer than time.
#     Return None on failure or no change, otherwise a tuple: (filetime,
#     configlist, hostlist).  filetime is the modification time of the
#     configuration, configlist is a list of dictionaries containing
#     an IOC configuration, and hostlist is a (hint) list of hosts in
#     this hutch.
#
# readStatusDir(hutch, readfile)
#     Read the status directory for a particular hutch, returning a list
#     of dictionaries containing updated information.  The readfile parameter
#     is a function passed a filepath and the IOC name.  This should read
#     any updated information, returning a list of lines or an empty list
#     if the file was not read.  The default readfile always reads everything.
#
# applyConfig(hutch)
#     Apply the current configuration for the specified hutch.
#
######################################################################


import telnetlib, string, datetime, os, time, fcntl
from re import search

#
# Defines
#
CAMRECORDER = "/reg/g/pcds/controls/camrecord"
PROCSERV    = "/reg/g/pcds/package/procServ-2.5.1/procServ"
STARTUP_DIR = "/reg/g/pcds/pyps/apps/ioc/latest/"
CONFIG_FILE = "/reg/g/pcds/pyps/config/%s/iocmanager.cfg"
AUTH_FILE   = "/reg/g/pcds/pyps/config/%s/iocmanager.auth"
STATUS_DIR  = "/reg/g/pcds/pyps/config/.status/%s"
LOGBASE     = "/reg/d/iocData/%s/iocInfo/ioc.log*"
LOGFILE     = "/reg/d/iocData/%s/iocInfo/ioc.log_" + datetime.datetime.today().strftime("%m%d%Y_%H%M%S")
PVFILE      = "/reg/d/iocData/%s/iocInfo/IOC.pvlist"
BASEPORT    = 29000

STATUS_INIT      = "INITIALIZE WAIT"
STATUS_NOCONNECT = "NOCONNECT"
STATUS_RUNNING   = "RUNNING"
STATUS_SHUTDOWN  = "SHUTDOWN"
STATUS_ERROR     = "ERROR"

CONFIG_NORMAL    = 0
CONFIG_ADDED     = 1
CONFIG_DELETED   = 2

# messages expected from procServ
MSG_BANNER_END = "server started at"
MSG_ISSHUTDOWN = "is SHUT DOWN"
MSG_ISSHUTTING = "is shutting down"
MSG_KILLED     = "process was killed"
MSG_RESTART = "new child"
MSG_PROMPT = "\x0d\x0a> "
MSG_SPAWN = "procServ: spawning daemon"
MSG_AUTORESTART_IS_ON = "auto restart is ON"
MSG_AUTORESTART_TO_ON = "auto restart to ON"
MSG_AUTORESTART_TO_OFF = "auto restart to OFF"

EPICS_TOP      = "/reg/g/pcds/package/epics/"
EPICS_SITE_TOP = "/reg/g/pcds/package/epics/3.14/"

######################################################################
#
# Name and Directory Utilities
#

#
# Given an IOC name, find the base PV name.
#
def getBaseName(ioc):
    try:
        lines = open(PVFILE % ioc).readlines()
        for l in lines:
            pv = l.split(",")[0]
            if pv[-10:] == ":HEARTBEAT":
                return pv[:-10]
    except:
        pass
    return None

#
# Given a full path and an IOC name, return a path relative
# to EPICS_SITE_TOP without the final "iocBoot".
#
def fixdir(dir, id):
    if dir[0:len(EPICS_SITE_TOP)] == EPICS_SITE_TOP:
        dir = dir[len(EPICS_SITE_TOP):]
    if dir[0:len(EPICS_TOP)] == EPICS_TOP:
        dir = "../" + dir[len(EPICS_TOP):]
    try:
        ext = "/build/iocBoot/" + id
        if dir[len(dir)-len(ext):len(dir)] == ext:
            dir = dir[0:len(dir)-len(ext)]
    except:
        pass
    try:
        ext = "/iocBoot/" + id
        if dir[len(dir)-len(ext):len(dir)] == ext:
            dir = dir[0:len(dir)-len(ext)]
    except:
        pass
    return dir


######################################################################
#
# Telnet/Procserv Utilities
#

#
# Read and parse the connection information from a new telnet connection.
# Returns a dictionary of information.
#
def readLogPortBanner(tn):
    response = tn.read_until(MSG_BANNER_END, 1)
    if not string.count(response, MSG_BANNER_END):
        print response
        return {'status'      : STATUS_ERROR,
                'pid'         : "-",
                'id'          : "-",
                'autorestart' : False,
                'rdir'        : "/tmp"}
    if search('SHUT DOWN', response):
        tmpstatus = STATUS_SHUTDOWN
        pid = "-"
    else:
        tmpstatus = STATUS_RUNNING
        pid = search('@@@ Child \"(.*)\" PID: ([0-9]*)', response).group(2)
    getid = search('@@@ Child \"(.*)\" start', response).group(1)
    dir   = search('@@@ Server startup directory: (.*)', response).group(1)
    if dir[-1] == '\r':
        dir = dir[:-1]
    if search(MSG_AUTORESTART_IS_ON, response):
        arst = True
    else:
        arst = False
    return {'status'      : tmpstatus,
            'pid'         : pid,
            'id'          : getid,
            'autorestart' : arst,
            'rdir'        : fixdir(dir, getid)}

#
# Returns a dictionary with status information for a given host/port.
#
def check_status(host, port, id):
    try:
        tn = telnetlib.Telnet(host, port, 1)
    except:
        return {'status'      : STATUS_NOCONNECT,
                'id'          : id,
                'pid'         : "-",
                'autorestart' : False,
                'rdir'        : "/tmp"}
    result = readLogPortBanner(tn)
    tn.close()
    return result

def openTelnet(host, port):
    connected = False
    telnetCount = 0
    while (not connected) and (telnetCount < 2):
        telnetCount += 1
        try:
            tn = telnetlib.Telnet(host, port, 1)
        except:
            time.sleep(0.25)
        else:
            connected = True
    if connected:
        return tn
    else:
        return None

def killProc(host, port):
    print "Killing IOC on host %s, port %s..." % (host, port)
    tn = openTelnet(host, port)

    if tn:
        statd = readLogPortBanner(tn)

        if statd['status'] == STATUS_RUNNING:
            try:
                if statd['autorestart']:
                    # send ^T to toggle off auto restart.
                    tn.write("\x14")
                    # wait for toggled message
                    r = tn.read_until(MSG_AUTORESTART_TO_OFF, 1)
                    time.sleep(0.25)
                    
                # send ^X to kill child process
                tn.write("\x18");
                # wait for killed message
                r = tn.read_until(MSG_KILLED, 1)
                time.sleep(0.25)
                
                # send ^Q to kill procServ
                tn.write("\x11");
            except:
                pass # What to do???

        tn.close()
    else:
        print 'ERROR: killProc() telnet to %s port %s failed' % (host, port)

def restartProc(host, port):
    print "Restarting IOC on host %s, port %s..." % (host, port)
    tn = openTelnet(host, port)
    started = False

    if tn:
        statd = readLogPortBanner(tn)

        if statd['status'] == STATUS_RUNNING:
            try:
                # send ^X to kill child process
                tn.write("\x18");

                # wait for killed message
                r = tn.read_until(MSG_KILLED, 1)
                time.sleep(0.25)
            except:
                pass # What do we do now?!?

        if not statd['autorestart']:
            # send ^R to restart child process
            tn.write("\x12");

        # wait for restart message
        r = tn.read_until(MSG_RESTART, 1)
        if not string.count(r, MSG_RESTART):
            print 'ERROR: no restart message... '
        else:
            started = True

        tn.close()
    else:
        print 'ERROR: restartProc() telnet to %s port %s failed' % (host, port)

    return started

def startProc(cfg, entry):
    # Hopefully, we can dispose of this soon!
    platform = '1'
    if cfg == 'fee':
        platform = '2'
    if cfg == 'las':
        platform = '3'

    host  = entry['host']
    port  = entry['port']
    name  = entry['id']
    try:
        cmd = entry['cmd']
    except:
        # The New Regime: no cmd --> invoke startProc.
        sr = os.getenv("SCRIPTROOT")
        if sr == None:
            sr = STARTUP_DIR
        elif sr[-1] != '/':
            sr += '/'
        cmd = sr + "startProc " + name + " " + str(port) + " " + cfg
    try:
        if 'u' in entry['flags']:
            # The Old Regime: supply a command, and possibly flag it with 'u'
            # to append the ID to the command.
            cmd += ' -u ' + name
    except:
        pass
    log = LOGFILE % name
    ctrlport = BASEPORT + 100 * int(platform)
    print "Starting %s on port %s of host %s, platform %s..." % (name, port, host, platform)
    cmd = '%s --logfile %s --name %s --allow --coresize 0 %s %s' % \
          (PROCSERV, log, name, port, cmd)
    if int(entry['delay']) != 0:
        cmd += "; sleep %s" % str(entry['delay'])
    try:
        tn = telnetlib.Telnet(host, BASEPORT + 100 * int(platform), 1)
    except:
        print "ERROR: telnet to procmgr (%s port %d) failed" % (host, ctrlport)
        print ">>> Please start the procServ process on host %s!" % host
    else:
        # telnet succeeded

        # send ^U followed by carriage return to safely reach the prompt
        tn.write("\x15\x0d");

        # wait for prompt (procServ)
        statd = tn.read_until(MSG_PROMPT, 2)
        if not string.count(statd, MSG_PROMPT):
            print 'ERROR: no prompt at %s port %s' % (host, ctrlport)
            
        # send command
        tn.write('%s\n' % cmd);

        # wait for prompt
        statd = tn.read_until(MSG_PROMPT, 2)
        if not string.count(statd, MSG_PROMPT):
            print 'ERR: no prompt at %s port %s' % (host, ctrlport)

        # close telnet connection
        tn.close()

######################################################################
#
# Configuration/Status Utilities
#

#
# Reads a hutch configuration file and returns a tuple:
#     (filetime, configlist, hostlist).
#
def readConfig(cfg, time = None):
    config = {'procmgr_config': None, 'hosts': None, 'dir':'dir',
              'id':'id', 'cmd':'cmd', 'flags':'flags', 'port':'port', 'host':'host',
              'disable':'disable', 'history':'history', 'delay' : 'delay' }
    f = open(CONFIG_FILE % cfg, "r")
    fcntl.lockf(f, fcntl.LOCK_SH)    # Wait for the lock!!!!
    try:
        mtime = os.stat(CONFIG_FILE % cfg).st_mtime
        if time != None and time == mtime:
            raise Exception
        execfile(CONFIG_FILE % cfg, {}, config)
        res = (mtime, config['procmgr_config'], config['hosts'])
    except:
        res = None
    fcntl.lockf(f, fcntl.LOCK_UN)
    f.close()
    if res == None:
        return None
    for l in res[1]:
        # Add defaults!
        if not 'disable' in l.keys():
            l['disable'] = False
        if not 'delay' in l.keys():
            l['delay'] = 0
        if not 'history' in l.keys():
            l['history'] = []
        l['cfgstat'] = CONFIG_NORMAL
        l['rdir'] = l['dir']
        l['rhost'] = l['host']
        l['rport'] = l['port']
        l['newstyle'] = False
    return res

#
# Reads the status directory for a hutch, looking for changes.  The newer
# parameter is a routine that is called as newer(iocname, mtime) which
# returns True if the file has been modified since last read.  In this
# case, newer should also remember mtime as the last read time.
#
# Returns a list of dictionaries containing the new information.
#
def readStatusDir(cfg, readfile=lambda fn, f: open(fn).readlines()):
    files = os.listdir(STATUS_DIR % cfg)
    d = []
    for f in files:
        fn = (STATUS_DIR % cfg) + "/" + f
        l = readfile(fn, f)
        if l != []:
            stat = l[0].strip().split()                     # PID HOST PORT DIRECTORY
            d.append({'id' : f, 'pid': stat[0], 'rhost': stat[1], 'rport': int(stat[2]),
                      'rdir': stat[3], 'newstyle' : True})
    return d

#
# Apply the current configuration.
#
def applyConfig(cfg):
  result = readConfig(cfg)
  if result == None:
      print "Cannot read configuration for %s!" % cfg
      return -1
  (mtime, cfglist, hostlist) = result

  config = {}
  for l in cfglist:
    config[l['id']] = l

  runninglist = readStatusDir(cfg)

  current = {}
  for l in runninglist:
      result = check_status(l['rhost'], l['rport'], l['id'])
      if result['status'] == STATUS_RUNNING:
          rdir = l['rdir']
          l.update(result);
          if l['rdir'] == '/tmp':
              l['rdir'] = rdir
          else:
              l['newstyle'] = False
          current[l['id']] = l

  running = current.keys()
  wanted  = config.keys()

  # Double-check for old-style IOCs that don't have an indicator file!
  for l in wanted:
      if not l in running:
          result = check_status(config[l]['host'], int(config[l]['port']), config[l]['id'])
          if result['status'] == STATUS_RUNNING:
              result.update({'rhost': config[l]['host'],
                             'rport': config[l]['port'],
                             'newstyle': False})
              current[l] = result

  running = current.keys()
  wanted = [l for l in wanted if not config[l]['disable']]

  # Camera recorders always seem to be in the wrong directory, so cheat!
  for l in cfglist:
      if l['dir'] == CAMRECORDER:
          try:
              current[l['id']]['rdir'] = CAMRECORDER
          except:
              pass

  #
  # Now, we need to make three lists: kill, restart, and start.
  #
  
  # Kill anyone who we don't want, or is running on the wrong host or port, or is oldstyle and needs
  # an upgrade.
  kill_list    = [l for l in running if not l in wanted or current[l]['rhost'] != config[l]['host'] or
                  current[l]['rport'] != config[l]['port'] or
                  (not current[l]['newstyle'] and current[l]['rdir'] != config[l]['dir'])]
                  
  # Start anyone who wasn't running, or was running on the wrong host or port, or is oldstyle and needs
  # an upgrade.
  start_list   = [l for l in wanted if not l in running or current[l]['rhost'] != config[l]['host'] or
                  current[l]['rport'] != config[l]['port'] or
                  (not current[l]['newstyle'] and current[l]['rdir'] != config[l]['dir'])]

  # Anyone running the wrong version, newstyle, on the right host and port just needs a restart.
  restart_list = [l for l in wanted if l in running and current[l]['rhost'] == config[l]['host'] and
                  current[l]['newstyle'] and current[l]['rport'] == config[l]['port'] and
                  current[l]['rdir'] != config[l]['dir']]
  
  for l in kill_list:
    killProc(current[l]['rhost'], int(current[l]['rport']))
    try:
        # This is dead, so get rid of the status file!
        os.unlink((STATUS_DIR % cfg) + "/" + l)
    except:
        pass

  for l in start_list:
    startProc(cfg, config[l])

  for l in restart_list:
    restartProc(current[l]['rhost'], int(current[l]['rport']))

  time.sleep(1)
  return 0

######################################################################
#
# Authorization utilities
#

authinfo = {}

def check_auth(user, hutch):
    if not hutch in authinfo.keys():
        lines = open(AUTH_FILE % hutch).readlines()
        lines = [l.strip() for l in lines]
        authinfo[hutch] = lines
    for l in authinfo[hutch]:
        if l == user:
            return True
    return False
