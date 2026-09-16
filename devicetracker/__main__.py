"""支持 ``python -m devicetracker``。"""

from .app import main

if __name__ == "__main__":
    raise SystemExit(main())
