"""Feature modules.

Each module exposes ``setup(app)``, which registers its API routes (and, in
later milestones, its navigation entries, privileged commands and background
tasks). ``MODULES`` lists them in load order.
"""

from . import auth, changes, config_files, console, control, core, nodes, status, system

MODULES = [core, auth, system, status, console, changes, config_files, nodes, control]
