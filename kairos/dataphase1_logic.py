"""Compatibility imports for the data refresh pipeline."""
from kairos.pipeline.refresh import *  # noqa: F401,F403
from kairos.pipeline.refresh import main

if __name__ == "__main__":
    main()
