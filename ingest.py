"""Compatibility entry point: builds whichever backend RETRIEVAL_BACKEND selects."""
from config.settings import RETRIEVAL_BACKEND

if __name__ == "__main__":
    if RETRIEVAL_BACKEND == "files":
        from scripts.build_index import main
    else:
        from scripts.build_db import main
    main()
