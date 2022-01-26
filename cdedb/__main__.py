"""interactive werkzeug debugger for the CdEDB2 application"""

import os
from pathlib import Path

from werkzeug.serving import run_simple

# this must be defined before the first import from the cdedb module
configpath = "/etc/cdedb-application-config.py"
os.environ["CDEDB_CONFIGPATH"] = configpath

from cdedb.frontend.application import (
    Application,  # pylint: disable=import-outside-toplevel
)

static_directory = Path(__file__).resolve().parent.parent / "static"

if __name__ == "__main__":
    os.environ["INTERACTIVE_DEBUGGER"] = "1"
    application = Application()
    run_simple(
        "0.0.0.0",
        5000,
        application,
        use_debugger=True,
        use_evalex=True,
        use_reloader=True,
        static_files={"/static": str(static_directory)}
    )
