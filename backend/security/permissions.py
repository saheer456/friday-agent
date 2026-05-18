import logging
from typing import Optional

logger = logging.getLogger("Permissions")


class PermissionManager:
    def __init__(self):
        self._allowlist: set[str] = set()
        self._denylist: set[str] = set()
        self._safe_mode: bool = True
        self._confirmation_required: set[str] = set()

    def configure(self, allowlist: Optional[list[str]] = None, denylist: Optional[list[str]] = None,
                  safe_mode: bool = True, confirmation_required: Optional[list[str]] = None) -> None:
        if allowlist:
            self._allowlist = set(allowlist)
        if denylist:
            self._denylist = set(denylist)
        self._safe_mode = safe_mode
        if confirmation_required:
            self._confirmation_required = set(confirmation_required)

    def validate(self, permissions: list[str], tool_name: str = "") -> bool:
        if self._safe_mode and not permissions:
            logger.warning(f"[Permissions] Tool '{tool_name}' has no declared permissions in safe mode")
            return False

        for perm in permissions:
            if self._denylist and perm in self._denylist:
                logger.warning(f"[Permissions] Denied '{perm}' for tool '{tool_name}'")
                return False
            if self._allowlist and perm not in self._allowlist:
                logger.warning(f"[Permissions] '{perm}' not in allowlist for tool '{tool_name}'")
                return False

        return True

    def requires_confirmation(self, permissions: list[str]) -> bool:
        return any(p in self._confirmation_required for p in permissions)

    def is_safe_mode(self) -> bool:
        return self._safe_mode

    def set_safe_mode(self, enabled: bool) -> None:
        self._safe_mode = enabled


permission_manager = PermissionManager()
