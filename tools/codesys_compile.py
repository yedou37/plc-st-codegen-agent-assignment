"""Default CODESYS entry point using the shared reachable-POU compiler."""
from codesys_compile_posthoc import (  # compatibility for existing callers
    DEFAULT_PROFILE, DEVICE_NAME, DEVICE_ID, find_codesys, split_pou,
    type_declarations, script_source, compile_one, main,
)

if __name__ == "__main__":
    raise SystemExit(main())
