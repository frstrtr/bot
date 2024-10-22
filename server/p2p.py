# p2p.py

"""
This module handles P2P connections and data synchronization.
"""

import json
import logging
from twisted.internet import endpoints, defer, error, protocol, reactor
from database import store_spammer_data, retrieve_spammer_data

LOGGER = logging.getLogger(__name__)


class P2PProtocol(protocol.Protocol):
    """P2P protocol to handle connections and exchange spammer information."""

    def connectionMade(self):
        self.factory.peers.append(self)
        peer = self.transport.getPeer()
        LOGGER.info("P2P connection made with %s:%d", peer.host, peer.port)
        LOGGER.info("P2P connection details: %s", peer)
        self.send_peer_info()

    def dataReceived(self, data):
        message = data.decode("utf-8")
        LOGGER.info("P2P message received: %s", message)
        data = json.loads(message)
        if "user_id" in data:
            user_id = data["user_id"]
            lols_bot_data = data.get("lols_bot_data", "")
            cas_chat_data = data.get("cas_chat_data", "")
            p2p_data = data.get("p2p_data", "")
            store_spammer_data(user_id, lols_bot_data, cas_chat_data, p2p_data)
            self.factory.broadcast_spammer_info(user_id)
        elif "peers" in data:
            self.factory.update_peer_list(data["peers"])

    def connectionLost(self, reason):
        self.factory.peers.remove(self)
        LOGGER.info("P2P connection lost: %s", reason)

    def send_peer_info(self):
        """Send the list of known peers to the connected peer."""
        peer_info = [
            {
                "host": peer.transport.getPeer().host,
                "port": peer.transport.getPeer().port,
                "uuid": self.factory.uuid,
            }
            for peer in self.factory.peers
        ]
        message = json.dumps({"peers": peer_info})
        self.transport.write(message.encode("utf-8"))
        LOGGER.info("Sent peer info: %s", message)


class P2PFactory(protocol.Factory):
    """Factory to manage P2P connections."""

    protocol = P2PProtocol

    def __init__(self, uuid):
        self.peers = []
        self.uuid = uuid
        self.bootstrap_peers = ["172.19.113.234:9002", "172.19.112.1:9001"]

    def broadcast_spammer_info(self, user_id):
        """Broadcast spammer information to all connected peers."""
        spammer_data = retrieve_spammer_data(user_id)
        if spammer_data:
            message = json.dumps(
                {
                    "user_id": user_id,
                    "lols_bot_data": spammer_data["lols_bot_data"],
                    "cas_chat_data": spammer_data["cas_chat_data"],
                    "p2p_data": spammer_data["p2p_data"],
                }
            )
            for peer in self.peers:
                peer.transport.write(message.encode("utf-8"))
            LOGGER.info("Broadcasted spammer info: %s", message)
        else:
            LOGGER.warning("No spammer data found for user_id: %s", user_id)

    def connect_to_bootstrap_peers(self, bootstrap_addresses):
        """Connect to bootstrap peers and gather available peers."""
        deferreds = []
        for address in bootstrap_addresses:
            host, port = address.split(":")
            port = int(port)
            endpoint = endpoints.TCP4ClientEndpoint(reactor, host, port)
            deferred = endpoint.connect(self)
            deferred.addCallback(self.on_bootstrap_peer_connected)
            deferred.addErrback(self.on_bootstrap_peer_failed, address)
            deferreds.append(deferred)
        return defer.gatherResults(deferreds)

    def on_bootstrap_peer_connected(self, protocol):
        """Handle successful connection to a bootstrap peer."""
        peer = protocol.transport.getPeer()
        LOGGER.info("Connected to bootstrap peer %s:%d", peer.host, peer.port)
        self.bootstrap_peers.append(protocol)
        self.synchronize_spammer_data(protocol)

    def on_bootstrap_peer_failed(self, failure, address):
        """Handle failed connection to a bootstrap peer."""
        LOGGER.error("Failed to connect to bootstrap peer %s: %s", address, failure)

    def update_peer_list(self, peers):
        """Update the list of known peers."""
        for peer in peers:
            host = peer["host"]
            port = peer["port"]
            peer_uuid = peer.get("uuid")
            if peer_uuid == self.uuid:
                LOGGER.info(
                    "Skipping self connection to %s:%d (UUID: %s)",
                    host,
                    port,
                    peer_uuid,
                )
                continue
            if not any(
                p.transport.getPeer().host == host
                and p.transport.getPeer().port == port
                for p in self.peers
            ):
                endpoint = endpoints.TCP4ClientEndpoint(reactor, host, port)
                endpoint.connect(self).addCallback(
                    lambda _: LOGGER.info("Connected to new peer %s:%d", host, port)
                ).addErrback(
                    lambda err: LOGGER.error(
                        "Failed to connect to new peer %s:%d: %s", host, port, err
                    )
                )
                LOGGER.info("Connecting to new peer %s:%d", host, port)

    def synchronize_spammer_data(self, protocol):
        """Synchronize spammer data with a newly connected peer."""
        for user_id in self.get_all_spammer_ids():
            spammer_data = retrieve_spammer_data(user_id)
            if spammer_data:
                message = json.dumps(
                    {
                        "user_id": user_id,
                        "lols_bot_data": spammer_data["lols_bot_data"],
                        "cas_chat_data": spammer_data["cas_chat_data"],
                        "p2p_data": spammer_data["p2p_data"],
                    }
                )
                protocol.transport.write(message.encode("utf-8"))
                LOGGER.info("Synchronized spammer data for user_id: %s", user_id)

    def get_all_spammer_ids(self):
        """Retrieve all spammer IDs from the database."""
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM spammers")
        rows = cursor.fetchall()
        conn.close()
        return [row[0] for row in rows]


def find_available_port(start_port):
    """Find an available port starting from the given port."""
    port = start_port
    while True:
        try:
            endpoint = endpoints.TCP4ServerEndpoint(reactor, port)
            endpoint.listen(protocol.Factory())
            return port
        except error.CannotListenError:
            port += 1
