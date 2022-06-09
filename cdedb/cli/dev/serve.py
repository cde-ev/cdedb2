"""Interactive werkzeug debugger for the CdEDB2 application."""

import subprocess

from werkzeug.serving import run_simple

from cdedb.config import Config
from cdedb.frontend.application import Application


def serve_debugger() -> None:
    """Serve the cdedb using the werkzeug development server"""

    subprocess.run(["make", "i18n-compile"], check=True, stdout=subprocess.DEVNULL)

    application = Application()
    conf = Config()
    i18n_files = (conf["REPOSITORY_PATH"] / "i18n" / lang / "LC_MESSAGES" / "cdedb.po"
                  for lang in application.conf["I18N_LANGUAGES"])
    run_simple(
        "0.0.0.0",
        5000,
        application,
        use_debugger=True,
        use_evalex=True,
        use_reloader=True,
        extra_files=i18n_files,
        static_files={
            "/static": str(conf["REPOSITORY_PATH"] / "static"),
            "/doc": str(conf["REPOSITORY_PATH"] / "doc/build/html"),
        },
    )
