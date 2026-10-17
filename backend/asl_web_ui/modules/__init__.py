"""Feature modules.

Each module exposes ``setup(app)``, which registers its API routes (and, in
later milestones, its navigation entries, privileged commands and background
tasks). ``MODULES`` lists them in load order.
"""

from . import (allmon3, auth, backups, changes, config_files, console, control, core, diagnostics, https, jobs, net44,
               network, nodes, sa818, status, system, tuning)

MODULES = [core, auth, system, status, console, jobs, changes, config_files, nodes, control, backups, diagnostics,
           tuning, allmon3, sa818, https, network, net44]
