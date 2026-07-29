# Changelog

Notable changes to duckbrain. Format follows [Keep a Changelog](https://keepachangelog.com);
versioning follows [Semantic Versioning](https://semver.org).

duckbrain is distributed by `git clone` and served from a working copy, so most
users sit *between* releases. Provenance therefore records a `git describe` of the
actual checkout (e.g. `v0.1.0-3-gabc1234`), not the release number below — see
`core.bids_metadata._duckbrain_generated_by`.

## [Unreleased]

## [0.3.0] — 2026-07-29

### Added

- **The GUI tells you when you are running an old duckbrain.** The bar at the top
  of every page now shows the version you are on — a `git describe` of your
  checkout, which is also what a bug report needs to quote — and links the newer
  release when one exists.

  This closes a real gap rather than adding chrome. duckbrain is distributed by
  `git clone` and the GUI serves whatever is checked out, so a user could sit on
  one commit indefinitely with nothing to say a fix had landed — and the fixes
  that most need to travel are the ones with no symptom. The
  `B0FieldIdentifier`/`B0FieldSource` inversion produced datasets that validate,
  convert cleanly, and are silently uncorrected.

  It compares against **published releases, not `origin/main`**: sitting a few
  commits past a tag is the normal state, so "behind main" would fire for
  everyone, always. When it cannot reach GitHub it says *nothing* — never that you
  are up to date, since it has no way to tell that apart from a failed check. Set
  `DUCKBRAIN_NO_UPDATE_CHECK=1` to switch it off entirely.

  To be told about releases by email: on the repo, **Watch → Custom → Releases**.

- **You can leave a series out of the conversion.** The plan table has a
  `convert` checkbox: untick a row and `becomes` reads *not converted*, no file
  is written for it, and the rest of the session is unaffected. Series duckbrain
  has no way to convert anyway — scouts, physio logs, diffusion — start unticked.

  **Unticking never removes the row**, so nothing you untick by accident
  disappears — the row stays exactly where it was with the box clear, and ticking
  it again puts the file straight back. Nothing is written until you submit.

  Unticking one half of a fieldmap pair removes the **whole pair**, because a
  field is estimated from both halves or not at all; a lone `fmap/` file would be
  something no scan can be corrected from. The runs that were using that pair are
  still converted, just without distortion correction, and you are told which and
  why. Skipping a BOLD without also skipping its SBRef is reported too — an SBRef
  is the reference volume *for* a run, so on its own it references nothing.

  A skip is **per session**. It is recorded in that session's saved
  `dcm2bids_config.json`, which is what the conversion actually runs, so it
  survives leaving the page and coming back. It does not carry to other subjects:
  if the same unwanted series appears in every session, you untick it in each.

- **Each aspect of a run can be signed off on its own.** Every domain page now
  has *Reviewed — no concerns* / *Reviewed — concerns*, with a note, recorded
  against your username and against that aspect only. It is optional and gates
  nothing: a run you can see is wrecked can still be excluded immediately,
  without touring four pages first.

  A domain review is **never** a verdict on the run. The Overview shows how many
  aspects you have reviewed ("3/4 aspects reviewed · no verdict recorded") as a
  prompt, and nothing derives a keep/exclude from it — the four domains do not
  cover every way a run can be unusable (task timing, stimulus delivery, a
  participant asleep with their eyes open), so "reviewed everything" and "this run
  is usable" are different claims and only you can make the second.

- **fMRIPrep's own report is now readable from the QC Dashboard.** A panel at the
  top of the page opens the per-subject report — tissue segmentation, spatial
  normalization, surface reconstruction, susceptibility distortion correction
  before/after, per-run carpet plots and confound correlations. None of these
  were reachable from the GUI before: every QC view is organised around runs, and
  fMRIPrep writes one document per *subject*, so there was nowhere for it to
  hang. The panel sits above the point where the page stops for missing MRIQC
  metrics, so an fMRIPrep derivative is readable whether or not MRIQC has run.

  This includes the **animated** reportlets — the ones that flicker between
  before and after for susceptibility distortion correction and for both
  coregistrations. **Hover the mouse over one to play it**; fMRIPrep leaves the
  animation paused until you do, so a still frame is what it should look like at
  rest.

  The report's size is stated before you open it (~80 MB of figures for a
  13-run subject) and nothing is loaded until you ask for it, because the figures
  are read into the session's memory in order to be served — and the OnDemand
  form defaults to 4 GB.
- **A NORDIC project's QC report now says its IQMs come from raw data.** MRIQC
  always grades the raw acquisition, on purpose — NORDIC removes the thermal
  noise that MRIQC's noise measures are measuring, so denoised IQMs would
  describe the denoiser rather than the scan. That means on a NORDIC project the
  IQM columns and the fMRIPrep motion columns describe different images, and only
  the motion side said so. MRIQC is also, for the same reason, still submittable
  before NORDIC has run, where fMRIPrep is not.
- **The conversion table says whether a Type was read or guessed.** A new
  "Type from" column reads `header` when the DICOM headers state the datatype and
  `name` when it was inferred from the series description — which is the guess,
  and the one worth checking, since a study-specific name like `food` or `Whack`
  says nothing about datatype. duckbrain has recorded this since header
  classification landed; it had just never reached the screen.
- **You can choose which reconstruction converts** where the scanner saved a
  series twice — once distortion-corrected and once with `ND` in the name. Set
  `[conversion] nd_duplicates` to `corrected` (the default, and what duckbrain
  has always done), `uncorrected`, or `both`. The Conversion page offers it as a
  choice on any session that actually holds duplicates, and can save it as the
  project default so bulk convert and the cockpit build the same thing. Under
  `both` the two copies are written as `acq-dis` and `acq-nd`, and a duplicated
  fieldmap becomes two independent fieldmaps, with runs bound to the corrected
  one unless you say otherwise. Whichever you pick, a copy whose folder holds no
  DICOM files is never chosen over one that does.
- **Duplicate copies that are dropped now say so.** They were counted as
  "left unconverted as expected" alongside the scanner localizers, which hid a
  choice being made on your behalf about which image ships.
- **QC decisions now record who made them.** The reviewer is taken from the
  session, so nothing has to be typed and nothing can be left blank. Recording a
  keep/exclude/investigate without an identifiable reviewer is now refused rather
  than saved anonymously.
- **`pending` joins the decision vocabulary**, and automated writers may record
  only that — a machine's suggestion is carried alongside as a recommendation
  where it cannot be mistaken for a judgement.
- **Decision counts separate signed-off from automated and unattributed**, since
  "has a decision" and "was reviewed" are different claims. Decisions written
  before duckbrain captured a reviewer are shown as unattributed and flagged on
  the QC page, so they can be re-recorded rather than silently counted.
- **The QC page now renders a full QC report**, with a run table, IQM
  distributions, outlier detail and the guidance glossary inline — and the same
  report downloads as one self-contained HTML file, or saves into
  `derivatives/duckbrain_qc/` beside the MRIQC and fMRIPrep reports. Links to
  MRIQC reports are relative, so a saved report keeps working when it is moved or
  copied off the cluster.
- **The report states which data the motion numbers came from.** fMRIPrep output
  lives in one directory whether or not `use_nordic` is set, so nothing in the
  path distinguished mean FD computed on NORDIC-denoised data from the same
  number computed on raw data. It is now read from the derivative's own
  provenance and shown.
- **QC measures now come with an explanation and a citation.** A registry of 30
  MRIQC/fMRIPrep measures records, for each one, why it is worth looking at, what
  a human should check by eye, what gets flagged without them, and where the
  guidance comes from — 29 sources, checked against tool source and primary
  literature rather than common practice. Much of what it establishes is that a
  measure has **no** defensible absolute cutoff: tSNR has no published basis for
  "below 20 is poor", and Power's 0.5/0.2 mm figures censor individual frames, so
  applying them to a run's mean is a category error. Nothing is surfaced in the
  GUI yet.
- **`[qc]` config section** (`fd_threshold`, `investigate_threshold`,
  `iqr_multiplier`), so a project can set a QC threshold in its own
  `code/duckbrain.toml` instead of it being a UI slider in one place and a Python
  default in another. A config that cannot be read now warns instead of quietly
  falling back.
- **A run now binds to the fieldmap it was acquired next to**, when a session
  has more than one fieldmap pair. Previously every run bound to whichever pair
  sorted first, so a session that shot one fieldmap, ran some tasks, then shot a
  second fieldmap and ran more, corrected every run with the first pair. An
  explicit `[fmap_mapping]` rule and a matching name still take precedence — this
  only changes the automatic fallback.
- **An empty series directory is now flagged** instead of silently producing no
  file. An empty folder still looks like source data by name, so the conversion
  plan predicted a file that dcm2bids then couldn't create; the plan now checks
  the source and reports it.

- **Conversion now reads the DICOM header, not just the sequence name.** Which
  datatype a series is — anatomical, functional, fieldmap, single-band reference
  — is decided by what the scanner recorded, falling back to the name only when
  the header can't say.

  This matters if your protocol names sequences after the *task* rather than the
  scan type. Series called `food`, `Whack`, `Resting1`, `WMS_R1` or `EPI196` are
  ordinary BOLD runs, and duckbrain previously classified them "unknown" and
  converted nothing — on some sessions producing the anatomical and the
  fieldmaps and none of the functional data. No naming vocabulary can fix that,
  because a site is under no obligation to name a sequence after what it is.

  Checked against 15 studies in the LCNI repository: of the series their curator
  converted, duckbrain now picks the right datatype for **all 359**, and
  reproduces **391 of their 392 BIDS files**. The one miss is a suffix typo in
  the reference dataset.

- **Gradient-echo fieldmaps (magnitude + phase difference) convert.** Previously
  only spin-echo AP/PA pairs did, so a study using the gradient-echo flavour got
  no fieldmap at all and its functional runs were preprocessed without
  distortion correction. duckbrain now produces `magnitude1`, `magnitude2` and
  `phasediff`, and binds the runs they correct.

- **Fieldmap pairs named `distortion_ap`/`distortion_pa`** (and `topup`,
  `pepolar`, `b0map`) are recognised. Previously only `se_epi`-style names were.

- **Diffusion series and gradient-echo fieldmaps duckbrain cannot convert are
  now named as such**, with the consequence spelled out, instead of being
  reported as unrecognised names you might fix on the console.

- **Declared study expectations, and the checks that read them** (`[expected]` in
  a project's `code/duckbrain.toml`). You can now state what a session of your
  study is *supposed* to contain — how many participants, how many T1w scans,
  how many fieldmap pairs, how many runs of each task — and duckbrain flags any
  session that falls short.

  This closes a gap that was invisible by construction. Every other expectation
  in duckbrain is worked out *from* the data it is judging: the subject list from
  what exists on disk, the expected runs from the runs that converted. So a run
  the scanner aborted, or a subject scanned but never ingested, shrinks the
  expectation to match and the status board reads complete. Validated on real
  data: with one task's BOLD removed, the status matrix still reported every
  subject **complete** while the new check caught it.

  Declare it from the Project Status page: pick a session you have reviewed and
  trust, and freeze what it contains as the study's rule. Genuine deviations —
  the subject whose last run was aborted — go under `[expected.exceptions]` with
  a reason, so they stop being reported without being forgotten.

  **Absent means off.** A project that declares nothing gets no expectation
  checks and no new warnings; removing the declaration turns them back off.
  Findings appear in the cockpit's existing warnings panel, which now
  distinguishes errors from warnings and notes. Nothing blocks: a shortfall is
  reported, never a gate on running a stage.
- **A consistency check for fieldmap intent (`fmap-intent`).** The inverted
  `B0FieldIdentifier`/`B0FieldSource` bug fixed on 2026-07-21 was invisible to
  every tool involved — the dataset validated, dcm2bids succeeded, and fMRIPrep
  exited 0 having quietly skipped susceptibility distortion correction. The
  cockpit now flags it directly, on the raw BIDS tree and on the NORDIC
  `bids_input` tree that fMRIPrep actually reads on the NORDIC path.

  It is deliberately wider than the bug it comes from. Inversion is only one way
  to end up with fieldmap metadata nothing can act on, so it also catches a
  `B0FieldSource` that no fieldmap declares as an identifier, a BOLD or SBRef
  with no source at all in a session that *has* fieldmaps, and a fieldmap no
  scan can reference. Each fails identically and silently. It reports and never
  repairs: whether to re-convert or swap the keys depends on what else those
  sidecars have been edited to say.
- **Continuous integration** — `ruff check`, `ruff format --check`, an import
  check and `pytest --cov` now run on every push and pull request, against
  Python 3.10 and 3.12. Nothing about duckbrain's behaviour changes; what changes
  is that a regression can no longer merge on the strength of one machine being
  green. Lint, formatter and coverage settings live in `pyproject.toml`, so a
  local run enforces exactly what CI does — and the formatter is version-bounded
  so that keeps being true. An unpinned gate re-resolves itself on every run and
  can turn a passing commit red with nothing in the repo having changed, which is
  what ruff 0.16 did the day it began formatting Python inside Markdown. The
  coverage floor starts at 60% (measured 61%) and only ever goes up.

  Two bugs fell out of the first lint run: a return annotation in
  `slurm/monitor.py` referenced `Path` with no such import (harmless until
  something introspected it), and `dcm2bids_config._fmap_description` looked up a
  series description it never used. Both fixed.
- **The Conversion page is one table.** DICOM Series, Task/Run Mapping and
  Fieldmap Binding were three surfaces that shared a grain but not a table, so
  reviewing a session meant joining series numbers, task labels and group names by
  eye. They are now a single editor — one row per DICOM series, carrying every
  decision that shapes the output (`task`, `run`, `fieldmap`) next to the output
  itself (`becomes`). Fieldmap rows show the pair they belong to, so the
  run↔pair relation reads off a single row in both directions, and a **Preflight**
  panel sits above it.
- **Fieldmap bindings now attach per run, not per task.** A pair re-shot *within*
  one task — where the runs before and after it want different pairs — could not
  be expressed at all before. `FmapRule` takes an optional `run`, and a run-level
  rule beats a task-wide one. Every existing `[fmap_mapping]` keeps working
  unchanged: a rule with no `run` still means every run of that task. Saved
  project defaults collapse back to task-wide rows wherever all runs agree, so the
  config stays readable.
- **Load a hand-edited config JSON back into the table** — explicit and one-shot,
  and it *reports what it couldn't represent* (criteria beyond `SeriesNumber`,
  arbitrary `sidecar_changes`, custom ids, dcm2bids options) rather than dropping
  them. Continuous two-way sync was considered and rejected for exactly that
  reason; see `docs/conversion-legibility.md`.
- **Conversion Plan — the Conversion page now shows what it will produce.** It
  asked you to approve a transformation while showing only its *inputs*; the
  predicted BIDS filenames existed nowhere except as `custom_entities` fragments
  inside the generated JSON, so reviewing a mapping meant simulating the config
  generator in your head. A new section renders the other half: every series with
  the file it becomes (or an explicit **— not converted**), a **preflight** panel
  above it, and a **which pair corrects which run** view that reads the fieldmap
  relation the direction users actually ask about. The plan is derived from the
  generated config dict — the same one dcm2bids consumes, hand edits included — so
  it cannot drift from what actually runs.
- **Preflight checks before submitting a conversion** (`core.conversion_plan`):
  two series resolving to the same filename (an **error** — dcm2bids writes one
  and loses the other), a fieldmap group holding one phase-encoding direction, a
  series no description claims (an unmatched anat used to vanish silently and
  looked exactly like a dropped scout), and bolds that will be written without
  distortion correction while a usable pair exists. Reports, never repairs.
- **Stable colour tokens per fieldmap pair**, shared across every surface on the
  page, so the series↔pair↔task join is done by eye instead of working memory.
  Colour is always paired with the group's label — never the only channel.

- **BIDS validation now runs automatically after every conversion.** dcm2bids has
  its own `--bids_validate`, and the validator already ships inside the dcm2bids
  container — so this costs nothing and needed no new install. On by default
  (`[conversion] bids_validate = true` to opt out); findings appear in the SLURM
  log the cockpit already shows. Worth knowing what it does *not* do: it checks
  structure and naming, not semantic intent, and would not have caught the
  fieldmap bug below.
- **New consistency check `fmap-pe-direction`** — flags a fieldmap whose `dir-AP`
  / `dir-PA` label disagrees with the `PhaseEncodingDirection` in its header. The
  header is authoritative, so the *label* is the suspect one, and a mismatch
  usually means the console protocol is misnamed — which every downstream
  assumption about that study would inherit.

### Changed

- **Everything duckbrain writes now lives under `derivatives/duckbrain/`.** QC
  decisions go to `derivatives/duckbrain/qc/decisions/` and exported QC reports
  to `derivatives/duckbrain/qc/reports/`, so a project shows at a glance which
  derivatives came from a tool and which from duckbrain. The tool trees —
  `fmriprep/`, `mriqc/`, `nordic/` — are unchanged; those are the tools' own
  output and BIDS expects them where they are.

  **Nothing needs moving, and nothing is moved for you.** Decisions written
  before this — in `derivatives/preprocessing_qc/` — are still read, and so are
  mmmdata's, which still writes there. New decisions go to the new location and
  supersede the old ones for the same run, with both halves of the history
  visible. If you had reviewed runs already, they will look exactly as they did.

- **QC is now five pages grouped by what you are actually asking, instead of one
  long dashboard.** The old page put every measure, every figure and every
  decision in one scroll, with the explanation of what each number meant in a
  glossary far from the number. QC now sits under a single collapsible **QC**
  item in the top bar: an **Overview** with the cohort and the keep/exclude
  verdict, then **Signal & contrast**, **Temporal stability**, **Alignment &
  distortion** and **Artifacts & inhomogeneity** — each reviewing the selected run
  for one question at a time, with each measure's guidance attached to it.

  Each measure is now shown with **where the run sits among the runs around it**,
  not just its value. That is the comparison the guidance has always said to make:
  these numbers carry scanner and protocol batch effects and have almost no
  defensible absolute cutoffs, so "unusual here" is the honest reading and a bare
  value is not.

  Your selection travels in the URL, so a link to one run's alignment review can
  be sent to someone else, and the page it opens is the page you were looking at.

  Faster, too: a domain page loads in about a second on a 65-run project where the
  old page took eighteen, because it renders its own domain rather than a 5 MB
  chart bundle. The standalone HTML report is still exported from the Overview,
  now built only when you ask for it.

- **The QC Dashboard shows fMRIPrep's figures one run at a time, instead of the
  whole 80 MB subject report.** Reviewing distortion correction meant loading
  every figure fMRIPrep wrote for a subject — 83 MB on a real project — to look
  at one 1.1 MB picture. The panel now offers the specific figures the alignment
  review needs (SDC before/after, BOLD-to-T1w and fieldmap coregistration, brain
  mask and CompCor ROIs, segmentation, normalization, surface reconstruction),
  each behind its own toggle with its size named first, scoped to a run you pick.
  The SDC before/after animation still works: the flicker is CSS carried inside
  each SVG, so it does not need the enclosing report. The whole report is still
  one toggle away for anything the curated list does not cover.

  Each figure now also says **what to look for in it**, and — new — what it means
  when it is *missing*. A run with no SDC figure was preprocessed with no
  distortion correction at all, which the old panel had no way to tell you.

- **QC decision files are written in the same schema mmmdata uses**
  (`{"run_key": …, "decisions": [...]}`, append-only). Both the old and new
  shapes are read, and both flat and `sub-XX/` layouts are found, so no existing
  file needs converting — and none is ever rewritten on read.

### Fixed

- **An edit to the conversion table stays edited.** Changing a row's `fieldmap`,
  `task`, `run` or `convert` used to hold for one redraw and then snap back to
  duckbrain's own value — with nothing to explain it, since the revert lands on
  the *next* rerun, not the edit. Anything at all could trigger it: editing a
  second row, clicking a button, or the connection dropping and re-establishing,
  which happens by itself on an idle OnDemand tab. Reported by a beta tester as
  "it soon changes back".

  **The half nobody could see mattered more.** The table would say
  `— not converted` for a series while **Save Config** wrote a config that still
  contained it, and that file — not the table — is what a later bulk convert
  runs. So a review could be made, watched to take effect, and silently not
  reach the conversion. Anyone who edited this table and saved should reopen the
  session, check the rows read as intended, and save again.

  The cause was that `st.data_editor` keys its state on a hash of the table it
  is handed, not on the `key` you give it, so writing an edit back into the
  table discards the edit. duckbrain now keeps its own record of your edits.
  They also **persist** now, so the table carries a note saying how many rows
  are yours, with **↺ Discard my row edits** to put every row back to the
  derived value.
- **A run that loses its fieldmap is now written uncorrected, as the page says
  it is — not corrected by a different pair.** Where a binding could not be
  honoured (you unticked one half of a pair, or pointed a run at a pair holding
  one phase-encoding direction), duckbrain dropped the binding, which handed the
  run back to automatic assignment. In a session with a second complete pair
  that meant the run *was* distortion-corrected, by a pair you had not chosen,
  while the message on screen said it was uncorrected — the one place the
  substitution would have shown said the opposite. The binding is now stated as
  "no distortion correction" rather than removed.

  **Who should look:** anyone who unticked a fieldmap half in a session holding
  more than one pair, and saved. Reopen those sessions and check the fieldmap
  column reads as intended.
- **Binding a run to an incomplete fieldmap pair no longer hides the conversion
  table.** It was reported as an error above the table, which took the table —
  and with it the only cell that could undo the binding — off the screen. It is
  now a warning: the table stays, the row still shows what you picked, and the
  run converts without distortion correction until you change it. (The sibling
  case, unticking one half of a pair, was fixed this way earlier; this was the
  same trap in the same page.)
- **A series dropped on purpose no longer reads as a problem.** Where the
  duplicate-reconstruction choice left a series out, the preflight reported it
  twice — once as a warning saying nothing claimed the series (which means a
  misclassification, a real bug) and once as the note explaining what did. Now
  only the note.

- **Concurrent fMRIPrep jobs no longer destroy each other's FreeSurfer templates.**
  fMRIPrep copies `fsaverage` into a SUBJECTS_DIR shared by every job in the
  project, and a job arriving while another is copying deletes the partial tree
  (it looks like a stale FreeSurfer-6 install). The result is a permanently
  incomplete `fsaverage`, no error anywhere, and `recon-all` failures hours later
  blaming a "stale freesurfer version". duckbrain now installs the templates once
  before submitting anything and verifies them against the container's own file
  list, so every job finds a complete tree and copies nothing. It **refuses to
  submit** if it cannot do this, rather than launching a batch it cannot protect.
  Submitting a whole study is unaffected in speed: the container is inspected once.

  If you have a project that already hit this, the broken tree is self-perpetuating
  — fMRIPrep's own repair check passes on it. Deleting
  `derivatives/fmriprep/sourcedata/freesurfer/fsaverage` once is enough; the next
  submission reinstalls it.
- **The QC run table now says which tool produced each column.** It is a join of
  two derivatives presented as one table, and nothing marked the seam — so MRIQC's
  `fd_mean` and fMRIPrep's `mean_fd` sat side by side, near-anagrams of each
  other, both mean framewise displacement, computed by different tools on
  different images whenever NORDIC is in play. A spanning header row now attributes
  each block to **MRIQC** or **fMRIPrep**, and the blocks are shaded to match.
- **Missing fMRIPrep motion no longer looks like good motion.** The motion columns
  were dropped whenever no run carried them, so a table that was entirely MRIQC
  looked exactly like one where both tools agreed. The report now states which of
  the reasons applies — fMRIPrep has not run, it ran but wrote no confounds files,
  its confounds matched none of these runs, or it covered only some of them — and
  an individual empty motion cell renders as `—` rather than blank. Found on a
  real project where 65 MRIQC runs loaded against zero confounds files.
- **MRIQC reports are now reachable from the QC Dashboard.** Every per-run
  "View report" link in the embedded report did nothing when clicked — not an
  error, nothing at all — because the link was relative to the *exported* copy's
  location, and the embedded copy lives in a sandboxed iframe with no location of
  its own. Under OnDemand it resolved to a path the proxy does not serve. Each
  run's expander in the QC Decisions panel now has a **Show MRIQC report** toggle
  that renders the real report, figures included, inside the app; the run table's
  Report column names the report rather than offering a link that cannot work.
  Reports open one at a time on purpose: their figures are 4–15 MB per run.
- **The fieldmap-intent check never ran on NORDIC projects.** It looked for
  fMRIPrep's assembled input tree under `derivatives/nordic/bids_input`, which
  duckbrain has never written — the tree is `bids_format`. Because a missing
  directory is skipped rather than reported, the one check that catches fMRIPrep
  silently declining distortion correction was inert on exactly the projects
  where the input tree is assembled by hand and can go stale on its own. The path
  now comes from one function both ends share.

- **A duplicated gradient-echo fieldmap no longer loses a usable pair.** Where a
  session held both reconstructions of a fieldmap — four series, two names — the
  uncorrected magnitude was matched against the corrected *phase* and dropped on
  the strength of it. If the corrected magnitude's folder was then empty, both
  uncorrected series went too and the session was left with no usable fieldmap
  even though a complete one was sitting there. The choice is now made once per
  pair, so a fieldmap's magnitude and phase always come from the same
  reconstruction.
- **A session that shot the same anatomical twice and saved both reconstructions
  gained a spurious third anatomical.** One of the four series went unclaimed and
  converted alongside the two the setting had chosen.
- **A turbo spin echo is now recognised as one from the scanner header.** T2w
  anatomicals classified only because their *name* happened to contain `t2`, so a
  site naming them anything else lost them; a dual-echo (PD+T2) turbo spin echo
  was also on course to convert as half a fieldmap.
- **A scanner localizer is now recognised from the sequence it ran**, not only
  from its name — so a site whose console calls it something other than
  `scout`/`localizer` no longer gets a warning about a series duckbrain should
  have known to skip. A 3D SPACE anatomical named after its pulse sequence is
  likewise no longer dropped.
- **An unpaired gradient-echo fieldmap half no longer claims the flavour is
  unsupported.** It has been supported since the previous release's fix; the
  message now names what is actually missing.
- **The QC page now finds MRIQC output on a study without sessions.** It looked
  only for `sub-XX/ses-YY/<datatype>/`, so a single-session study matched nothing
  and the page reported no metrics and suggested running MRIQC — which had
  already run, successfully. Sessioned and flat layouts are unaffected.
- **A session with two gradient-echo fieldmap pairs now converts.** Both pairs
  were written to the same filenames, which the collision check caught as an
  error — so nothing was ever silently overwritten, but the session could not be
  converted at all, and the message suggested setting task or run values that a
  fieldmap does not have. Each pair now gets its own `acq-` or `run-` entity,
  exactly as spin-echo pairs already did. Which run each pair corrects is
  unchanged.
- **A complete gradient-echo fieldmap is no longer reported as unusable.** Every
  session with one was told the fieldmap "can't correct anything and isn't
  offered for binding". Both halves of that were false — the group was complete,
  and the runs were bound to it — so the warning was pure noise on a correct
  conversion.
- **A single-volume reference is no longer mistaken for a functional run on
  non-mosaic data.** Telling a single-band reference from its BOLD relied on the
  file count, which equals the volume count only for Siemens mosaic exports. With
  mosaic disabled, or on GE/Philips, a one-volume reference is one file per slice
  and read as a multi-volume run; it is now settled by the slice geometry.
- **A distortion-uncorrected `_ND` copy is no longer dropped when its corrected
  twin is present but empty.** One real session had the corrected anatomical
  folder present yet empty beside a populated `_ND` copy, and dropping the copy
  left it with no anatomical at all.

- **A task whose name contains `t1_` or `t2_` is no longer converted as an
  anatomical.** The anat vocabulary matched anywhere in the name, so real
  functional runs called `BART1_…`, `SST2_…` and `React2_…` were written as T1w
  and T2w images — and because anatomicals carried no run entity, they landed on
  the *same filename* as the real MPRAGE and silently replaced it.

- **Repeated anatomicals get `run-` entities instead of overwriting each
  other.** Two T1w scans in one session previously resolved to one filename.

- **Siemens localizers named `AAHScout` or `aa_scout` are recognised as
  localizers.** They previously fell through as unrecognised, one spurious
  warning each — hundreds per project.

- **The vNav navigator setter and Siemens' distortion-uncorrected `_ND` copy no
  longer convert as extra anatomicals.** Both collided with the real MPRAGE. An
  `_ND` series is only dropped when its corrected twin is present, so a site
  that acquires `_ND` alone still gets its anatomical.

- **Bulk convert, the cockpit and SLURM submissions now refuse a session whose
  series would overwrite each other's output.** The Conversion page has always
  reported these; the non-interactive path submitted anyway, and dcm2bids kept
  whichever series it wrote last and exited successfully.

- **A repeated task named by suffix — `MAB1`, `MAB2`, `MAB3` — is one task with
  three runs**, not three tasks. Acquisition parameters in the name
  (`GNG1_mb3_g2_2mm_te27`) are no longer part of the task label.

- **Fieldmap pairs whose name contains the letters `ap` or `pa` outside the
  direction token** are grouped correctly. `AP_fieldmap_se_epi_2mm_ap` was split
  into two groups and never paired, and `se_epi_pa_apex` was read as AP.


- **"Force overwrite existing BIDS output" overwrote nothing.** duckbrain passed
  dcm2bids `--force_dcm2bids`, which only overwrites the *temporary* dcm2niix
  output under `tmp_dcm2bids/`. The flag that overwrites the BIDS output is
  `--clobber`, and it was never passed — so dcm2bids skipped every destination
  file that already existed and exited 0. Reconverting an already-converted
  session re-ran dcm2niix, wrote nothing, and reported success. Both flags are
  now sent, in the sbatch template and the subprocess path alike.

  The practical consequence: no fix to the generated config could reach a
  subject that had been converted once. That is how the B0 identifier fix above
  failed to take.
- **A stale saved conversion config is now reported instead of silently
  winning.** `<sourcedata>/sub-XX/[ses-YY]/dcm2bids_config.json` is reused by
  bulk convert and the cockpit, and only regenerated when absent — right when
  the file records a review you made, wrong when duckbrain's generator has
  changed since. The Conversion page now compares the saved file against what
  would be generated for that session today and names the descriptions and
  fields that differ.

  Reported, not resolved. A difference can equally mean "I edited this
  deliberately" or "duckbrain changed underneath me", and the file records no
  provenance to tell them apart — regenerating would discard a real review,
  ignoring it discards a real fix. A config that still matches says nothing, so
  a reviewed session stays quiet.
- **NORDIC could disappear from the Project Status board with no way to bring it
  back.** The cockpit marks the NORDIC stage **n/a** — and offers no run control
  — for any project that hasn't set `use_nordic`, which is right: NORDIC is
  opt-in, and grading it missing made every non-NORDIC project show unfinished
  work forever. But `use_nordic` had no control anywhere in the GUI. It existed
  only as a default in `config/base.toml`, so a project could not state that it
  *did* use NORDIC, and the stage simply vanished from the board unless you
  hand-edited the project's `code/duckbrain.toml`.

  Project Setup now carries the toggle. Off, fMRIPrep reads the raw BIDS tree and
  the board shows NORDIC as n/a; on, fMRIPrep reads
  `derivatives/nordic/bids_format` and waits for the NORDIC stage. NORDIC runs as
  a producer either way — the setting only decides whether anything consumes what
  it produces — and launching it deliberately from Preprocessing → NORDIC works
  regardless, as it did throughout.
- **A voxel size in a fieldmap's series name aborted every fMRIPrep run.** The
  B0 identifier is composed from the fieldmap group name, which comes straight
  off the scanner's SeriesDescription — `se_epi_2.5mm_ap` yields the group
  `2.5mm` and the identifier `B0map_2.5mm`. sdcflows names a nipype node after
  whatever it reads from `B0FieldIdentifier`, and nipype accepts only `[\w-]`,
  so the period killed the run at workflow-build time (`Node name
  "out_B0map_2.5mm" is not valid`) before a single volume was processed.
  Characters illegal in a node name are now stripped, giving `B0map_25mm`;
  hyphens and underscores are kept, because the repeat-pair suffix
  (`encoding-2`) and the subject/session suffix need them to stay distinct.

  This is the fieldmap-intent fix surfacing a second bug underneath it. While
  `B0FieldIdentifier` and `B0FieldSource` were inverted, sdcflows found no
  estimator, never built a node named after the identifier, and fMRIPrep ran
  happily without distortion correction. Correcting the intent made PEPOLAR
  estimation genuinely fire, and the malformed identifier was read for the first
  time. Every test fixture had used group names that were already alphanumeric,
  which is why nothing caught it. Datasets converted before this fix keep the
  old identifier and need their `B0Field*` sidecar values rewritten (or the
  subject reconverted) before fMRIPrep will run.

  Two group names that differ only in punctuation (`2.5mm` and `25mm`) would
  reduce to one identifier and hand fMRIPrep both pairs as a single estimator —
  distortion correction built from the wrong images, which looks processed. That
  now raises at config-generation time instead.

*The block below answers an external code review of 2026-07-22
(`docs/code-review-260722.md`); see TODO `#18`.*

- **A stage is complete when every run is, not when one output matched a glob.**
  Conversion, NORDIC, fMRIPrep and MRIQC each graded complete off a single
  wildcard, so a unit with four BOLD runs where one succeeded read green at every
  stage. Not merely cosmetic: green unlocks the next stage and suppresses a real
  sacct failure, so one surviving run both hid three failures and let fMRIPrep
  start on a half-converted unit. Completion now compares the runs a unit has
  against the outputs they produced. **Expect cells that read green yesterday to
  turn yellow** — the run popover says "2 of 4 runs present" so a partial cell
  explains itself.
- **NORDIC's assembled input tree takes anatomy from every session of a subject.**
  It took anat only from the current session, contradicting fMRIPrep's own
  deliberately-unfiltered anat policy — so with `use_nordic`, a subject whose T1w
  was acquired once in `ses-01` gave fMRIPrep a `ses-02` tree containing no
  anatomical at all. ⚠️ **This can change anat handling for a NORDIC project
  already mid-study**, since fMRIPrep now sees every session's anat and makes its
  own selection, exactly as a non-NORDIC run always has.
- **That tree also converges now instead of only growing.** Every copy was
  skip-if-exists and nothing was ever removed, so an edited sidecar (fieldmap
  intent, task labels) or a deleted run stayed in the tree fMRIPrep reads
  indefinitely. Staged files are refreshed when their source changes and pruned
  when it is gone — scoped so concurrent per-unit jobs cannot delete each other's
  files. Concurrent builds no longer crash on a hardlink collision, and fall back
  to copying where hardlinks are unavailable (a different filesystem, some NFS).
- **The Setup page's save no longer deletes hand-written SLURM settings.**
  Saving replaced the whole `[slurm]` section while writing only four of its keys,
  so a hand-tuned `[slurm.overrides.fmriprep]` — live config — was deleted by a
  project rename, and later submissions silently used different resources. Each
  form now owns named fields; everything else in the section survives.
- **A failure that follows a success is visible again.** Seven days of job history
  reduced to "names that failed" and "names that completed", so once a job name
  had ever completed, no later failure could ever surface. The latest attempt
  decides.
- **A failed cell shows stderr.** It displayed stdout and fell back to stderr only
  when stdout was empty — and fMRIPrep always writes a stdout banner, so the
  traceback was unreachable from the cell reporting the failure. Log reads are
  also bounded now; the cockpit re-read complete multi-megabyte logs on every
  30-second refresh to show their last 4000 characters.
- **Per-session conversion records what it launched.** The Conversion page
  submitted its own job instead of going through the pipeline controller, so the
  most-used conversion path wrote no provenance row and left the cockpit with no
  job id — its cells read "No job id recorded" for every conversion started there.
- **Each submitted script is kept.** Retrying a stage overwrote the previous
  attempt's script, and the submission record held no parameters, so a failed
  attempt's exact command line was unrecoverable even with its log and its record
  still on disk. Scripts are archived per job id and referenced from the record.
- **Paths with spaces or shell metacharacters no longer break the sbatch
  scripts** — `/projects/lcni/dcm/hulacon/Hutchinson/New Program` is a real
  export. Paths are quoted as single shell arguments, and the NORDIC templates no
  longer interpolate them into Python and MATLAB string literals nested inside
  bash strings, where an apostrophe escaped the literal and a `$` was expanded
  before Python or MATLAB saw it.
- **The DICOM sorter no longer builds paths from unchecked scanner metadata.**
  `PatientName` / `StudyDescription` / `SeriesDescription` went into the
  destination unmodified: a name of `../../escape` wrote outside the project
  directory, and an absolute-looking `StudyDescription` part discarded the output
  root entirely. Components are sanitized and containment is enforced;
  overlapping input/output roots are refused, since with the default *move* the
  tool would rearrange the source tree into itself.
- **Re-ingesting a copied session is a no-op again**, not a collision with its own
  output — a regression in the previous commit's collision check, which compared
  resolved paths (right for a symlink, meaningless for a directory). Subject and
  session labels typed into the mapping table are validated before they become
  paths, and the whole selection is checked for duplicate destinations before
  anything is written.
- **The hand-edited config JSON now drives the whole Conversion page.** With the
  override on, the `task` / `run` / `fieldmap` columns kept showing table state
  and kept accepting edits, while a different config was submitted — three
  controls that silently did nothing, with the only notice inside a collapsed
  expander at the bottom of the page. Those columns are now read from the JSON and
  read-only while it drives, the state is announced above the table, and because
  everything downstream derives from the same frame, "Save as project default" now
  persists the bindings you reviewed rather than the table's.
- **A previously reviewed `dcm2bids_config.json` is surfaced.** That file — not
  the table — is what a bulk or cockpit convert consumes, but the page only ever
  wrote it, so a reviewed session reopened showing heuristic values and submitting
  overwrote the review without a word. It now reports the saved file, when it was
  saved, that submitting replaces it, and offers to load it into the table.
- **Pickers follow a project switch.** The directory picker committed its
  selection once per session, so after switching projects the DICOM-source and
  project-directory fields still showed the *previous* project's paths — under a
  green "✓ Selected:" — and saving wrote them into the new project.
- **"Shared resources" shows the shared value.** The section saves to the user
  config but was seeded from the fully merged config, so it displayed a project's
  own override under a heading that says "all your projects", and saving pushed
  that project's container versions onto every other project. A project that pins
  something different is now called out explicitly.
- **Ingestion no longer reports success for a session it didn't write.** Ingest is
  idempotent, and the page couldn't tell a real link from a no-op — so two scanner
  folders mapped to one subject/session both showed green while only the first was
  on disk. Re-ingesting the same folder is still a quiet no-op; a *different*
  folder colliding on an ingested subject/session is now refused and named.
- **The QC "Reason" field no longer records a verdict.** Typing a note on an
  undecided run saved `decision="investigate"` while the heading still read "no
  decision". The reason is carried into whichever verdict you click.
- **Saving on the Project Setup page no longer deletes the rest of the project
  config.** It wrote the file whole, so saving a SLURM account silently discarded
  the study's `[task_mapping]` and `[fmap_mapping]` — the task labels and fieldmap
  bindings defined on the Conversion page — along with `[fmriprep]`, `[nordic]`,
  `[conversion]` and any hand-written key, and reported success. Both project and
  user saves are now section-scoped read-modify-write, the contract
  `save_project_task_map` already had. The user config likewise keeps its
  `[recent]` projects.
- **The SLURM partition set on the Setup page now reaches jobs.** Every stage
  carried a shipped per-stage partition that outranked it, so the field was inert
  while looking functional (`account` and `email` did work). Stages now declare
  *which of two roles* they need — fMRIPrep is the long one — and both role names
  resolve from `[slurm] partition` / `partition_long`, which is also the first
  thing that has ever read `partition_long`. Per-stage `time`/`memory`/`cpus` are
  deliberately unchanged: those are tuned per stage and a project-wide default
  should not retune them.
  - ⚠️ **Check your project's partition.** duckbrain's default was `medium`, which
    is not a Talapas partition; projects created before this carry it, and it was
    harmless only while the field was inert. The Setup page now validates both
    partitions against `sinfo` and refuses to let a bad one pass unnoticed.
- **A BOLD is no longer bound to an incomplete fieldmap pair.** When a session had
  no complete pair, every incomplete one became a candidate, so an aborted lone AP
  got bound — contradicting the Fieldmap Detection panel, which says an incomplete
  pair isn't offered. The per-session page then hard-errored on a binding it had
  made itself, and the bulk path submitted it. No complete pair now means no
  binding, which is an honest "no distortion correction".
- **NORDIC no longer shows as unfinished work in projects that don't use it.**
  Without `use_nordic` nothing reads NORDIC output, but the stage graded *missing*
  for every unit: the rollup read `0/N`, the board offered a one-click "run all",
  and "every stage complete" could never be reached. It reads `—` / `n/a` now and
  is not launchable from the board. The Preprocessing page's NORDIC tab still runs
  it deliberately.
- **duckbrain no longer overwrites `PhaseEncodingDirection`.** It was forced to
  `j-`/`j` from the `_ap`/`_pa` token in the series name, clobbering the value
  dcm2niix derives from the DICOM header. That could only lose information — a
  no-op when they agree, and wrong when they don't — and a mis-signed phase
  encoding direction doesn't skip distortion correction, it applies it backwards,
  deforming the data while looking processed. The header is now left alone and
  disagreements are reported (see `fmap-pe-direction` above).
- **`.bidsignore` now covers `tmp_dcm2bids/`.** dcm2bids' working directory holds
  a log named `sub-XXX_ses-YY_*.log`, so the BIDS validator inferred a phantom
  subject with no valid data — three of the four errors on a real dataset. Only
  `work/`, which dcm2bids never writes to, was listed.
- 🔴 **Fieldmap intent was inverted, so susceptibility distortion correction never
  ran.** BIDS estimates the field from scans sharing a `B0FieldIdentifier` and
  applies it to scans sharing a `B0FieldSource`; duckbrain wrote the identifier on
  the **bold** and the source on the **fieldmap** — exactly backwards. Nothing
  errored: the dataset validates, dcm2bids is happy, and fMRIPrep simply reports
  *"Susceptibility distortion correction: None"* and preprocesses uncorrected.
  Confirmed on the real `divatten_gui_beta` runs, which have complete AP/PA pairs
  and no `--ignore` flags. **Datasets converted before this fix have unusable
  fieldmap metadata and their fMRIPrep derivatives ran without SDC** — re-convert
  (or patch the sidecars) and re-run fMRIPrep.
- **SBRefs are now bound to the same fieldmap pair as their BOLD.** They were
  written with no fieldmap association at all. This matters more than it looks:
  fMRIPrep uses an SBRef, when present, to build the BOLD reference that
  coregistration and SDC operate on, so an unassociated SBRef made that reference
  the one image in the chain nothing corrected.
- **`use_sessions` accepts both a TOML boolean and the GUI's string form.** A
  project config carrying `use_sessions = true` (which is what a hand-written one
  naturally has) crashed the whole Project Setup page with
  `ValueError: 'True' is not in list`. Worse and quieter: `bool("false")` is
  `True` in Python, so a project that turned the `ses-` entity **off** through the
  Setup page got session entities anyway — the option did the opposite of what it
  said. Both forms now normalize in one place in core
  (`ingestion.normalize_use_sessions`), and a value duckbrain doesn't recognize
  falls back to `auto` *and says so* on the Setup page instead of being swallowed.
- **The dcm2bids JSON editor no longer silently overrides the tables.** The text
  area held its own widget state, so once you typed in it the Task/Run Mapping and
  Fieldmap Binding tables stopped reconciling and nothing said which of the two
  would be submitted — despite the page declaring the tables the source of truth.
  Hand-editing is now an explicit, labelled opt-in with a revert.

## [0.2.0] — 2026-07-21

### Added
- **Project-wide fieldmap binding** — when a session holds more than one usable
  fieldmap pair, a study can now declare which pair corrects which task instead of
  accepting the automatic choice (name match, else the first pair — there is no
  temporal-proximity logic). Set it on the Conversion page's new **Fieldmap
  Binding** table, which also *shows* the binding for the first time: previously
  the func↔fmap link was only visible as `B0FieldIdentifier` strings inside the
  generated JSON. Persisted to the project config's `[fmap_mapping]` and threaded
  through bulk/cockpit conversion, so both paths agree. A binding naming a group a
  session doesn't have — or one holding a single phase-encoding direction, or any
  group at all in a session that collected no fieldmaps — **fails loudly**:
  quietly using a different pair, or none, is precisely what an explicit binding
  exists to prevent. The reserved group `none` binds a task to no fieldmap, for a
  run that shouldn't be distortion-corrected. A session with no fieldmaps and no
  binding is unchanged: no `B0FieldIdentifier`, no `fmap/`, fMRIPrep runs without
  susceptibility distortion correction.
- **Project-wide task mapping** — define a study's `SeriesDescription → task`
  mapping once and inherit it across every subject (per-session edits still
  override). Persisted to the project config's `[task_mapping]`; threaded through
  bulk/cockpit conversion. Live-validated through the Conversion page.
- **Actionable cockpit board** — the Project Status matrix cells are now the launch
  controls. A cell opens a popover: **▶** to launch the next step (params inline),
  or, when a job exists, a reference to the **exact SLURM job** (id + live
  squeue/sacct detail + log tail) with **cancel** for in-flight jobs and **re-run**
  for failed ones. Column headers run a whole stage (guarded). Replaces the former
  separate launch selectbox + bulk expander + read-only table.
- **Job tracking folded into Project Status** — the standalone Job Monitor page is
  retired; its squeue/sacct tables and log viewer live on as the cockpit's "All
  SLURM jobs" panel (the catch-all for jobs not tied to a board cell), fed from the
  same single SLURM pull. `survey_live(config, with_jobs=True)` exposes the job
  index; `cancel_job()` wraps `scancel`; `find_job_logs()` resolves array-job logs.
- **ReproIn console naming is understood** —
  [ReproIn](https://github.com/ReproNim/reproin) sequence names
  (`func-bold_ses-pre_task-faces_acq-1mm_run-01_dir-AP`) are parsed for their BIDS
  entities, and those are trusted ahead of the inferring heuristics: the seqtype
  sets the datatype, `acq-` names the fieldmap group, `run-` pairs the fieldmaps,
  and `task-`/`run-` set the func entities. duckbrain still converts with
  dcm2bids — only the convention is adopted, not heudiconv or the ReproIn
  heuristic. Without this, a ReproIn-named study converted with **no fieldmaps at
  all and no warning**. The Conversion page says when it detects the convention.
- **Sources that group sessions by protocol** — a DICOM source whose session
  folders sit one level down (mmmdata's `anat_session/`, `func_session_*/`) is now
  discovered; previously it produced an empty list. Descent only happens when the
  top level yields nothing parseable, so the flat LCNI layout is untouched, and the
  grouping folder is recorded as a protocol label, not part of the subject/session
  identity.
- **A Notes column on the ingestion table** — flags rows needing attention rather
  than accepting a guess silently: an unreadable folder, a subject that still reads
  as a session label or a date, and two folders claiming the same `sub-XX/ses-YY`
  (real in mmmdata, and ingestion is idempotent, so the second would have quietly
  resolved to the first).

### Changed
- **MRIQC default pinned to `24.0.2`** (was `24.1.0`) — `24.0.2` is both the
  validated version and MRIQC's latest stable release; there is no `24.1.0` Docker
  tag (that string is only the `24.0.2` container's internal self-report). The old
  default pointed the build command at a nonexistent tag.

### Fixed
- **Reacquired *named* fieldmap pairs were silently discarded.** A session that
  reshoots `se_epi_ap_encoding` between task blocks kept only the last pair — one
  real session shoots three and converted one. Named groups now pair by
  acquisition order exactly as unnamed pairs already did, emitting
  `acq-encoding_run-1` / `_run-2` / … instead of one overwritten `dir-AP`.
- **A bold could be linked to a fieldmap group with only one direction.** An
  aborted opening AP sorts first, and the first group won by default — giving
  fMRIPrep a distortion correction it cannot run. Only groups holding both AP and
  PA are candidates now.
- **A session label with a qualifier was adopted as the subject.** `sess04CR` (a
  condition tag) and `sess3.2` (a rescan) did not match the session pattern, so
  `MMM03_sess04CR` parsed as subject `sess04CR`: the real subject disappeared and
  its sessions became phantom subjects.
- **Discovery crashed on a session folder the user cannot read.** Shared LCNI
  exports hold other people's sessions with no group read bit, and one
  `PermissionError` took down the whole ingestion page. Such folders are now kept
  and annotated — dropping them would hide a real subject.
- **"Reuse anat derivatives" silently did nothing** when there were no anat
  derivatives to reuse. fMRIPrep accepts `--derivatives` pointing at a tree with no
  anat for the subject, rebuilds the whole anat workflow, and logs nothing about
  the reuse it could not do — so the option looked honoured while costing the hours
  it claimed to save. Requesting reuse without a prior anat-only run now fails at
  submit time; the cockpit disables the option per unit and says why.
- **fMRIPrep bind-mounted its output directory twice** (read-write, then read-only
  for `--derivatives`) whenever anat reuse was on. Singularity resolved the overlap
  by dropping one of the two; had it dropped the read-write bind, fMRIPrep could
  not have written its outputs.
- **Invalid BIDS task labels** — a user-entered task label (mapping-table edit or
  hand-written rule) was emitted verbatim, so `resting_test` produced the invalid
  `task-resting_test`. Labels are now sanitized to alphanumeric at the entity
  boundary for every path, with a GUI warning showing the rewrite.
- **NORDIC logs unresolvable** — `job_log` globbed `*_<id>.out` and missed NORDIC's
  array logs (`nordic_%A_%a.out`); a new `find_job_logs` adds the array pattern.

## [0.1.0] — 2026-07-16

First tagged release. Feature-complete across the three planned phases, with all
core stages validated live on Talapas against real data.

### Added
- **DICOM → BIDS ingestion and conversion** — DICOM sorter, inspector/classifier,
  and `dcm2bids` conversion. Validated end-to-end: output filename set is
  identical to canonical heudiconv output for the DIVATTEN dataset.
- **Preprocessing stages** — fMRIPrep, MRIQC, and NORDIC denoising, submitted via
  SLURM with dependency chaining. All validated live.
- **NORDIC → fMRIPrep chaining** — a per-project `[nordic] use_nordic` flag routes
  fMRIPrep through denoised data. NORDIC stays a pure producer; fMRIPrep's input
  is the only variable.
- **Pipeline cockpit (Project Status)** — a `(subject, session) × stage` matrix
  fusing filesystem completion with live SLURM state, with dependency-gated
  per-unit launching and a durable submission log.
- **Provenance recording** — every run records tool, version, runtime, and code
  source; duckbrain-produced derivatives carry BIDS `GeneratedBy`.
- **Consistency checker** — surfaces config-vs-provenance, container/toolbox/MATLAB
  drift, mixed provenance, staleness, and presence mismatches in the cockpit.
- **Open OnDemand app** — launches the GUI as a Batch Connect interactive app.
- **Streamlit GUI** — project setup, ingestion, conversion, preprocessing, QC, and
  job monitoring.

### Fixed
Notable bugs caught by live validation rather than unit tests:
- **MRIQC OOM** — the sbatch `--mem` and MRIQC `--mem-gb` came from one value, so
  MRIQC's soft target had no cgroup headroom. Decoupled (`--mem-gb` = alloc − 8G).
- **Surveyor false-green** — MRIQC graded complete on the anat T1w JSON alone, so
  func-crashed subjects read 🟢. Now requires func IQMs when the input has func.
- **NORDIC never ran** — three latent bugs: an m-file `DIROUT`/`fn_out` double
  path, a `{#` Jinja collision meaning the sbatch template had never rendered, and
  hardcoded `ses-` paths breaking sessionless data.
- **Provenance false positive** — drift compared a config-pinned container *tag*
  against a tool's *self-reported* version. Different namespaces: `mriqc-24.0.2.simg`
  reports `24.1.0.dev0+gd5b13cb5`. Now compares container identity.
- **Submission-log corruption** — appending a provenance row to a pre-provenance
  log made a ragged file `pd.read_csv` refuses, which would have taken down the
  log, Job Monitor, and every log-overlay check on the next launch. The header now
  migrates atomically before appending.

### Licensing
- Released under **GPL-3.0-or-later**. Supersedes an unbacked `license = "MIT"`
  claim in `pyproject.toml` (no `LICENSE` file had ever existed).

[Unreleased]: https://github.com/hulacon/duckbrain/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/hulacon/duckbrain/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/hulacon/duckbrain/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/hulacon/duckbrain/releases/tag/v0.1.0
