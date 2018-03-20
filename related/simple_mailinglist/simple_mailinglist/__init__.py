"""
Simple but extensible mailing list manager.

It works standalone, only processes mails when called (or when run as daemon),
uses a JSON-file per mailinglist for configuration and external programs to
receive/send mail.
No webinterface, no automatic subscribe/unsubscribe handling, no whistles and
bells. All it does is:

- read configuration from a JSON-file
  (and optionally extend it by a script to get some data e.g. from a database)
- read mails from a maildir-like directory

  - check if the sender is in the whitelist
  - check the mail-contents/format/size/attachments
  - if ok: mangle mail, add footer and write mail+recipients to an outbox
  - else: write a moderation-mail to an outbox and optionally
          write a notice to the sender to an outbox

- read moderator-answers from a maildir-like directory and
  forward accepted mails (like if they were on the whitelist)
- move processed mails to an other maildir-like directory
  (which could be cleaned up periodically)
- send all mails in the outbox
- log to logfile and/or syslog

Configuration: a JSON-file, containing::

    {
    "include" : "JSON_FILE_WITH_DEFAULT_VALUES" or [LIST, OF, SUCH, FILES],

    "listname"      : "MAILINGLIST_NAME",
    "address"       : "MAILINGLIST_ADDRESS",
    "admin_address" : "MAILINGLIST_ADMIN_ADDRESS",
    "sender"        : "MAILINGLIST_ENVELOPE_SENDER_ADDRESS",

    "list-owner"       : "URL_OR_EMAIL",
    "list-subscribe"   : "URL_OR_EMAIL",
    "list-unsubscribe" : "URL_OR_EMAIL",
    "list-help"        : "URL_OR_EMAIL",

    "footer" : "UNSUBSCRIBE_FOOTER_TEXT",

    "dir"             : "DIRECTORY_CONTAINING_THE_MAILS",
    "dir_done"        : "DIRECTORY_FOR_PROCESSED_MAILS",
    "admin_dir"       : "DIRECTORY_CONTAINING_ADMIN_MAILS",
    "admin_dir_done"  : "DIRECTORY_FOR_PROCESSED_ADMIN_MAILS",
    "outbox_dir"      : "DIRECTORY_FOR_THE_OUTBOX",
    "outbox_dir_done" : "DIRECTORY_FOR_THE_SENT_MAILS"

    "sendmail"               : "SENDMAIL_CMD",
    "sendmail_skip_errors"   : false,
    "sendmail_batch_maxrcpt" : 50,
    "sendmail_batch_wait"    : 1.0,

    "log_name"       : "LOGGER_NAME"
    "log_syslog"     : LEVEL,
    "log_file"       : "LOGFILE_FILENAME",
    "log_file_level" : LEVEL,

    "html" : "allow"|"forbid"|"convert"|"convert_strip",
    "size_min" : SIZE_IN_BYTES,
    "size_max" : SIZE_IN_BYTES,

    "DMARC" : "ignore"|"reject"|"append.INVALID"|"reply-to",
    "DMARC_template_reject" : "MAIL_TEMPLATE_FILE",

    "forbid_action": "moderate"|"reject",
    "template_reject"   : "MAIL_TEMPLATE_FILE",
    "template_moderate" : "MAIL_TEMPLATE_FILE",

#    "header_precedence" : "bulk",
#    "header_add"    : [...],
#    "header_keep"   : [...],
#    "header_remove" : [...],
#    "header_allow"  : [...],
#    "header_forbid" : [...],

#    "mime_keep"   : [...],
#    "mime_remove" : [...],
#    "mime_allow"  : [...],
#    "mime_forbid" : [...],

    "moderators"    : [MODERATOR, EMAIL, ADDRESSES],
    "subscribers"   : [ALL, SUBSCRIBED, MAIL, ADDRESSES],
    "whitelist"     : [WHITELISTED, SENDER, ADDRESSES],
    "whitelist_hashfile" : "FILE_CONTAINING_SHA256_HASHED_EMAIL_ADDRESSES",

    "extend_exec" : "SHELL_CMD_TO_RECEIVE_A_JSON_FILE_WHICH_EXTENDS_THESE_VALUES"
    }

The following fields are mandatory:

    - address
    - admin_address
    - sender
    - dir
    - dir_done
    - admin_dir
    - admin_dir_done
    - outbox_dir
    - sendmail
    - subscribers

All other fields are optional and use sensible defaults (see documentation).

:Version:   2.0

:Requires:  Python >= 3.4 (TODO: check), python3-html2text, host-command, Linux
:SeeAlso:   Python email module, RFC2822, RFC2369

:Author:    Roland Koebler <rk@simple-is-better.org>
:Copyright: Roland Koebler
:License:   MIT/X11-like, see __license__

:VCS:       $Id$
"""

__version__ = "2.0"
__author__  = "Roland Koebler <rk@simple-is-better.org>"            #pylint: disable=bad-whitespace
__license__ = """Copyright (c) Roland Koebler, 2011-2017

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
IN THE SOFTWARE."""

#-----------------------------------------
# import

import os
import logging
from logging.handlers import SysLogHandler, WatchedFileHandler
import time
import json
import hashlib
import socket
import subprocess
#import email
import email.policy
from email.parser import BytesParser
from email.message import EmailMessage
from html import escape as htmlescape

import html2text

from .validate import validate_dict, R_OK, RX_OK, RWX_OK
from .dmarc import dmarc

# TODO:
# - mangle()
# - cleanup()
# - check_contents()
# - check max. size before parsing a mail?
# - daemonzie:
#   - poll interval or inotify (import daemon, inotify)
#   - run-file?
#   - sighup handler?
# - DMARC-lookup + .INVALID / .DMARC-SUCKS.INVALID
# - use module "mailbox"?
# - mailfilter.py

#=========================================
# configuration specification

#----------------------
# default values

CFG_DEFAULT = {
    #"include" optional

    "listname"      : "",
    #"address"       required
    #"admin_address" required
    #"sender"        required

    "list-owner"       : "",
    "list-subscribe"   : "",
    "list-unsubscribe" : "",
    "list-help"        : "",

    "footer" : "",

    #"dir"             required
    #"dir_done"        required
    #"admin_dir"       required
    #"admin_dir_done"  required
    #"outbox_dir"      required
    "outbox_dir_done": "",

    #"sendmail"       required
    "sendmail_skip_errors"   : False,
    "sendmail_batch_maxrcpt" : 50,
    "sendmail_batch_wait"    : 1.0,

    "log_name"       : "simple_mailinglist",
    "log_syslog"     : logging.WARN,
    "log_file"       : "STDERR",
    "log_file_level" : logging.WARN,

    "html" : "forbid",
    "size_min" : 2,
    "size_max" : 1000000,

    "DMARC" : "append.DMARC-SUCKS.INVALID",
    "DMARC_template_reject" : "",

    "forbid_action": "moderate",
    "template_reject"   : "",
    "template_moderate" : "",

    "moderators"    : [],
    "subscribers"   : [],
    "whitelist"     : ["."],
    "whitelist_hashfile" : "",

    #"extend_exec"  optional
    }

#----------------------
# format specification

CFG_REQUIRED = [
    "address",
    "admin_address",
    "sender",
    "dir",
    "dir_done",
    "admin_dir",
    "admin_dir_done",
    "outbox_dir",
    "sendmail",
    "subscribers"
    ]

CFG_SCHEMA = {
    "include" : [(str, [""]), ("FILE", R_OK), (list, ("FILE", R_OK))],

    "listname"      : str,
    "address"       : "EMAIL",
    "admin_address" : "EMAIL",
    "sender"        : "EMAIL",

    "list-owner"       : ["EMAIL", "URL"],
    "list-subscribe"   : ["EMAIL", "URL"],
    "list-unsubscribe" : ["EMAIL", "URL"],
    "list-help"        : ["EMAIL", "URL"],

    "footer" : str,

    "dir"             : ("DIR", RWX_OK),
    "dir_done"        : ("DIR", RWX_OK),
    "admin_dir"       : ("DIR", RWX_OK),
    "admin_dir_done"  : ("DIR", RWX_OK),
    "outbox_dir"      : ("DIR", RWX_OK),
    "outbox_dir_done" : [(str, [""]), ("DIR", RWX_OK)],

    "sendmail"       : ("FILE", RX_OK),
    "sendmail_skip_errors"   : bool,
    "sendmail_batch_maxrcpt" : (int, 1, None),
    "sendmail_batch_wait"    : ([int, float], 0, None),

    "log_name"       : str,
    "log_syslog"     : int,
    "log_file"       : str,
    "log_file_level" : int,

    "html" : (str, ["allow", "forbid", "convert", "convert_strip"]),
    "size_min" : (int, 0, None),
    "size_max" : (int, 1, None),

    "DMARC" : (str, ["ignore", "reject", "append.INVALID", "reply-to"]),
    "DMARC_template_reject" : [(str, [""]), ("FILE", R_OK)],

    "forbid_action" : (str, ["moderate", "reject"]),
    "template_reject"   : [(str, [""]), ("FILE", R_OK)],
    "template_moderate" : [(str, [""]), ("FILE", R_OK)],

    "moderators"    : (list, "<EMAIL>"),
    "subscribers"   : (list, "<EMAIL>"),
    "whitelist"     : (list, "<EMAIL>"),
    "whitelist_hashfile" : [(str, [""]), ("FILE", R_OK)],

    "extend_exec" : str
    }

#=========================================
# default templates

TEMPLATE_MODERATE = """
Please moderate the attached mail:

- accept: To accept the attached message, please answer to this mail
  without modifying the subject (except for adding Re:/Aw:/...).
- otherwise: No action is necessary.

From:    {mail[from]}
Subject: {mail[subject]}
Size:    {size_kB} kB

The message is attached.
"""

#=========================================
# helper functions

def jsondict_loadf(filename):
    """Load JSON-object from a file with error-handling.

    :Parameters:
        - filename: name of the JSON-file
    :Returns:
        dict containing the JSON-data
    :Raises:
        IOError if the file cannot be read,
        ValueError if the file does not contain a valid JSON-object
    """
    if not os.path.isfile(filename):
        raise IOError("Configfile '%s' does not exist or is not a regular file." % filename)
    if not os.access(filename, os.R_OK):
        raise IOError("Configfile '%s': Permission denied." % filename)

    with open(filename, 'r') as f:
        try:
            cfg = json.load(f)
        except json.JSONDecodeError as err:
            raise ValueError("Configfile '%s' does not contain valid JSON. (%s)" % (filename, str(err)))
    if not isinstance(cfg, dict):
        raise ValueError("Configfile '%s' does not contain a JSON-object/dictionary." % filename)
    return cfg

def jsondict_loads(s):
    """Load JSON-object from a string with error-handling.

    :Parameters:
        - s: string containing JSON
    :Returns:
        dict containing the JSON-data
    :Raises:
        ValueError if the string does not contain a valid JSON-object
    """
    try:
        cfg = json.loads(s)
    except json.JSONDecodeError as err:
        raise ValueError("Config-string %s... does not contain valid JSON. (%s)" % (repr(s[:10]), str(err)))
    if not isinstance(cfg, dict):
        raise ValueError("Config-string %s... does not contain a JSON-object/dictionary." % repr(s[:10]))
    return cfg

def emailadr_parse(s):
    """Parse an email-address / from-field.

    - "SomeOne@example.com" -> "", "someone@example.com"
    - "Some One <SomeOne@example.com>" -> "Some One", "someone@example.com"

    :Parameters:
        - s: email-address/from-field-contents
    :Returns:
        name, lower-case-address
    """
    # TODO: enhance this, merge with emailadr_extract
    if "<" not in s:
        return "", s.lower().strip()
    elif s.count("<") != 1 or s.count(">") != 1:
        raise ValueError("Invalid email-address-string. (%s)" % s)
    else:
        return s[:s.index("<")].strip(), s[s.index("<")+1:s.index(">")].lower()

def emailadr_extract(s):
    """Extract an email-address from a string and normalize it.

    Supported formats:
        - "someone@example.com"
        - "Some One <SomeOne@example.com>"

    :Returns:
        the lower-case email-address
    :Raises:
        ValueError for invalid formats
    """
    if "<" not in s:
        return s.lower().strip()
    elif s.count("<") != 1 or s.count(">") != 1:
        raise ValueError("Invalid email-address-string. (%s)" % s)
    else:
        return s[s.index("<")+1:s.index(">")].lower()

def file_mod_id(filename):
    """Return an id to check if a file has changed.

    If the returned data differs from previously returned data, the file
    has probably changed.

    :Returns:
        id-tuple or None (if accessing the file failed)
    """
    try:
        s = os.stat(filename)
        return (s.st_dev, s.st_ino, s.st_mtime, s.st_size)
    except IOError:
        return None

def mail_from_file(filename, headersonly=False):
    """Load a mail from a file.

    :Parameters:
        - filename: name of the mail-file
        - headersonly: parse only headers?
    :Returns:
        a EmailMessage-instance
    :Raises:
        IOError/FileNotFoundError if the file does not exist
    """
    with open(filename, 'rb') as f:
        return BytesParser(policy=email.policy.default).parse(f, headersonly)

def mail_add_footer(mail, footer, html=False):
    """Add a footer to a mail.

    - to text/plain: \\n\\n-- \\nfooter\\n
    - to text/html:  <div>footer</div> before </body> or </html>

    :Parameters:
            - mail:   mail as EmailMessage
            - footer: footer-text
            - html:   if True, add the footer also to html-body-part
    """
    body = mail.get_body('plain')
    if body:
        body.set_content(body.get_content() + "\n\n-- \n" + footer)
    if html:
        body = mail.get_body('html')
        if body:
            h = body.get_content()
            hlower = h.lower()
            if "</body>" in hlower:
                i = hlower.index("</body>")
                h = h[:i] + "<div>%s</div>" % htmlescape(footer) + h[i:]
            elif "</html>" in hlower:
                i = hlower.index("</html>")
                h = h[:i] + "<div>%s</div>" % htmlescape(footer) + h[i:]
            else:
                h += "<div>%s</div>" % htmlescape(footer)
            body.set_content(h)

def mail_html2text(mail, minsize=2, striphtml=False):
    """Make sure the mail has a plaintext-part.

    If the mail has no plaintext-body, but only a html-body,
    prepend a html2text-converted plaintext-body.
    """
    # TODO: keep attachments
    body_txt = mail.get_body('plain')
    body_htm = mail.get_body('html')
    if body_txt and len(body_txt.get_content().strip()) < minsize:
        body_txt = None

    if body_htm:
        if not body_txt:
            h = body_htm.get_content()
            t = html2text.html2text(h)
            body_htm.set_content(t, subtype='plain')
            if not striphtml:
                body_htm.add_alternative(h, subtype='html')
        elif striphtml:
            mail.set_content(body_txt.get_content(), subtype='plain')

#=========================================
# mailinglist

class SimpleMailinglist:
    """Simple mailing list.
    """

    def __init__(self, cfgfile, allow_exec=False):
        """Load configuration-file and init the mailinglist.

        :Parameters:
            - cfgfile:    name of the mailinglist-configfile
            - allow_exec: allow to execute the "extend_exec"-command? (True/False)
        :Raises:
            see cfg_load()
        :Logs:
            - DEBUG: "Init: <cfgfile>"
            - see cfg_load()
            - ERROR: "ERROR: <cfgfile>: <ERRORMSG>"
        """
        self.allow_exec = allow_exec
        self.cfgfile = None         # name of the config-file
        self.cfgfile_id = None      # for detecting configfile-changes
        self.cfgf = None            # cfg from cfgfile
        self.cfgx = None            # cfg from extend_exec
        self.cfg = None             # combined cfg
        self.cfg_whitehash = None   # whitelist_hashfile cache
        self.cfg_whitehash_id = None

        # setup initial logging
        self.log = logging.getLogger("simple_mailinglist")
        # - stderr
        self.log.addHandler(logging.StreamHandler())
        # - syslog
        handler = SysLogHandler("/dev/log")
        handler.setFormatter(logging.Formatter("%(name)s: %(levelname)s - %(message)s"))
        self.log.addHandler(handler)

        self.log.debug("Init: %s", cfgfile)

        # load configfile
        try:
            self.cfg_load(cfgfile)
        except Exception as err:
            self.log.error("ERROR: %s: %s", cfgfile, str(err))
            raise

    def log_setup(self):
        """Setup logging from mailinglist-configuration.

        Before, messages are logged to stderr and syslog.
        """
        # clear old logging
        if self.log:
            for h in self.log.handlers:
                self.log.removeHandler(h)
                h.flush()
                h.close()

        # setup new logging
        self.log = logging.getLogger(self.cfg["log_name"])

        if self.cfg["log_syslog"]:
            handler = SysLogHandler("/dev/log")
            handler.setFormatter(logging.Formatter("%(name)s: %(levelname)s - %(message)s"))
            handler.setLevel(self.cfg["log_syslog"])
            if self.log.level == 0  or  self.cfg["log_syslog"] < self.log.level:
                self.log.setLevel(self.cfg["log_syslog"])
            self.log.addHandler(handler)
        if self.cfg["log_file"]:
            if self.cfg["log_file"] == "STDERR":
                self.log.addHandler(logging.StreamHandler())
            else:
                handler = WatchedFileHandler(self.cfg["log_file"], encoding="utf-8")
                handler.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d - %(name)s - %(levelname)-8s - %(message)s", "%Y-%d-%m %H:%M:%S"))
                handler.setLevel(self.cfg["log_file_level"])
                if self.log.level == 0  or  self.cfg["log_file_level"] < self.log.level:
                    self.log.setLevel(self.cfg["log_file_level"])
                self.log.addHandler(handler)
        if not self.log.handlers:
            handler = logging.NullHandler()
            self.log.addHandler(handler)

    #----------------------
    # configuration

    def cfg_load(self, cfgfile):
        """Load/reload mailinglist-configuration.

        Only reloads the configuration, if the configfile was modified.

        :Parameters:
            - cfgfile: name of the mailinglist-configfile
        :Raises:
            IOError if the file (or included files) cannot be read,
            ValueError if a file/string does not contain a valid JSON-object,
            ValueError if the included configfiles are invalid,
            ValueError if allow_exec is False but the config-file contains "extend_exec",
            ValueError for invalid email-adresses
        :Logs:
            - INFO:  "Configuration: load <cfgfile>..."
            - INFO:  "Configuration: reload <cfgfile>..."
            - DEBUG: "Configuration: include <INCLUDEFILE>..."
        """
        fileid = file_mod_id(cfgfile)

        # check if the config-file has changed
        if self.cfg is not None  and  self.cfgfile_id is not None  and  self.cfgfile_id == fileid:
            return

        if self.cfg is None:
            self.log.info("Configuration: load %s...", cfgfile)
        else:
            self.log.info("Configuration: reload %s...", cfgfile)

        # load configfile
        cfg = jsondict_loadf(cfgfile)

        # include
        while "include" in cfg:
            incl = cfg.pop("include")
            if not isinstance(incl, list):
                incl = [incl]
            for inclfile in reversed(incl):
                self.log.debug("Configuration: include %s...", inclfile)
                cfg_include = jsondict_loadf(inclfile)
                for k in cfg_include:
                    if k not in cfg:
                        cfg[k] = cfg_include[k]
                    elif isinstance(cfg[k], list):
                        if not isinstance(cfg_include[k], list):
                            raise ValueError("Incompatible values for '%s' in files '%s' and '%s'." % (k, cfgfile, inclfile))
                        cfg_include[k].extend(cfg[k])
                        cfg[k] = cfg_include[k]

        # check extend_exec / allow_exec
        if "extend_exec" in cfg  and  cfg["extend_exec"]  and  not self.allow_exec:
            raise ValueError("Executing 'extend_exec' is not allowed.")

        # normalize moderators/subscribers/whitelist
        for k in ("moderators", "subscribers", "whitelist"):
            if k in cfg:
                cfg[k] = [emailadr_extract(e) for e in cfg[k]]

        # default values for optional fields
        self.cfgf = CFG_DEFAULT.copy()
        self.cfgf.update(cfg)
        del cfg

        self.cfgfile = cfgfile
        self.cfgfile_id = fileid
        self.cfg = self.cfgf
        self.cfgx = None
        self.log_setup()

    def cfg_extend(self, force=False):
        """Extend configuration via ``extend_exec``-shell-script.

        This is run automatically by cfg_check() or process_mails().

        :Parameters:
            - force: if True, always exec extend_exec; otherwise only exec
                     extend_exec if not yet done.

        :Raises:
            OSError if executing the shell-script fails,
            ValueError if the extend_exec-result does not contain a
                       valid JSON-object or invalid data
        :Logs:
            - INFO: "Configuration: running extend_exec-command..."
        """
        if "extend_exec" not in self.cfg  or  not self.cfg["extend_exec"]:
            return
        if self.cfgx  and  not force:
            return

        self.log.info("Configuration: running extend_exec-command...")
        p = subprocess.Popen(self.cfg["extend_exec"], shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
        out, err = p.communicate()
        ret = p.wait()
        if ret:
            raise OSError("Running 'extend_exec'-command failed. (ret %d, cmd '%s', stderr %s)" % (ret, self.cfg["extend_exec"], repr(err)))

        cfgx = jsondict_loads(out)

        # normalize moderators/subscribers/whitelist
        for k in cfgx.keys():
            if k in ("moderators", "subscribers", "whitelist"):
                cfgx[k] = [emailadr_extract(e) for e in cfgx[k]]

        # extend configuration
        cfg = self.cfgf.copy()
        for k in cfgx.keys():
            if k in cfg  and  isinstance(cfg[k], list):
                if not isinstance(cfgx[k], list):
                    raise ValueError("Incompatible values for '%s' in file '%s' and extend_exec. (%s)" % (k, self.cfgfile, repr(cfgx[k])))
                cfg.extend(cfgx[k])
            else:
                cfg[k] = cfgx[k]
        self.cfgx = cfgx
        self.cfg = cfg
        self.log_setup()

    def cfg_check(self):
        """Check configuration-file syntax and some file/directory permissions.

        Automatically runs cfg_extend().

        :Raises:
            see cfg_extend,
            ValueError("key: ERRORMESSAGE") if the validation fails,
            IOError if files/directories cannot be accessed
        :Logs:
            - ERROR: "ERROR: <cfgfile>: <ERRORMSG>"
        :Uses:
            cfg_extend(), validate_dict()
        """
        try:
            # extend configuration (if necessary)
            self.cfg_extend()

            # check required configuration-fields
            for k in CFG_REQUIRED:
                if k not in self.cfg  or  not self.cfg[k]:
                    raise ValueError("%s: is required." % k)

            # check contents
            validate_dict(self.cfg, CFG_SCHEMA)
        except Exception as err:
            self.log.error("ERROR: %s: %s", self.cfgfile, str(err))
            raise

    #----------------------
    # low-level

    def whitelist_check(self, address):
        """Check if an email-address is in the whitelist.

        :Parameters:
            - address: email address
        :Returns:
            - True:  in whitelist
            - False: not in whitelist
        :Raises:
            IOError if the whitelist-hashfile cannot be accessed.

        :Note:
            If the whitelist includes an "*" entry, all adresses are whitelisted.
            If the whitelist includes an "." entry, all subscribers are whitelisted.
        """
        if "*" in self.cfg["whitelist"]:
            return True
        address = address.lower()
        if address in self.cfg["whitelist"]:
            return True
        if "." in self.cfg["whitelist"]  and  address in self.cfg["subscribers"]:
            return True
        if self.cfg["whitelist_hashfile"]:
            whiteid = file_mod_id(self.cfg["whiteliste_hashfile"])
            if self.cfg_whitehash is None  or  self.cfg_whitehash_id != whiteid:
                f = open(self.cfg["whitelist_hashfile"], 'r')
                self.cfg_whitehash = set(f)
                self.cfg_whitehash_id = whiteid
                f.close()
            if hashlib.sha256(address).hexdigest()+"\n" in self.cfg_whitehash:
                return True
        return False

    def contents_check(self, mail):
        """Check the contents of the mail.

        ...TODO
        :Parameters:
            - mail: ...TODO
        :Returns:
            0: ok
            1: moderate
            2: reject
            3: drop
        """
        # check size
        #TODO

        # check html
        #TODO

        # check DMARC
        #TODO

        # check attachments
        #TODO

    def moderate(self, mailfile, mail):
        """Moderate a mail: Send moderation-mails to the moderators.

        The original mail gets attached to the moderation-mail.

        :Parameters:
            - mailfile: filename of the mail to moderate
            - mail: mail as EmailMessage-instance
        :Returns:
            name of the created outbox-mail
        :Raises:
            IOError if the mailfile or the moderation-template cannot be read,
            see mail_outbox()
        :Uses:
            mail_outbox()
        :Logs:
            - DEBUG: "Moderate: Fill moderation-template '<TEMPLATEFILE>'..."
            - DEBUG: "Moderate: Fill default-moderation-template..."
        """
        # get mail-id
        mail_id = os.path.basename(mailfile).split(":", 1)[0]

        # create moderation-body
        if self.cfg["template_moderate"]:
            template = open(self.cfg["template_moderate"], 'r', encoding="utf-8").read()
        else:
            template = TEMPLATE_MODERATE

        stat = os.stat(mailfile)
        size = stat.st_size
        size_kb = size / 1000
        size_mb = size_kb / 1000

        self.log.info("Moderate: Create moderation-mail for '%s'...", mailfile)

        if self.cfg["template_moderate"]:
            self.log.debug("Moderate: Fill moderation-template '%s'...", self.cfg["template_moderate"])
        else:
            self.log.debug("Moderate: Fill default-moderation-template...")
        text = template.format(mail=mail, size=size, size_kB=size_kb, size_MB=size_mb)

        # create moderation-mail
        if self.cfg["listname"]:
            mod_listname = self.cfg["listname"]
        else:
            mod_listname = self.cfg["address"]

        modmail = EmailMessage()
        modmail.add_header("From", self.cfg["admin_address"])
        modmail.add_header("To",   self.cfg["admin_address"])       #pylint: disable=bad-whitespace
        modmail.add_header("Subject", "MODERATE %s, ID: %s" % (mod_listname, mail_id))
        modmail.add_header("Reply-To", self.cfg["addmin_address"])
        modmail.set_content(text)
        modmail.add_attachment(mail)

        return self.mail_outbox(modmail, self.cfg["moderators"])

    def moderation_get(self):
        """Process moderation-mails.

        Get the mail-IDs from the moderator-accept mails which arrived since
        the last call of this function. The processed moderation-mails are
        then moved to ``admin_dir_done``.

        Note that this moves all files from admin_dir to admin_dir_done.

        :Returns:
            a list of accepted mail-IDs
        :Raises:
            OSError/IOError if moderation-mails cannot not be accessed.
        :Logs:
            - INFO: "Moderation: accept <MAILID>..."
            - WARNING: "Moderation: invalid moderation-mail-subject '<SUBJECT>'."
        """
        moderation_accept = []
        for mailname in os.listdir(self.cfg["admin_dir"]):
            # skip dotfiles
            if mailname[0] == '.':
                continue
            mailfile = os.path.join(self.cfg["admin_dir"], mailname)
            # skip non-files
            if not os.path.isfile(mailfile):
                continue

            # get subject
            mail = mail_from_file(mailfile, headersonly=True)
            subject = mail["Subject"]

            # get ID of moderated mail
            if subject  and  "MODERATE" in subject:
                try:
                    mod_mailid = subject.split(", ID: ", 1)[1].strip()
                    moderation_accept.append(mod_mailid)
                    self.log.info("Moderation: accept %s...", mod_mailid)
                except IndexError:
                    self.log.warning("Moderation: invalid moderation-mail-subject '%s'.", subject)
            else:
                self.log.warning("Moderation: invalid moderation-mail-subject '%s'.", subject)

            # move moderation-mail to "done"
            os.rename(mailfile, os.path.join(self.cfg["admin_dir_done"], mailname))
        return moderation_accept

    def mangle(self, mail):
        """Mangle the mail for the mailinglist.

        - remove headers "Return-Path:", "Sender:", "List-*:", "Envelope-*",
          "Delivered-To:", "X-Original-To:", "Precedence:",
          "DKIM-Signature:", "Domainkey-Signature:", "Received-SPF:"
        - add headers "List-Id:", "List-Post:", and optionally
          List-Help/Subscribe/Unsubscribe/Owner, "Precedence:"
        - add "[list_name]" to the subject if it's not already there
        - convert html
        - add footer
        - modify header according to (braindead) DMARC

        :Parameters:
            - mail: mail as EmailMessage-instance (gets modified)
        :Returns:
            the mangled mail
            :Raises:
                ...
            :Logs:
                - DEBUG: "Mangle mail..."
        """
        self.log.debug("Mangle mail...")

        # remove headers
        del mail["return-path"]
        del mail["sender"]
        del mail["delivered-to"]
        del mail["x-original-to"]
        del mail["precedence"]
        del mail["dkim-signature"]
        del mail["domainkey-signature"]
        del mail["received-spf"]
        for header in mail:
            if header.startswith("list-") or header.startswith("envelope-"):
                del mail[header]

        # add headers
        mail.add_header("List-Id", self.cfg["address"].replace("@", "."))
        mail.add_header("List-Post", "<mailto:%s>\n" % self.cfg["address"])

        #pylint: disable=bad-whitespace,multiple-statements
        if "list-owner"       in self.cfg  and  self.cfg["list-owner"]:        mail.add_header("List-Owner",      "<%s>" % self.cfg["list-owner"])
        if "list-help"        in self.cfg  and  self.cfg["list-help"]:         mail.add_header("List-Help",       "<%s>" % self.cfg["list-help"])
        if "list-subscribe"   in self.cfg  and  self.cfg["list-subscribe"]:    mail.add_header("List-Subscribe",  "<%s>" % self.cfg["list-subscribe"])
        if "list-unsubscribe" in self.cfg  and  self.cfg["list-unsubscribe"]:  mail.add_header("List-Unsubscribe" "<%s>" % self.cfg["list-unsubscribe"])

        # mangle subject
        if "subject" not in mail:
            mail.add_header("Subject", "["+self.cfg["listname"]+"]")
        elif self.cfg["listname"]:
            subj_listname = "[%s]" % self.cfg["listname"]
            if subj_listname not in mail["subject"]:
                mail.replace_header("Subject", "[%s] %s" % (self.cfg["listname"], mail["subject"]))

        # convert html
        #TODO: log?
        if self.cfg["html"] == "convert":
            mail_html2text(mail)
        elif self.cfg["html"] == "convert_strip":
            mail_html2text(mail, striphtml=True)

        # add footer
        #TODO: log?
        if self.cfg["footer"]:
            mail_add_footer(mail, self.cfg["footer"], html=True)

        # DMARC
        #TODO: log?
        if self.cfg["DMARC"] in ("append.INVALID", "reply-to"):
            name, addr = emailadr_parse(mail["from"])
            domain = addr.split("@")[-1]
            dmarc_status = dmarc(domain)
            if dmarc_status in (-1, 2, 3):
                if self.cfg["DMARC"] == "append.INVALID":
                    mail.replace_header("From", "%s <%s.INVALID>" % (name, addr))
                elif self.cfg["DMARC"] == "reply-to":
                    mail.replace_header("From", "%s (%s) via <%s>" % (name, addr, self.cfg["address"]))
                    mail.add_header("Reply-To:", addr)

        return mail

    def mail_outbox(self, mail, recipients):
        """Write a mail + a file containing sender+recipients to the outbox.

        Two files are written:

        - envelope.TIME_SECONDS.SUBSECONDS_PID.HOSTNAME,
          containing the sender and the recipients
          (1 address per line, empty line between sender and recipients)
        - TIME_SECONDS.SUBSECONDS_PID.HOSTNAME, containing the mail

        send_outbox() should then be used to send the outbox-mails.

        :Parameters:
            - mail: mail as EmailMessage-instance or string
            - recipients: list of recipients (usually subscribers or moderators)
        :Returns:
            name of the created outbox-mail
        :Raises:
            TypeError if parameter mail is not a str/EmailMessage-instance,
            ValueError if the mail or recipients is empty,
            IOError if writing the mail fails.
        :Logs:
            - INFO: "Outbox: writing mail '<MAILFILE>'..."
        """
        # serialize mail
        if isinstance(mail, EmailMessage):
            mail = mail.as_string()
        if not isinstance(mail, str):
            raise TypeError("mail_outbox(): parameter 'mail' must be EmailMessage or str.")

        # don't allow empty mail/recipients
        if not mail:
            raise ValueError("Empty 'mail'.")
        if not recipients:
            raise ValueError("Empty 'recipients'.")


        mailname = "%f_%d.%s" % (time.time(), os.getpid(), socket.gethostname())
        self.log.info("Outbox: writing mail '%s'...", mailname)

        # write mail
        f = open(os.path.join(self.cfg["outbox_dir"], mailname), "w", encoding="utf-8")
        f.write(mail.as_string())
        f.close()

        # write envelope-file
        env_filename = os.path.join(self.cfg["outbox_dir"], "envelope."+mailname)
        f = open(env_filename+".part", "w", encoding="utf-8")
        f.write(self.cfg["sender"])
        f.write("\n")
        f.write("\n".join(recipients))
        f.close()
        os.rename(env_filename+".part", env_filename)

        return mailname

    #----------------------
    # high level

    def process_mails(self, reloadcfg=False):
        """Process mailinglist mails.

        Check mails, forward whitelisted/moderator-accepted mail to the
        subscribers and send moderation-requests.

        :Parameters:
            - reloadcfg: if True, re-extend the configuration by extend_exec.
        :Raises:
            see other methods
        :Logs:
            - see other methods
            - DEBUG: "mailing-list '<cfgfile>..."
            - INFO:  "<MAILFILE>..."
            - INFO:  "  -> accepted by moderator"
            - INFO:  "  -> waiting for moderation"
            - INFO:  "  -> whitelist ok ('<EMAIL>')"
            - INFO:  "  -> whitelist failed ('<EMAIL>')"
            - INFO:  "  -> outbox to moderators ('<MAILFILE>')."
            - INFO:  "  -> outbox <MAILFILE>"
            - WARNING: "<MAILFILE>: Invalid mail, no Return-Path or From!"
            - WARNING: "<MAILFILE>: Invalid mail, invald sender-address '<SENDERADR>'."
            - WARNING: "Cannot write moderation-mail to outbox. (<ERRORMSG>, config '<CFGFILE>', mail '<MAILFILE>')"
            - WARNING: "Cannot write mail to outbox. (<ERRORMSG>, config '<CFGFILE>', mail '<MAILFILE>')"
            - ERROR:   "ERROR '<ERRORMSG>', continuing with next mail."
            - ERROR:   "ERROR '<ERRORMSG>', continuing with next mail."
            - ERROR:   "ERROR '<ERRORMSG>', aborting."
        """
        self.log.debug("mailing-list '%s'...", self.cfgfile)

        try:
            # optimization: Only exec extend_exec if there is anything to do.
            # So, check if there are not-yet-moderated mails or moderation-mails:
            for mailname in os.listdir(self.cfg["dir"]) + os.listdir(self.cfg["admin_dir"]):
                # skip dotfiles
                if mailname[0] == '.':
                    continue
                # skip non-files
                elif not os.path.isfile(os.path.join(self.cfg["dir"], mailname)) and \
                     not os.path.isfile(os.path.join(self.cfg["admin_dir"], mailname)):
                    continue
                # skip mails which are waiting for moderation
                elif ":" in mailname  and  "F" in mailname[mailname.index(":"):]:
                    continue
                else:
                    break
            else:
                # no mails -> bye.
                return

            # load/reload/extend configuration
            self.cfg_load(self.cfgfile)
            self.cfg_extend(force=reloadcfg)

            # get moderator-accepted mail IDs
            moderation_accept = self.moderation_get()

            # process mails
            for mailname in os.listdir(self.cfg["dir"]):
                try:
                    # skip dotfiles + non-files
                    if mailname[0] == '.':
                        continue
                    mailfile = os.path.join(self.cfg["dir"], mailname)
                    if not os.path.isfile(mailfile):
                        continue

                    self.log.info("%s...", mailname)
                    accept = False

                    # moderated mail?
                    if ":" in mailname  and  "F" in mailname[mailname.index(":"):]:
                        # mail accepted by moderator? -> accept/forward mail
                        if mailname.split(":", 1)[0] in moderation_accept:
                            self.log.info("  -> accepted by moderator")
                            accept = True
                        else:
                            self.log.info("  -> waiting for moderation")

                    # "normal" mail: check whitelist and accept mail or send moderation mail
                    else:
                        # get mail sender (from Return-Path: or From:)
                        sender = None

                        mail = mail_from_file(mailfile, headersonly=True)
                        if "Return-Path" in mail:
                            sender = mail["Return-Path"]
                        elif "From" in mail:
                            sender = mail["From"]
                        else:
                            self.log.warning("%s: Invalid mail, no Return-Path or From!", mailname)
                            continue
                        if "<" in sender:
                            try:
                                sender = emailadr_extract(sender)
                            except ValueError:
                                self.log.warning("%s: Invalid mail, invald sender-address '%s'.", mailname, sender)
                                continue

                        # check whitelist
                        if self.whitelist_check(sender):
                            # ok -> accept/forward mail
                            self.log.info("  -> whitelist ok ('%s')", sender)
                            accept = True
                        else:
                            # sender not in whitelist -> send mail to moderators and set mail-flag
                            self.log("  -> whitelist failed ('%s')" % sender)
                            try:
                                outbox_mailname = self.moderate(mailfile, mail)
                                self.log.info("  -> outbox to moderators ('%s').", outbox_mailname)
                                os.rename(mailfile, mailfile.rsplit(":", 1)[0]+":2,F")
                            except IOError as err:
                                self.log.warning("Cannot write moderation-mail to outbox. (%s, config '%s', mail '%s')", str(err), self.cfgfile, mailfile)

                        # check contents
                        #TODO

                    # forward mail
                    if accept:
                        # mangle mail
                        mail = mail_from_file(mailfile, headersonly=True)
                        newmail = self.mangle(mail)
                        # send mail
                        try:
                            outbox_mailname = self.mail_outbox(newmail, self.cfg["subscribers"])
                            self.log.info("  -> outbox %s.", outbox_mailname)
                            os.rename(mailfile, os.path.join(self.cfg["dir_done"], mailname))
                        except IOError as err:
                            self.log.warning("Cannot write mail to outbox. (%s, config '%s', mail '%s')", str(err), self.cfgfile, mailfile)
                except Exception as err:                        #pylint: disable=broad-except
                    self.log.error("ERROR '%s', continuing with next mail.", str(err))
                    continue
        except Exception as err:                                #pylint: disable=broad-except
            self.log.error("ERROR '%s', aborting.", str(err))
            raise


    def send_outbox(self):
        """Send all mails in the outbox.

        Simple wrapper around the generic send_outbox-function.

        :Raises:
            see send_outbox()-function
        :Logs:
            - see send_outbox()-function
            - ERROR: "ERROR: <ERRORMSG>" for send_outbox-exceptions
        """
        try:
            send_outbox(self.cfg["sendmail"],
                        self.cfg["outbox_dir"],
                        self.cfg["outbox_done_dir"],
                        self.cfg["sendmail_skip_errors"],
                        self.cfg["sendmail_batch_maxrcpt"],
                        self.cfg["sendmail_batch_wait"],
                        self.log)
        except Exception as err:                                #pylint: disable=broad-except
            self.log.error("ERROR: %s", str(err))
            raise

#-----------------------------------------

def send_outbox(sendmail_cmd, outbox_dir, sent_dir=None, skip_errors=False, batch_maxrcpt=50, batch_wait=1.0, log=None):
    """Send all mails in an outbox.

    Send mails via ``sendmail_cmd -f sender -- recipients``. Each mail is
    sent in batches, which are controlled by batch_maxrcpt and batch_wait.

    In addition to the mailfile itself, the outbox must contain a file
    ``envelope.<mailfilename>`` per mail, which contains the sender
    (in 1st line) and the recipients (1 recipient per line) of the mail.
    If the sendmail-command fails, the remaining recipients are kept
    in the envelope-file for later retries.

    After a mail has been sent, it and its envelope-file are moved to
    sent_dir, or deleted if no sent_dir is given.

    :Parameters:
        - sendmail_cmd: sendmail-compatible command
        - outbox_dir: directory of the outbox-mails
        - sent_dir: directory for sent mails (optional)
        - skip_errors: abort (False) or continue with other mails (True)
          if sendmail fails
        - batch_maxrcpt: max. number of recipients per sendmail-call
        - batch_wait:    number of seconds to wait between sendmail-calls
        - log: logger-instance
    :Raises:
        IOError if the outbox_dir/sent_dir cannot be accessed,
        ValueError if the envelope-file is invalid or the mail is empty,
        OSError if the sendmail-command fails
    :Logs:
        - INFO:  "send_outbox: <MAILFILE>..."
        - INFO:  "send_outbox: <MAILFILE> -> sent (<N> recipients)."
        - DEBUG: "send_outbox: <ENVELOPEFILE> deleted.
        - DEBUG: "send_outbox: <MAILFILE> deleted.
        - DEBUG: "send_outbox: <MAILFILE> moved to <sent_dir>.
        - WARNING: "send_outbox: Sendmail failed, continuing with next mail... (<ERRORMSG>)"
    """
    if not os.path.isdir(outbox_dir)  or  not os.access(outbox_dir, os.R_OK|os.W_OK|os.X_OK):
        raise IOError("Directory '%s' does not exist/cannot be accessed." % outbox_dir)
    if sent_dir:
        if not os.path.isdir(sent_dir)  or  not os.access(sent_dir, os.R_OK|os.W_OK|os.X_OK):
            raise IOError("Directory '%s' does not exist/cannot be accessed." % sent_dir)

    for filename in os.listdir(outbox_dir):
        # skip non-files
        if not os.path.isfile(os.path.join(outbox_dir, filename)):
            continue
        # skip dotfiles
        if filename[0] == '.':
            continue
        # envelope-files
        if filename.startswith("envelope."):
            if log:
                log.info("send_outbox: %s...", filename[9:])
            filename_env  = os.path.join(outbox_dir, filename)          #pylint: disable=bad-whitespace
            filename_mail = os.path.join(outbox_dir, filename[9:])
            with open(filename_env, "r") as f:
                # get sender
                sender = f.readline().strip()
                if not sender:
                    raise ValueError("No sender in file '%s'." % filename_env)
                # get recipients
                recipients = [l.strip() for l in f if l.strip()]
                if not recipients:
                    raise ValueError("No recipients in file '%s'." % filename_env)
            # get mail contents
            f_mail = open(filename_mail, "r")
            mail = f_mail.read()
            f_mail.close()
            if not mail:
                raise ValueError("Mail '%s' is empty." % filename_mail)

            # send mail
            n = 0
            error = None
            try:
                sendmail = [sendmail_cmd, "-f", sender, "--"]
                for n in range(0, len(recipients), batch_maxrcpt):
                    if n != 0:
                        time.sleep(batch_wait)
                    p = subprocess.Popen(sendmail + recipients[n:n+batch_maxrcpt],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
                    (_, stderr) = p.communicate(input=mail)
                    ret = p.wait()
                    if ret:
                        error = "Sendmail failed. (return %d, cmd %s, n %d, stderr %s)" % (ret, repr(sendmail), n, repr(stderr))
                        break
            except OSError as err:
                error = "Sendmail failed. (cmd %s, n %d, err %s)" % (repr(sendmail), n, repr(err))

            # (re)move files or keep remaining recipients
            if error:
                # keep remaining recipients in address-file
                filename_tmp = os.path.join(outbox_dir, ".tmp"+filename)
                f = open(filename_tmp, "w")
                f.write(sender)
                f.write("\n")
                f.write("\n".join(recipients[n:]))
                f.close()
                os.rename(filename_tmp, filename_env)
                if not skip_errors:
                    raise OSError(error)
                else:
                    if log:
                        log.warning("send_outbox: Sendmail failed, continuing with next mail... (%s)", error)
            else:
                if log:
                    log.info("send_outbox: %s -> sent (%d recipients).", filename_mail, len(recipients))
                # move / remove sent mails
                os.unlink(filename_env)
                if log:
                    log.debug("send_outbox: %s deleted.", filename_env)
                if sent_dir:
                    os.rename(filename_mail, os.path.join(sent_dir, filename))
                    if log:
                        log.debug("send_outbox: %s moved to %s.", filename_mail, sent_dir)
                else:
                    os.unlink(filename_mail)
                    if log:
                        log.debug("send_outbox: %s deleted.", filename_mail)

        if error:
            raise OSError(error)


#=========================================

def run(cfgfiles, check=False, process=False, send=False, cleanup=False, daemon=None, allow_exec=False):
    """Run mailinglists.

    :Parameters:
        - cfgfiles: list of mailinglist-config-files
        - check/process/send/cleanup: actions
        - daemon: daemonize? (0: inotify, >0: poll interval)
        - allow_exec: allow executing extend_exec?

    :Returns:
        (EXITCODE, "MESSAGES")
    :Raises:
    """
    if daemon:
        # TODO
        raise NotImplementedError

    # init lists
    lists = []
    for cfgfile in cfgfiles:
        try:
            ml = SimpleMailinglist(cfgfile, allow_exec=allow_exec)
            lists.append(ml)
        except Exception as err:                                #pylint: disable=broad-except
            return (11, "ERROR: configfile '%s': '%s'" % (cfgfile, str(err)))

    # check configfiles
    if check:
        for ml in lists:
            try:
                ml.cfg_check()
            except Exception as err:                            #pylint: disable=broad-except
                return (12, "ERROR: %s: %s" % (ml.cfgfile, str(err)))

    # process/send/cleanup
    for ml in lists:
        if process:
            try:
                ml.process_mails()
            except Exception as err:                            #pylint: disable=broad-except
                return (13, "ERROR: %s: %s" % (ml.cfgfile, str(err)))
        if send:
            try:
                ml.send_outbox()
            except Exception as err:                            #pylint: disable=broad-except
                return (14, "ERROR: %s: %s" % (ml.cfgfile, str(err)))
        if cleanup:
            #TODO
            print("'cleanup' not yet implemented.")

    return (0, "OK")

#=========================================
