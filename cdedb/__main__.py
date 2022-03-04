"""interactive werkzeug debugger for the CdEDB2 application"""

import os
import subprocess
from pathlib import Path

from werkzeug.serving import run_simple

from cdedb.frontend.application import Application

repopath = Path(__file__).resolve().parent.parent
docs_directory = repopath / "doc/build/html"
static_directory = repopath / "static"
configpath = Path("/etc/cdedb-application-config.py")

if __name__ == "__main__":
    subprocess.run(["make", "i18n-compile"], check=True, stdout=subprocess.DEVNULL)
    os.environ["INTERACTIVE_DEBUGGER"] = "1"
    application = Application(configpath if configpath.is_file() else None)
    i18n_files = (repopath / "i18n" / lang / "LC_MESSAGES" / "cdedb.po"
                  for lang in application.conf["I18N_LANGUAGES"])
    run_simple(
        "0.0.0.0",
        5000,
        application,
        use_debugger=True,
        use_evalex=True,
        use_reloader=True,
        extra_files=i18n_files,
        static_files={"/static": str(static_directory), "/doc": str(docs_directory)}
    )
