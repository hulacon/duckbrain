function nordic_denoise(bold_in, out_dir)
% NORDIC_DENOISE  Apply magnitude-only NORDIC thermal noise removal to a BOLD NIfTI.
%
%   nordic_denoise(bold_in, out_dir)
%
%   Inputs:
%     bold_in  - Full path to input BOLD NIfTI (.nii.gz)
%     out_dir  - Directory for denoised output (original basename preserved)
%
%   Requires NIFTI_NORDIC from the NORDIC_Raw toolbox on the MATLAB path.
%
%   Ported from mmmdata's full-scale-validated nordic_denoise.m. The output-path
%   handling matters: NIFTI_NORDIC concatenates ARG.DIROUT + fn_out + '.nii', so
%   ARG.DIROUT must be the directory (with trailing '/') and fn_out must be the
%   bare basename (NO directory component). Passing a full path as fn_out writes
%   to out_dir/out_dir/... — the bug this ported version fixes.

    if nargin < 2
        error('Usage: nordic_denoise(bold_in, out_dir)');
    end

    fprintf('=== NORDIC Denoising ===\n');
    fprintf('Input:  %s\n', bold_in);
    fprintf('Output dir: %s\n', out_dir);

    % Validate input
    if ~isfile(bold_in)
        error('Input file not found: %s', bold_in);
    end

    if ~isfolder(out_dir)
        mkdir(out_dir);
    end

    % Derive output basename (same as input, .nii.gz double extension handled).
    [~, fname, ~] = fileparts(bold_in);
    if endsWith(fname, '.nii')
        fname_base = fname(1:end-4);
    else
        fname_base = fname;
    end
    % fn_out is the bare basename; ARG.DIROUT carries the directory (see header).
    fn_out = fname_base;

    % Configure NORDIC for magnitude-only fMRI.
    ARG.DIROUT = [out_dir '/'];
    ARG.magnitude_only = 1;
    ARG.temporal_phase = 1;          % fMRI mode
    ARG.kernel_size_PCA = [];        % default (11:1 spatial:temporal ratio)
    % Leave kernel_size_gfactor at default (empty). Setting it (e.g. [14 14 1])
    % triggers a bug in NIFTI_NORDIC line ~358 that indexes element 4.
    ARG.save_add_info = 1;           % save noise estimate + degrees removed
    ARG.write_gzipped_niftis = 1;    % output .nii.gz

    fprintf('Mode:   magnitude-only\n');
    fprintf('Running NIFTI_NORDIC...\n');
    tic;

    % fn_phase_in = [] for magnitude-only.
    NIFTI_NORDIC(bold_in, [], fn_out, ARG);

    elapsed = toc;
    fprintf('Completed in %.1f minutes.\n', elapsed / 60);
end
