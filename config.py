import os
import logging
import secrets
from dotenv import load_dotenv

# --------------------------------------------------
# Load Environment Variables
# --------------------------------------------------
load_dotenv()

# --------------------------------------------------
# Flask Environment & Debug Mode
# --------------------------------------------------
FLASK_ENV = os.getenv('FLASK_ENV', 'production').lower()
DEBUG_MODE = FLASK_ENV == 'development'

# --------------------------------------------------
# Logging Configuration
# --------------------------------------------------
log_level = os.getenv('FLASK_LOG_LEVEL', 'DEBUG' if DEBUG_MODE else 'INFO').upper()
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Enable debug logging for Werkzeug in development mode
if DEBUG_MODE:
    logging.getLogger('werkzeug').setLevel(logging.DEBUG)

# --------------------------------------------------
# Flask Secret Key
# --------------------------------------------------
SECRET_KEY = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))
