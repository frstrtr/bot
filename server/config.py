# config.py

"""
This module contains configuration settings for the P2P server.
"""

import logging

# Logging configuration
logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)

# Default port for P2P server
DEFAULT_P2P_PORT = 9001

# WebSocket server port
WEBSOCKET_PORT = 9000

# HTTP server port
HTTP_PORT = 8081

# Bootstrap addresses for P2P network
BOOTSTRAP_ADDRESSES = [
    "172.19.113.234:9002",
    "172.19.112.1:9001",
]