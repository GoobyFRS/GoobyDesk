#!/usr/bin/env python3
"""Matts Media Request Module to complement my home lab. Not really useful for most folks."""


media_request_module_bp = Blueprint('media_request_module', __name__, url_prefix='/requst-media')

@media_request_module_bp.route("/", methods=["GET", "POST"])
def submit_media_request():
