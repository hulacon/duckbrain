"""duckbrain — General-purpose neuroimaging toolbox for LCNI/Talapas HPC.

Copyright (C) 2026 Ben Hutchinson

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
this program.  If not, see <https://www.gnu.org/licenses/>.

Note: duckbrain *orchestrates* external tools (fMRIPrep, MRIQC, dcm2bids, the
NORDIC MATLAB toolbox) by invoking them at arm's length — it neither links nor
redistributes them, so its licence does not extend to them, nor theirs to it.
Each is obtained and licensed by the user directly; NORDIC in particular is
non-redistributable (see docs/ and TODO.md §5c).

``__version__`` marks the release. It is *not* what provenance records: duckbrain
is distributed by git clone and served from a working copy, so every derivative
is stamped with a ``git describe`` of the actual checkout instead — see
``core.bids_metadata._duckbrain_generated_by``.

This literal is the **single source** of the version: ``pyproject.toml`` declares
``dynamic = ["version"]`` and hatchling reads it from here. Bump it here only —
see ``docs/releasing.md``.
"""

__version__ = "0.2.0"
