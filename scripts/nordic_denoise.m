function nordic_denoise(bold_in, out_dir)
% NORDIC_DENOISE  Apply NORDIC thermal noise removal to a BOLD NIfTI.
%
%   nordic_denoise(bold_in, out_dir)
%
%   Inputs:
%     bold_in  - Full path to input BOLD NIfTI (.nii.gz)
%     out_dir  - Directory for denoised output
%
%   Requires NIFTI_NORDIC from the NORDIC_Raw toolbox on the MATLAB path.
%
%   Output filename matches the input basename, written to out_dir.

    fprintf('NORDIC denoise\n');
    fprintf('  Input:  %s\n', bold_in);
    fprintf('  Output: %s\n', out_dir);

    % Ensure output directory exists
    if ~exist(out_dir, 'dir')
        mkdir(out_dir);
    end

    % Construct output path (same basename in out_dir)
    [~, fname, ext] = fileparts(bold_in);
    % Handle .nii.gz double extension
    if strcmp(ext, '.gz')
        [~, fname2, ext2] = fileparts(fname);
        fname = fname2;
    end

    fn_out = fullfile(out_dir, fname);

    % NORDIC arguments
    ARG.temporal_phase = 1;          % fMRI temporal mode
    ARG.phase_filter_width = 10;     % Phase regularization
    ARG.magnitude_only = 1;          % No phase data
    ARG.save_add_info = 1;           % Save noise estimate + degrees removed
    ARG.DIROUT = out_dir;            % Output directory
    ARG.write_gzipped_niftis = 1;    % Compress output

    % NOTE: Do NOT set ARG.kernel_size_gfactor — triggers a bug in
    % NIFTI_NORDIC line 358 (as of toolbox version ~2024).

    fprintf('  Running NIFTI_NORDIC...\n');
    NIFTI_NORDIC(bold_in, [], fn_out, ARG);

    fprintf('  Done.\n');
end
