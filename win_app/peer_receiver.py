"""Windows peer adapter; the shared receiver and its wire protocol stay unchanged.

The legacy focus targets name roles, not operating systems. A Windows sender
always sends focus 'mac' for the far machine and 'windows' for its home machine.
Consequently a Windows receiver accepting that sender must use the Mac role.
Each of the two independent links has its own focus state.
"""

from receiver import ReceiverServer


class PeerReceiver(ReceiverServer):
    def start(self, config):
        windows = getattr(config, "peer_platform", "mac") == "windows"
        self._self_target = "mac" if windows else "windows"
        self._peer_target = "windows" if windows else "mac"
        self._peer_name = "PC" if windows else "Mac"
        return super().start(config)

    def is_receiving_target(self, target):
        return target == self._self_target
