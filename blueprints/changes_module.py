#!/usr/bin/env python3
from flask import Blueprint, render_template, session, Response
import io, csv, logging
from datetime import datetime, timedelta
from local_config_loader import load_core_config

core_yaml_config = load_core_config()
LOG_LEVEL = core_yaml_config["logging"]["level"]
LOG_FILE = core_yaml_config["logging"]["file"]

logging.basicConfig(
    filename=LOG_FILE,
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s"
)
""" Above is the default logging configuration.
Debug - Detailed information
Info - Successes
Warning - Unexpected events
Error - Function failures
Critical - Serious application failures
"""

changes_module_bp = Blueprint('changes', __name__, url_prefix '/changes')

# Importing from APP to avoid circular imports. There might be a better way for this.