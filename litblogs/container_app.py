"""Single-port production entrypoint: ``uvicorn container_app:app --port 5000``.

Development continues to use main:app without mounting a frontend build.
"""

from container_frontend import mount_frontend
from main import app as backend_app

app = mount_frontend(backend_app)
