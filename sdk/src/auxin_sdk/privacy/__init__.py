"""Privacy provider package — M2M payment routing abstraction.

The active provider is selected by AUXIN_PRIVACY env var (default: "direct").
Adding a new privacy rail (Cloak, MagicBlock, Umbra, etc.) requires:
  1. A new module under this package implementing PrivacyProvider.
  2. One entry in the provider_factory() in scripts/run_bridge.py.
  3. Zero changes to Bridge or any other consumer.
"""

from auxin_sdk.privacy.base import PaymentResult, PrivacyProvider

__all__ = ["PaymentResult", "PrivacyProvider"]
