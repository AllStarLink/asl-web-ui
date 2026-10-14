"""Feature modules.

Each module exposes ``setup(app)``, which registers its API routes (and, in
later milestones, its navigation entries, privileged commands and background
tasks). ``MODULES`` lists them in load order.
"""

from . import core

MODULES = [core]
