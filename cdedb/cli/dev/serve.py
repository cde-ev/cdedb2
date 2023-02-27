"""Interactive werkzeug debugger for the CdEDB2 application."""

import pathlib
import subprocess

from werkzeug.serving import run_simple

from cdedb.config import Config, TestConfig
from cdedb.frontend.application import Application


def serve_debugger(test: bool) -> None:
    """Serve the cdedb using the werkzeug development server"""
    conf = TestConfig() if test else Config()

    repo_path: pathlib.Path = conf["REPOSITORY_PATH"]
    subprocess.run(["make", "i18n-compile"], check=True, stdout=subprocess.DEVNULL,
                   cwd=repo_path)

    application = Application()
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
