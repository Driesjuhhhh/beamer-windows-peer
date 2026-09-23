"""Start at login, owned by the app through SMAppService: macOS keeps the record, so there is no
config field to disagree with it.

ServiceManagement is loaded from the system framework rather than through
pyobjc-framework-ServiceManagement, which would be a new dependency for four calls.
"""

import objc

objc.loadBundle(
    "ServiceManagement", {}, bundle_path="/System/Library/Frameworks/ServiceManagement.framework"
)
for _selector in (b"registerAndReturnError:", b"unregisterAndReturnError:"):
    objc.registerMetaDataForSelector(
        b"SMAppService", _selector, {"arguments": {2: {"type_modifier": objc._C_OUT}}}
    )
SMAppService = objc.lookUpClass("SMAppService")

NOT_REGISTERED, ENABLED, REQUIRES_APPROVAL, NOT_FOUND = 0, 1, 2, 3


def status():
    return SMAppService.mainAppService().status()


def is_enabled():
    """Waiting for approval in Login Items counts as on: the choice was made here."""
    return status() in (ENABLED, REQUIRES_APPROVAL)


def set_enabled(enabled):
    """Raises OSError with macOS's own words when it refuses."""
    service = SMAppService.mainAppService()
    if enabled:
        ok, error = service.registerAndReturnError_(None)
    else:
        if service.status() not in (ENABLED, REQUIRES_APPROVAL):
            return
        ok, error = service.unregisterAndReturnError_(None)
    if not ok:
        raise OSError(error.localizedDescription() if error is not None else "macOS refused")
