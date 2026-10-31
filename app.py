import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = BASE_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["DB_PATH"] = os.environ.get("PAPERS_DB", str(BASE_DIR / "data" / "papers.db"))
    app.config["CORPUS_PATH"] = os.environ.get("CORPUS_JSON", str(BASE_DIR / "data" / "corpus.json"))
    app.config["SCREENED_PATH"] = os.environ.get("SCREENED_JSON", str(BASE_DIR / "data" / "screened_corpus.json"))
    app.config["COLLECTIONS_PATH"] = os.environ.get("COLLECTIONS_DB", str(BASE_DIR / "data" / "collections.db"))

    from services.labels import doc_type_label, status_label

    app.jinja_env.filters["doc_type_label"] = doc_type_label
    app.jinja_env.filters["status_label"] = status_label

    from routes.api import api_bp
    from routes.pages import pages_bp

    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
