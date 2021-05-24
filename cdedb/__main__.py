import os
from pathlib import Path

from cdedb.frontend.application import Application

static_directory = Path(__file__).parent.parent / "static"

if __name__ == "__main__":
    from werkzeug.serving import run_simple
    os.environ["INTERACTIVE_DEBUGGER"] = "1"
    application = Application()
    run_simple(
        "0.0.0.0",
        8000,
        application,
        use_debugger=True,
        use_evalex=True,
        use_reloader=True,
        static_files={"/static": str(static_directory)}
    )
