import os

# Tests mint dev tokens; production has no default secret (see Settings.validate_for_runtime).
os.environ.setdefault("AD_JWT_SECRET", "test-only-secret-0123456789-abcdefghij")
