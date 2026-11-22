import os
import sys
import glob
import math
import re
import hashlib
import subprocess
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def check_file(filepath, description):
    if not os.path.exists(filepath):
        print(f"Error: {description} '{filepath}' was not found!")
        sys.exit(1)

def _parse_resinfo_output(stdout_text, skip_names):
    last_res = None
    absolute_last_res = None
    lines = stdout_text.splitlines()
    has_header = any(line.strip().lower().startswith('#res') for line in lines)
    in_table = not has_header

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith('#res'):
            in_table = True
            continue
        if not in_table or line.startswith('#') or '---' in line:
            continue
        parts = line.split()
        if (
            len(parts) >= 5
            and parts[0].isdigit()
            and parts[2].isdigit()
            and parts[3].isdigit()
            and parts[4].isdigit()
        ):
            try:
                res_num = int(parts[0])
                if res_num < 1:
                    continue
                res_name = parts[1].lower().strip()
                absolute_last_res = res_num
                if res_name not in skip_names:
                    last_res = res_num
            except (ValueError, IndexError):
                continue
    return last_res, absolute_last_res

def get_last_residue_index(topology_path):
    # Common solvent, ion, and lipid residue names to skip
    solvent_ions_lipids = {
        'wat', 'hoh', 'tip3', 'tip3p', 'tip4', 'tip4p', 't4e', 'tip5', 'tip5p', 'opc', 'spce',
        'tip', 'sol', 'spc', 'tp3', 't3p', 'h2o',
        'na', 'cl', 'k', 'mg', 'ca', 'zn', 'na+', 'cl-', 'k+', 'mg2+', 'ca2+', 'zn2+',
        'sod', 'cla', 'pot', 'cal', 'mg+', 'cs', 'cs+', 'rb', 'rb+',
        'li', 'li+', 'f', 'f-', 'br', 'br-', 'i', 'i-', 'cio', 'ib+',
        'so4', 'po4', 'act', 'dms', 'dmso', 'gol', 'peg',
        'popc', 'pope', 'pops', 'dopc', 'dppc', 'dmpc', 'chl1', 'chol'
    }

    try:
        # 1. Prefer residues containing @CA (protein/peptide backbone) while skipping ions like Ca2+ (CA)
        ca_result = subprocess.run(
            ["cpptraj", "-p", topology_path],
            input="resinfo @CA\nexit\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )
        if ca_result.returncode == 0 and ca_result.stdout:
            last_ca_res, _ = _parse_resinfo_output(ca_result.stdout, solvent_ions_lipids)
            if last_ca_res is not None:
                return last_ca_res

        # 2. Fallback: full resinfo skipping solvent, ions, and lipids (for nucleic acids / custom polymers)
        result = subprocess.run(
            ["cpptraj", "-p", topology_path],
            input="resinfo\nexit\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        last_res, absolute_last_res = _parse_resinfo_output(result.stdout, solvent_ions_lipids)

        if last_res is not None:
            return last_res
        if absolute_last_res is not None:
            return absolute_last_res

        return None
    except Exception:
        return None


def _parse_bool(val, default=False, param_name=None):
    if isinstance(val, bool):
        return val
    if val is None:
        return default
    s = str(val).strip().lower()
    if s in ('true', '1', 'yes', 'on'):
        return True
    if s in ('false', '0', 'no', 'off'):
        return False
    if param_name:
        print(f"Warning: Invalid boolean value '{val}' for parameter '{param_name}'. Using default: {default}")
    else:
        print(f"Warning: Invalid boolean value '{val}'. Using default: {default}")
    return default


def _inspect_dssp_gnu_header(gnu_file, default_betadetail=True):
    """Parse Gnuplot header metadata (cbtics mode, ytics residue map, pm3d flag) from dssp_time.gnu."""
    has_pm3d = False
    is_betadetail = bool(default_betadetail)
    idx_to_resnum = {}
    num_ytics = 0
    ytics_buf = ""
    in_ytics = False

    def _extract_ytics(buf):
        nonlocal num_ytics
        matches = re.findall(r'''["']([^"']+)["']\s+([0-9.]+)''', buf)
        for label, tick_str in matches:
            try:
                idx = int(round(float(tick_str)))
                num_ytics = max(num_ytics, idx)
                if ':' in label:
                    res_part = label.rsplit(':', 1)[1].strip()
                    if res_part.lstrip('-').isdigit():
                        idx_to_resnum[idx] = int(res_part)
            except ValueError:
                continue

    with open(gnu_file, 'r') as f:
        for line in f:
            line_strip = line.strip()
            if not line_strip:
                continue
            line_lower = line_strip.lower()
            if in_ytics:
                ytics_buf += " " + line_strip.rstrip('\\').strip()
                if line_strip.endswith('\\') or ('(' in ytics_buf and ytics_buf.count('(') > ytics_buf.count(')')):
                    continue
                _extract_ytics(ytics_buf)
                ytics_buf = ""
                in_ytics = False
                continue

            if 'pm3d' in line_lower or 'corners2color' in line_lower:
                has_pm3d = True
            if line_lower.startswith('set cbtics'):
                if any(tok in line_lower for tok in ('"extended"', "'extended'", '"ext"', "'ext'", '"bridge"', "'bridge'")):
                    is_betadetail = False
                elif any(tok in line_lower for tok in ('"para"', "'para'", '"anti"', "'anti'")):
                    is_betadetail = True
            if line_lower.startswith('set ytics'):
                ytics_buf = line_strip.rstrip('\\').strip()
                if line_strip.endswith('\\') or ('(' in ytics_buf and ytics_buf.count('(') > ytics_buf.count(')')):
                    in_ytics = True
                    continue
                _extract_ytics(ytics_buf)
                ytics_buf = ""
            if line_lower.startswith('splot '):
                break

    if ytics_buf:
        _extract_ytics(ytics_buf)

    return has_pm3d, is_betadetail, num_ytics, idx_to_resnum


def _detect_dssp_gnu_format(gnu_file, has_pm3d):
    """Distinguish 3-column pm3d (Frame, Residue, Code) from wide matrix (Frame, C1, C2, ...)."""
    sample_col0 = []
    saw_three_cols = False
    with open(gnu_file, 'r') as f:
        for line in f:
            line_strip = line.strip()
            if not line_strip or line_strip.startswith('#'):
                continue
            parts = line_strip.split()
            if len(parts) < 2:
                continue
            try:
                vals = [float(p) for p in parts]
            except ValueError:
                continue
            if len(vals) > 3:
                return 'wide'
            if len(vals) == 3:
                saw_three_cols = True
                if has_pm3d:
                    return 'three_col'
                f0 = int(round(vals[0]))
                if f0 in sample_col0:
                    return 'three_col'
                sample_col0.append(f0)
                if len(sample_col0) >= 50:
                    break
            elif len(vals) == 2:
                # 1-residue wide matrix
                return 'wide'

    if saw_three_cols:
        # Distinct Frame values on every sampled 3-col row without pm3d indicates a 2-residue wide matrix
        return 'wide'
    return None


def parse_dssp_time_gnu(gnu_file, sec_type, default_betadetail=True):
    from collections import defaultdict
    counts = defaultdict(int)

    has_pm3d, is_betadetail, num_ytics, _ = _inspect_dssp_gnu_header(gnu_file, default_betadetail=default_betadetail)

    if is_betadetail:
        name_to_codes = {
            'para': [1],
            'anti': [2],
            'beta': [1, 2],
            '3-10': [3],
            'alpha': [4],
            'pi': [5],
            'helix': [3, 4, 5],
            'turn': [6],
            'bend': [7],
            'structured': [1, 2, 3, 4, 5],
            'canonical': [1, 2, 3, 4, 5],
            'alpha_beta': [1, 2, 3, 4, 5],
            'coil': [0],
            'none': [0]
        }
    else:
        name_to_codes = {
            'extended': [1],
            'ext': [1],
            'bridge': [2],
            'beta': [1, 2],
            '3-10': [3],
            'alpha': [4],
            'pi': [5],
            'helix': [3, 4, 5],
            'turn': [6],
            'bend': [7],
            'structured': [1, 2, 3, 4, 5],
            'canonical': [1, 2, 3, 4, 5],
            'alpha_beta': [1, 2, 3, 4, 5],
            'coil': [0],
            'none': [0]
        }

    sec_type_clean = str(sec_type).lower().strip()
    if not sec_type_clean:
        raise ValueError("secstruct_type cannot be empty.")

    allowed_codes = []

    if sec_type_clean == 'total':
        allowed_codes = [1, 2, 3, 4, 5, 6, 7]
    elif sec_type_clean in ('structured', 'canonical', 'alpha_beta'):
        allowed_codes = [1, 2, 3, 4, 5]
    else:
        # Support comma-separated strings/digits (e.g. "beta", "para,anti", or "1,2")
        parts = sec_type_clean.split(',')
        for p in parts:
            p_strip = p.strip()
            if not p_strip:
                continue
            if is_betadetail and p_strip in ('extended', 'ext', 'bridge'):
                raise ValueError(
                    f"secstruct_type='{p_strip}' is incompatible with secstruct_betadetail=true. "
                    "Set secstruct_betadetail=false in parameters.in, or use secstruct_type=beta for total beta count."
                )
            if (not is_betadetail) and p_strip in ('para', 'anti'):
                raise ValueError(
                    f"secstruct_type='{p_strip}' requires secstruct_betadetail=true in parameters.in "
                    "(with secstruct_betadetail=false, cpptraj codes 1 and 2 represent Extended and Bridge, not Parallel and Anti-parallel)."
                )
            if p_strip in name_to_codes:
                for code_val in name_to_codes[p_strip]:
                    if code_val not in allowed_codes:
                        allowed_codes.append(code_val)
            elif p_strip.isdigit():
                code_val = int(p_strip)
                if code_val < 0 or code_val > 7:
                    raise ValueError(f"Unsupported DSSP numeric code '{p_strip}' (expected 0..7).")
                if code_val not in allowed_codes:
                    allowed_codes.append(code_val)
            else:
                raise ValueError(f"Unsupported secstruct_type token '{p_strip}'.")

    if not allowed_codes:
        raise ValueError(f"No valid secondary structure types found in secstruct_type='{sec_type}'.")

    fmt = _detect_dssp_gnu_format(gnu_file, has_pm3d)
    if fmt is None:
        raise ValueError(f"No numerical DSSP data found in '{gnu_file}'.")

    allowed_set = set(allowed_codes)
    max_frame = 0
    max_res = 0
    found_any = False

    if fmt == 'wide':
        with open(gnu_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        frame = int(float(parts[0]))
                        codes = [int(float(p)) for p in parts[1:]]
                    except ValueError:
                        continue
                    found_any = True
                    if frame > max_frame:
                        max_frame = frame
                    for code in codes:
                        if code in allowed_set:
                            counts[frame] += 1
        if not found_any or max_frame < 1:
            raise ValueError(f"No valid DSSP frames found in '{gnu_file}'.")
    else:
        # 2-pass O(N_frames)-memory streaming for 3-column pm3d format
        with open(gnu_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split()
                if len(parts) == 3:
                    try:
                        frame = int(float(parts[0]))
                        res = int(float(parts[1]))
                        int(float(parts[2]))
                    except ValueError:
                        continue
                    found_any = True
                    if frame > max_frame:
                        max_frame = frame
                    if res > max_res:
                        max_res = res

        if not found_any or max_frame < 1:
            raise ValueError(f"No valid 3-column DSSP data found in '{gnu_file}'.")

        last_res_all_zero = True
        last_frame_all_zero = True
        max_res_counts = defaultdict(int)

        with open(gnu_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split()
                if len(parts) == 3:
                    try:
                        frame = int(float(parts[0]))
                        res = int(float(parts[1]))
                        code = int(float(parts[2]))
                    except ValueError:
                        continue
                    if res == max_res and code != 0:
                        last_res_all_zero = False
                    if frame == max_frame and code != 0:
                        last_frame_all_zero = False
                    if code in allowed_set:
                        if res == max_res:
                            max_res_counts[frame] += 1
                        else:
                            counts[frame] += 1

        strip_pm3d_dummy = False
        if num_ytics > 0 and max_res == num_ytics + 1 and max_frame > 1:
            strip_pm3d_dummy = True
        elif has_pm3d and max_res > 1 and max_frame > 1:
            if last_res_all_zero and last_frame_all_zero:
                strip_pm3d_dummy = True

        if strip_pm3d_dummy:
            max_frame = max_frame - 1
        else:
            for fr, cnt in max_res_counts.items():
                counts[fr] += cnt

    results = []
    for f in range(1, max_frame + 1):
        results.append((f, counts[f]))
    return results


def plot_dssp_heatmap(output_dir, default_betadetail=True):
    try:
        import pandas as pd
        import matplotlib.pyplot as plt
        from matplotlib.colors import ListedColormap

        gnu_file = os.path.join(output_dir, "dssp_time.gnu")
        output_image = os.path.join(output_dir, "dssp_heatmap.png")

        if not os.path.exists(gnu_file):
            return

        print("--> Generating 2D DSSP Heatmap...")

        has_pm3d, is_betadetail, num_ytics, idx_to_resnum = _inspect_dssp_gnu_header(gnu_file, default_betadetail=default_betadetail)
        fmt = _detect_dssp_gnu_format(gnu_file, has_pm3d)
        if fmt is None:
            print("Warning: No numerical data found in DSSP gnu file.")
            return

        # Parse the gnu file manually to extract only numerical data lines and handle formats
        data_rows = []
        with open(gnu_file, 'r') as f:
            for line in f:
                line_strip = line.strip()
                if not line_strip or line_strip.startswith('#'):
                    continue
                parts = line_strip.split()
                try:
                    # Convert to float first, to filter out text commands (e.g. "set", "splot")
                    row_vals = [float(p) for p in parts]
                    if len(row_vals) > 0:
                        data_rows.append(row_vals)
                except ValueError:
                    # Skip gnuplot script commands or text labels
                    continue

        if not data_rows:
            print("Warning: No numerical data found in DSSP gnu file.")
            return

        if fmt == 'three_col':
            # 3-column long format: Frame  Residue  Code
            df = pd.DataFrame([r for r in data_rows if len(r) == 3], columns=['Frame', 'Residue', 'Code'])
            if df.empty:
                print("Warning: No valid 3-column rows found in DSSP gnu file.")
                return
            df['Frame'] = df['Frame'].astype(int)
            df['Residue'] = df['Residue'].astype(int)
            df['Code'] = df['Code'].astype(int)
            # Pivot into index=Residue, columns=Frame, values=Code matrix
            df_matrix = df.pivot(index='Residue', columns='Frame', values='Code')

            # Remove cpptraj pm3d corner-padding dummy residue row and dummy frame column
            max_res = df_matrix.index[-1]
            max_frame = df_matrix.columns[-1]
            strip_pm3d_dummy = False
            if num_ytics > 0 and max_res == num_ytics + 1 and len(df_matrix.columns) > 1:
                strip_pm3d_dummy = True
            elif has_pm3d and len(df_matrix.index) > 1 and len(df_matrix.columns) > 1:
                if (df_matrix.loc[max_res] == 0).all() and (df_matrix[max_frame] == 0).all():
                    strip_pm3d_dummy = True

            if strip_pm3d_dummy:
                df_matrix = df_matrix.iloc[:-1, :-1]
        else:
            # Wide matrix format: Frame  Res1  Res2  ...
            df = pd.DataFrame(data_rows)
            df.iloc[:, 0] = df.iloc[:, 0].astype(int)
            df.set_index(df.columns[0], inplace=True)
            df_matrix = df.T
            # Ensure the index represents residue numbers starting from 1
            df_matrix.index = range(1, len(df_matrix) + 1)

        if df_matrix.empty:
            print("Warning: Empty DSSP matrix after parsing.")
            return

        # Map 1-based residue index to actual residue numbers if contiguous, or map Y-axis ticks
        y_tick_positions = None
        y_tick_labels = None
        if idx_to_resnum and len(idx_to_resnum) == len(df_matrix.index):
            mapped_res = [idx_to_resnum.get(i, i) for i in df_matrix.index]
            is_contiguous = (
                len(mapped_res) == 1
                or all(mapped_res[k] + 1 == mapped_res[k + 1] for k in range(len(mapped_res) - 1))
            )
            if is_contiguous:
                df_matrix.index = mapped_res
            else:
                n_res = len(mapped_res)
                step = max(1, n_res // 12)
                pos_idx = list(range(0, n_res, step))
                if pos_idx[-1] != n_res - 1:
                    pos_idx.append(n_res - 1)
                idx_list = list(df_matrix.index)
                y_tick_positions = [idx_list[k] for k in pos_idx]
                y_tick_labels = [str(mapped_res[k]) for k in pos_idx]
        elif idx_to_resnum:
            valid_ticks = sorted(i for i in idx_to_resnum if i in df_matrix.index)
            if valid_ticks:
                if len(valid_ticks) > 15:
                    step = max(1, len(valid_ticks) // 12)
                    sampled = valid_ticks[::step]
                    if sampled[-1] != valid_ticks[-1]:
                        sampled.append(valid_ticks[-1])
                    valid_ticks = sampled
                y_tick_positions = valid_ticks
                y_tick_labels = [str(idx_to_resnum[i]) for i in valid_ticks]

        cmap = ListedColormap(['white', 'cyan', 'blue', 'pink', 'red', 'magenta', 'green', 'yellow'])

        plt.figure(figsize=(15, 6))

        extent = [
            df_matrix.columns[0] - 0.5,
            df_matrix.columns[-1] + 0.5,
            df_matrix.index[0] - 0.5,
            df_matrix.index[-1] + 0.5
        ]
        im = plt.imshow(df_matrix, cmap=cmap, vmin=-0.5, vmax=7.5, aspect='auto', interpolation='nearest', extent=extent, origin='lower')

        if y_tick_positions is not None and y_tick_labels is not None:
            plt.yticks(y_tick_positions, y_tick_labels)

        # Invert y-axis so residue 1 is at the top and residue N is at the bottom
        plt.gca().invert_yaxis()

        # Add colorbar with labels matching cpptraj output mode (betadetail vs standard DSSP)
        cbar = plt.colorbar(im, ticks=range(8))
        if is_betadetail:
            tick_labels = ['Coil', 'Para-Beta', 'Anti-Beta', '3-10 Helix', 'Alpha Helix', 'Pi Helix', 'Turn', 'Bend']
        else:
            tick_labels = ['Coil', 'Extended Beta', 'Beta Bridge', '3-10 Helix', 'Alpha Helix', 'Pi Helix', 'Turn', 'Bend']
        cbar.set_ticklabels(tick_labels)
        cbar.ax.tick_params(labelsize=9)

        dir_name = os.path.basename(os.path.abspath(output_dir))
        plt.title(f"DSSP Secondary Structure Timeline ({dir_name})", fontsize=14, fontweight='bold', pad=15)
        plt.xlabel('Frame', fontsize=11, fontweight='bold')
        plt.ylabel('Residue No', fontsize=11, fontweight='bold')
        plt.tight_layout()
        plt.savefig(output_image, dpi=300)
        plt.close()
        print(f"--> DSSP Heatmap saved: {output_image}")
    except ImportError:
        print("Note: pandas not installed. Skipping DSSP Heatmap generation.")
    except Exception as e:
        print(f"Warning: Failed to generate DSSP Heatmap: {e}")

def run_script(cmd_list):
    print(f"Running command: {' '.join(cmd_list)}")
    try:
        subprocess.run(cmd_list, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error: Command failed (Exit code: {e.returncode})")
        sys.exit(1)

def validate_trajectory_type(val):
    ttype = str(val if val is not None else 'md').strip().lower()
    if ttype not in ('md', 'remd', 'mix'):
        raise ValueError(f"Invalid trajectory_type '{val}'! Must be 'md', 'remd', or 'mix'.")
    return ttype


def clean_var_filename(v):
    v_str = v.strip()
    col_suffix = ""
    if ":" in v_str:
        parts = v_str.rsplit(":", 1)
        if len(parts) == 2 and parts[1].isdigit():
            v_str = parts[0].strip()
            col_suffix = f"_col{parts[1]}"
    base = os.path.basename(v_str)
    name, _ = os.path.splitext(base)
    return f"{name.lower()}{col_suffix}"


def _is_dihedral_var(label, periodic_vars=None):
    s = str(label).upper().strip()
    s_no_colon = re.sub(r':\d+$', '', s)
    if re.match(r'^(EXT_)?(DIHEDRALS?|DIHD?|PHI|PSI|OMEGA|CHI\d*|TORSIONS?)([_.\-]|$)', s_no_colon):
        return True
    if periodic_vars:
        s_no_col = re.sub(r'_COL\d+$', '', s_no_colon)
        s_no_out = re.sub(r'_OUTPUT$', '', s_no_col)
        s_base = os.path.splitext(os.path.basename(s_no_colon))[0]
        s_ext = re.sub(r'^EXT_(.+)_[0-9A-F]{8}_\d+$', r'\1', s_base)
        candidates = {s, s_no_colon, s_no_col, s_no_out, s_base, s_ext}
        for tok in str(periodic_vars).split(','):
            t = tok.strip().upper()
            if not t:
                continue
            t_base = os.path.splitext(os.path.basename(t))[0]
            if t in candidates or (t_base and t_base in candidates):
                return True
    return False


def resolve_export_vars(cli_vars, default_var1, default_var2, default_vars=None):
    if cli_vars is not None and str(cli_vars).strip():
        parsed = [v.strip() for v in str(cli_vars).split(',') if v.strip()]
        if len(parsed) != 2:
            raise ValueError(f"Export mode requires exactly 2 variables with -v/--vars (got {len(parsed)}).")
        return parsed[0], parsed[1]
    v1 = str(default_var1).strip() if default_var1 is not None else ''
    v2 = str(default_var2).strip() if default_var2 is not None else ''
    if v1 or v2:
        return v1, v2
    if default_vars is not None and str(default_vars).strip():
        parsed = [v.strip() for v in str(default_vars).split(',') if v.strip()]
        if len(parsed) != 2:
            raise ValueError(f"Export mode requires exactly 2 variables in 'vars' (got {len(parsed)}).")
        return parsed[0], parsed[1]
    return '', ''


def cleanup_output_dir(output_dir, needs_calc, mode, dim, pca_modes_visualize, var_names=None, calc_vars=None, fel_equilibration_check=False):
    files_to_clean = []
    if needs_calc:
        if calc_vars is None:
            calc_set = {
                "PC1", "RMSD", "RG", "SASA", "HBOND",
                "DIHEDRAL", "DISTANCE1", "DISTANCE2", "SECSTRUCT"
            }
        else:
            calc_set = {str(v).upper().strip() for v in calc_vars}

        if any(v.startswith("PC") and len(v) > 2 and v[2:].isdigit() and int(v[2:]) >= 1 for v in calc_set):
            files_to_clean.extend([
                "vect.out", "avg_pca.pdb", "avg_pca.rst7", "covar.out", "pca_eigenvalues.dat",
                "cpptraj_avg.log", "cpptraj_avg_pca.log", "cpptraj_avg_pca_pdb.log",
                "cpptraj_cov.log", "cpptraj_proj.log",
                "step1_avg.in", "step1_avg_pdb.in", "step1_cov.in", "step2.in", "temp_proj.dat"
            ])
            for i in range(1, max(21, int(pca_modes_visualize) + 1)):
                files_to_clean.append(f"mode{i}.out")

        if "RMSD" in calc_set:
            files_to_clean.extend([
                "avg_rmsd.pdb", "avg_rmsd.rst7",
                "cpptraj_avg_rmsd.log", "cpptraj_avg_rmsd_pdb.log",
                "cpptraj_rmsd.log", "cpptraj_rmsd_output.log",
                "step1_avg.in", "step1_avg_pdb.in", "rmsd.in", "rmsd_output.in"
            ])

        if any(v in ("RG", "RADGYR") for v in calc_set):
            files_to_clean.extend([
                "cpptraj_rg.log", "cpptraj_rg_output.log", "rg.in", "rg_output.in"
            ])

        if "SASA" in calc_set:
            files_to_clean.extend([
                "cpptraj_sasa.log", "cpptraj_sasa_output.log", "sasa.in", "sasa_output.in"
            ])

        if any(v in ("HBOND", "HBONDS", "HYDROGENBOND", "HYDROGENBONDS") for v in calc_set):
            files_to_clean.extend([
                "cpptraj_hbond_output.log", "hbond_output.in", "hbond_output_avg.dat"
            ])

        if any(v in ("DIHEDRAL", "DIHD", "DIH", "DIHEDRALS") for v in calc_set):
            files_to_clean.extend([
                "cpptraj_dihedral_output.log", "dihedral_output.in"
            ])

        if any(v in ("DISTANCE", "DIST", "DISTANCE1", "DIST1") for v in calc_set):
            files_to_clean.extend([
                "cpptraj_distance1.log", "cpptraj_distance1_output.log", "distance1.in", "distance1_output.in"
            ])

        if any(v in ("DISTANCE2", "DIST2") for v in calc_set):
            files_to_clean.extend([
                "cpptraj_distance2.log", "cpptraj_distance2_output.log", "distance2.in", "distance2_output.in"
            ])

        if any(v in ("SECSTRUCT", "DSSP", "SECONDARYSTRUCTURE") for v in calc_set):
            files_to_clean.extend([
                "cpptraj_secstruct_output.log", "secstruct_output.in",
                "dssp_time.gnu", "dssp_sum.dat", "dssp_total_frac.dat"
            ])

    if mode == 'fel' and dim == 3 and var_names and len(var_names) >= 3:
        base_3d = f"{clean_var_filename(var_names[0])}_{clean_var_filename(var_names[1])}_{clean_var_filename(var_names[2])}_fel"
        files_to_clean.append(f"{base_3d}.html")
        files_to_clean.append(f"{base_3d}.png")

    if (mode == 'equilibration' or (mode == 'fel' and fel_equilibration_check)) and var_names and len(var_names) >= dim:
        eq_prefix = "_".join(clean_var_filename(v) for v in var_names[:dim]) + "_fel_equilibration"
        files_to_clean.append(f"{eq_prefix}.png")
        files_to_clean.append(f"{eq_prefix}.log")

    if mode == 'export':
        dir_prefix = os.path.basename(os.path.abspath(output_dir))
        files_to_clean.extend(["extract_minima.cpptraj", "export_info.log", "cpptraj_export.log", "total_data.dat"])
        export_patterns = [
            "farkli_minimum_konformasyonlar*",
            f"{dir_prefix}.pdb.*",
            f"{dir_prefix}_[0-9]*.pdb"
        ]
        for pat in export_patterns:
            for old_pdb in glob.glob(os.path.join(output_dir, pat)):
                try:
                    os.remove(old_pdb)
                except Exception:
                    pass

    files_to_clean = list(dict.fromkeys(files_to_clean))

    if files_to_clean or mode == 'export':
        print(f"\n--> Cleaning old intermediate analysis files and logs in '{output_dir}'...")

    for f in files_to_clean:
        path = os.path.join(output_dir, f)
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass


def process_variable(var_name, topology, traj_list, output_dir, config=None):
    if config is None:
        config = {}

    try:
        traj_type = validate_trajectory_type(config.get('trajectory_type', 'md'))
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    os.environ['TRAJ_TYPE'] = traj_type
    os.environ['TEMPERATURE'] = str(config.get('temperature', 310.0))
    os.environ['AUTOIMAGE'] = 'true' if _parse_bool(config.get('autoimage', 'true'), True, param_name='autoimage') else 'false'
    os.environ['DISTANCE_NOIMAGE'] = 'true' if _parse_bool(config.get('distance_noimage', 'true'), True, param_name='distance_noimage') else 'false'
    os.environ['PCA_MASS_WEIGHTED'] = 'true' if _parse_bool(config.get('pca_mass_weighted', 'false'), False, param_name='pca_mass_weighted') else 'false'
    os.environ['SASA_STRIP_SOLVENT'] = 'true' if _parse_bool(config.get('sasa_strip_solvent', 'true'), True, param_name='sasa_strip_solvent') else 'false'
    os.environ['SASA_STRIP_DIVALENT'] = 'true' if _parse_bool(config.get('sasa_strip_divalent', 'false'), False, param_name='sasa_strip_divalent') else 'false'
        
    pca_mask = config.get('pca_mask', '@CA')
    pca_modes_visualize = config.get('pca_modes_visualize', 4)
    rmsd_mask = config.get('rmsd_mask', '@CA')
    rg_mask = config.get('rg_mask', '@CA')
    sasa_mask = config.get('sasa_mask', ':1-auto&!@H*')
    hbond_mask = config.get('hbond_mask', ':1-auto')
    hbond_distance = config.get('hbond_distance', 3.0)
    hbond_angle = config.get('hbond_angle', 135.0)
    secstruct_res = config.get('secstruct_res', '1-auto')
    secstruct_type = config.get('secstruct_type', 'total')
    secstruct_betadetail = config.get('secstruct_betadetail', 'true')
    dihedral_mask1 = config.get('dihedral_mask1', ':1-13@CA')
    dihedral_mask2 = config.get('dihedral_mask2', ':14@CA')
    dihedral_mask3 = config.get('dihedral_mask3', ':49@CA')
    dihedral_mask4 = config.get('dihedral_mask4', ':50-auto@CA')
    distance1_mask1 = config.get('distance1_mask1', ':1@CA')
    distance1_mask2 = config.get('distance1_mask2', 'auto')
    distance2_mask1 = config.get('distance2_mask1', ':1@CA')
    distance2_mask2 = config.get('distance2_mask2', 'auto')
    rmsd_reference = config.get('rmsd_reference', 'average')
    # 1. Check if the variable is an existing file (optionally with a column index, e.g. file.dat:2)
    path_part = var_name.strip()
    col_index = 1  # Default to column 1 (the second column, since 0 is usually frame index)
    
    if ":" in path_part:
        parts = path_part.rsplit(":", 1)
        if len(parts) == 2 and parts[1].isdigit():
            path_part = parts[0].strip()
            col_index = int(parts[1])
            
    if os.path.isfile(path_part):
        filename = os.path.basename(path_part)
        label = os.path.splitext(filename)[0].upper()
        print(f"--> Found existing data file: {path_part} (using column {col_index})")
        
        # Save a clean copy with (Frame, Value) in the output directory, preserving original integer Frame IDs
        # so frame alignment and export mode remain accurate. Include path hash to avoid collisions.
        path_hash = hashlib.sha1(os.path.abspath(path_part).encode('utf-8')).hexdigest()[:8]
        cleaned_file = os.path.join(output_dir, f"ext_{label}_{path_hash}_{col_index}.dat")
        try:
            valid_rows = 0
            skipped_rows = 0
            with open(path_part, 'r') as f_in, open(cleaned_file, 'w') as f_out:
                frame_idx = 1
                for line in f_in:
                    line_strip = line.strip()
                    if not line_strip or line_strip.startswith('#') or line_strip.startswith('@'):
                        f_out.write(line)
                        continue
                    cols = line_strip.split()
                    if len(cols) > col_index:
                        try:
                            val_f = float(cols[col_index])
                        except ValueError:
                            if valid_rows > 0:
                                frame_idx += 1
                            skipped_rows += 1
                            continue
                        row_frame_idx = frame_idx
                        frame_idx += 1
                        if not math.isfinite(val_f):
                            skipped_rows += 1
                            continue
                        out_frame = row_frame_idx
                        if col_index > 0:
                            try:
                                fv = float(cols[0])
                                if math.isfinite(fv) and abs(fv - round(fv)) < 1e-9:
                                    out_frame = int(round(fv))
                            except ValueError:
                                out_frame = row_frame_idx
                        f_out.write(f"{out_frame}\t{cols[col_index]}\n")
                        valid_rows += 1
                    else:
                        if valid_rows > 0:
                            frame_idx += 1
                        skipped_rows += 1
            if skipped_rows > 0:
                print(f"Warning: Skipped {skipped_rows} row(s) in '{path_part}' (missing column {col_index} or non-finite value).")
            if valid_rows == 0:
                try:
                    os.remove(cleaned_file)
                except Exception:
                    pass
                print(f"Error: No valid numeric data found in '{path_part}' at column {col_index}.")
                sys.exit(1)
            return cleaned_file, f"{label}_COL{col_index}"
        except SystemExit:
            raise
        except Exception as e:
            print(f"Error parsing existing file '{path_part}': {e}")
            sys.exit(1)

    # 2. Built-in variables computed via cpptraj
    var_clean = var_name.upper().strip()
    
    # PCA Analysis (e.g., PC1, PC2)
    if var_clean.startswith("PC") and len(var_clean) > 2 and var_clean[2:].isdigit():
        pc_int = int(var_clean[2:])
        if pc_int < 1:
            print(f"Error: Invalid principal component '{var_name}'. PC index must be >= 1 (e.g., PC1, PC2).")
            sys.exit(1)
        pc_num = str(pc_int)
        output_file = os.path.join(output_dir, f"pca{pc_num}.dat")
        run_script(["bash", os.path.join(SCRIPT_DIR, "calculate_projection.sh"), topology, traj_list, pc_num, output_file, pca_mask, str(pca_modes_visualize)])
        return output_file, f"PC{pc_num}"
        
    # RMSD Analysis
    elif var_clean == "RMSD":
        output_file = os.path.join(output_dir, "rmsd_output.dat")
        run_script(["bash", os.path.join(SCRIPT_DIR, "calculate_rmsd.sh"), topology, traj_list, output_file, rmsd_mask, rmsd_reference])
        return output_file, var_clean
        
    # Radius of Gyration (Rg) Analysis
    elif var_clean in ["RG", "RADGYR"]:
        output_file = os.path.join(output_dir, "rg_output.dat")
        run_script(["bash", os.path.join(SCRIPT_DIR, "calculate_rg.sh"), topology, traj_list, output_file, rg_mask])
        return output_file, "RG"
        
    # Solvent Accessible Surface Area (SASA) Analysis
    elif var_clean == "SASA":
        output_file = os.path.join(output_dir, "sasa_output.dat")
        run_script(["bash", os.path.join(SCRIPT_DIR, "calculate_sasa.sh"), topology, traj_list, output_file, sasa_mask])
        return output_file, "SASA"
        
    # Secondary Structure (DSSP) Analysis
    elif var_clean in ["SECSTRUCT", "DSSP", "SECONDARYSTRUCTURE"]:
        output_file = os.path.join(output_dir, "secstruct_output.dat")
        os.environ['SECSTRUCT_TOTAL_FRAC_OUT'] = os.path.join(output_dir, "dssp_total_frac.dat")
        run_script(["bash", os.path.join(SCRIPT_DIR, "calculate_secstruct.sh"), topology, traj_list, output_file, secstruct_res, str(secstruct_betadetail)])
        
        # Parse dssp_time.gnu in Python to extract counts
        gnu_file = os.path.join(output_dir, "dssp_time.gnu")
        check_file(gnu_file, "DSSP time data")
        try:
            parsed_data = parse_dssp_time_gnu(
                gnu_file,
                secstruct_type,
                default_betadetail=_parse_bool(secstruct_betadetail, True, param_name='secstruct_betadetail')
            )
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
        
        # Write clean time series (Frame  Value) to secstruct_output.dat
        with open(output_file, 'w') as f_out:
            f_out.write(f"#Frame  {secstruct_type}_count\n")
            for frame, val in parsed_data:
                f_out.write(f"{frame}\t{val}\n")
                
        return output_file, "SECSTRUCT"
        
    # Hydrogen Bond (HBOND) Analysis
    elif var_clean in ["HBOND", "HBONDS", "HYDROGENBOND", "HYDROGENBONDS"]:
        output_file = os.path.join(output_dir, "hbond_output.dat")
        run_script(["bash", os.path.join(SCRIPT_DIR, "calculate_hbond.sh"), topology, traj_list, output_file, hbond_mask, str(hbond_distance), str(hbond_angle)])
        return output_file, "HBOND"
        
    # Dihedral Angle Analysis
    elif var_clean in ["DIHEDRAL", "DIHD", "DIH", "DIHEDRALS"]:
        output_file = os.path.join(output_dir, "dihedral_output.dat")
        run_script(["bash", os.path.join(SCRIPT_DIR, "calculate_dihedral.sh"), topology, traj_list, output_file, dihedral_mask1, dihedral_mask2, dihedral_mask3, dihedral_mask4])
        return output_file, "DIHEDRAL"
        
    # Distance 1 Analysis
    elif var_clean in ["DISTANCE", "DIST", "DISTANCE1", "DIST1"]:
        output_file = os.path.join(output_dir, "distance1_output.dat")
        run_script(["bash", os.path.join(SCRIPT_DIR, "calculate_distance.sh"), topology, traj_list, output_file, distance1_mask1, distance1_mask2])
        return output_file, "DISTANCE1"
        
    # Distance 2 Analysis
    elif var_clean in ["DISTANCE2", "DIST2"]:
        output_file = os.path.join(output_dir, "distance2_output.dat")
        run_script(["bash", os.path.join(SCRIPT_DIR, "calculate_distance.sh"), topology, traj_list, output_file, distance2_mask1, distance2_mask2])
        return output_file, "DISTANCE2"
        
    else:
        print(f"Error: Unsupported variable name or file not found: '{var_name}'")
        print("Supported built-in variables: PC1, PC2, ... or RMSD, RG (RADGYR), SASA, HBOND, DIHEDRAL, DISTANCE1, DISTANCE2, SECSTRUCT (DSSP)")
        print("Alternatively, you can provide the path to an existing data file (e.g., dihedral.dat or file.dat:2)")
        sys.exit(1)

def safe_input(prompt):
    sys.stdout.write(prompt)
    sys.stdout.flush()
    try:
        raw_bytes = sys.stdin.buffer.readline()
        # Decode as utf-8 but ignore any invalid bytes (e.g. copy-paste artifacts)
        return raw_bytes.decode('utf-8', errors='ignore').strip()
    except Exception:
        # Fallback if stdin buffer is not accessible
        return input().strip()

def load_parameters(config_file=None):
    defaults = {
        'mode': 'analysis',
        'trajectory_type': 'md',
        'autoimage': 'true',
        'vars': 'PC1, PC2',
        'output_dir': 'kulustur_folder',
        'dimension': 2,
        'temperature': 310.0,
        'kB': 0.001987,
        'topology': 'h2h3mono.top',
        'trajectory': 'traj.in',
        'energy_threshold_3d': 'auto',
        'bins_1d': 50,
        'bins_2d': 50,
        'bins_3d': 30,
        'plot_format_3d': 'html',
        'fel_equilibration_check': 'false',
        'fel_equilibration_blocks': 2,
        'pca_mask': '@CA',
        'pca_modes_visualize': 4,
        'pca_mass_weighted': 'false',
        'rmsd_mask': '@CA',
        'rg_mask': '@CA',
        'sasa_mask': ':1-auto&!@H*',
        'sasa_strip_solvent': 'true',
        'sasa_strip_divalent': 'false',
        'hbond_mask': ':1-auto',
        'hbond_distance': 3.0,
        'hbond_angle': 135.0,
        'secstruct_res': '1-auto',
        'secstruct_type': 'total',
        'secstruct_betadetail': 'true',
        'dihedral_mask1': ':1-13@CA',
        'dihedral_mask2': ':14@CA',
        'dihedral_mask3': ':49@CA',
        'dihedral_mask4': ':50-auto@CA',
        'periodic_vars': '',
        'distance1_mask1': ':1@CA',
        'distance1_mask2': 'auto',
        'distance2_mask1': ':1@CA',
        'distance2_mask2': 'auto',
        'distance_noimage': 'true',
        'rmsd_reference': 'average',
        'export_top_n': 10,
        'export_frames_per_well': 1,
        'export_distance_ratio': 0.10,
        'export_min_bin_count': 5,
        'export_max_dg': 'auto',
        'export_strip_solvent': 'false'
    }
    
    explicitly_passed = (config_file is not None)
    if config_file is None:
        # Fall back strictly to the global config in the script directory
        config_file = os.path.join(SCRIPT_DIR, 'parameters.in')
        
    config_file = os.path.abspath(config_file)
    print(f"--> Using configuration file: {config_file}")
    
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, val = line.split('=', 1)
                        key = key.strip()
                        val = val.strip()
                        # Convert to correct type with safe fallback
                        if key in ['temperature', 'kB', 'hbond_distance', 'hbond_angle', 'export_distance_ratio']:
                            try:
                                defaults[key] = float(val)
                            except ValueError:
                                print(f"Warning: Invalid float value '{val}' for parameter '{key}'. Using default: {defaults.get(key)}")
                        elif key in ['dimension', 'bins_1d', 'bins_2d', 'bins_3d', 'pca_modes_visualize', 'export_top_n', 'export_frames_per_well', 'export_min_bin_count', 'fel_equilibration_blocks']:
                            try:
                                defaults[key] = int(val)
                            except ValueError:
                                print(f"Warning: Invalid integer value '{val}' for parameter '{key}'. Using default: {defaults.get(key)}")
                        elif key in ['autoimage', 'fel_equilibration_check', 'pca_mass_weighted', 'sasa_strip_solvent', 'sasa_strip_divalent', 'secstruct_betadetail', 'distance_noimage', 'export_strip_solvent']:
                            val_lower = val.strip().lower()
                            if val_lower in ('true', '1', 'yes', 'on'):
                                defaults[key] = 'true'
                            elif val_lower in ('false', '0', 'no', 'off'):
                                defaults[key] = 'false'
                            else:
                                print(f"Warning: Invalid boolean value '{val}' for parameter '{key}'. Using default: {defaults.get(key)}")
                        else:
                            defaults[key] = val
        except Exception as e:
            print(f"Warning: Failed to load parameters from {config_file}: {e}")
    else:
        if explicitly_passed:
            print(f"Error: Specified parameter file '{config_file}' was not found!")
            sys.exit(1)
            
    return defaults, config_file


def merge_data_files_by_frame(data_file1, data_file2, label1, label2, combined_file):
    def read_rows_with_frames(filepath):
        rows = []
        with open(filepath, 'r') as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith('#') or s.startswith('@'):
                    continue
                parts = s.split()
                if len(parts) >= 2:
                    try:
                        val = float(parts[1])
                        if not math.isfinite(val):
                            continue
                    except ValueError:
                        continue
                    frame_id = None
                    try:
                        fv = float(parts[0])
                        if math.isfinite(fv) and abs(fv - round(fv)) < 1e-9:
                            frame_id = int(round(fv))
                    except ValueError:
                        frame_id = None
                    rows.append((frame_id, parts[0], parts[1]))
        return rows

    rows1 = read_rows_with_frames(data_file1)
    rows2 = read_rows_with_frames(data_file2)
    if not rows1 or not rows2:
        raise ValueError("One or both variable data files contain no valid data rows.")

    unique1 = all(r[0] is not None for r in rows1) and len({r[0] for r in rows1}) == len(rows1)
    unique2 = all(r[0] is not None for r in rows2) and len({r[0] for r in rows2}) == len(rows2)

    if unique1 and unique2:
        map1 = {r[0]: r[2] for r in rows1}
        map2 = {r[0]: r[2] for r in rows2}
        keys1 = set(map1.keys())
        keys2 = set(map2.keys())
        min1 = min(keys1)
        min2 = min(keys2)
        if (min1 == 0 and min2 == 1) or (min1 == 1 and min2 == 0):
            exact_shift = (
                (min1 == 0 and {k + 1 for k in keys1} == keys2)
                or (min2 == 0 and {k + 1 for k in keys2} == keys1)
            )
            shift_note = " (exact +1 frame shift)" if exact_shift else ""
            print(
                f"Warning: Potential 0-based vs 1-based Frame ID mismatch between '{label1}' (min={min1}) "
                f"and '{label2}' (min={min2}){shift_note}. Continuing with Frame ID intersection; "
                "verify whether one dataset needs a +1 frame offset."
            )
        elif min1 <= 0 or min2 <= 0:
            print("Warning: Detected non-positive Frame IDs (<= 0) when merging variables; cpptraj frame indices are 1-based.")

        common_frames = sorted(keys1 & keys2)
        if not common_frames:
            raise ValueError("No overlapping frame IDs found between the two variables.")
        if len(common_frames) != len(map1) or len(common_frames) != len(map2):
            print(
                f"--> [Info] Aligned datasets by Frame ID ({label1}: {len(map1)}, {label2}: {len(map2)}) "
                f"-> {len(common_frames)} common frames."
            )
        with open(combined_file, 'w') as out:
            out.write(f"# Frame {label1} {label2}\n")
            for fr in common_frames:
                out.write(f"{fr} {map1[fr]} {map2[fr]}\n")
        return len(common_frames)

    if len(rows1) != len(rows2):
        raise ValueError(
            f"Data lengths differ ({label1}: {len(rows1)}, {label2}: {len(rows2)}) and files do not share "
            "unique integer frame IDs for alignment."
        )

    if unique1 and all(r[0] > 0 for r in rows1):
        frame_source = [str(r[0]) for r in rows1]
    elif unique2 and all(r[0] > 0 for r in rows2):
        frame_source = [str(r[0]) for r in rows2]
    else:
        raise ValueError(
            "Export mode requires 1-based unique integer Frame IDs in at least one dataset "
            "to map extracted structures back to trajectory frames."
        )

    with open(combined_file, 'w') as out:
        out.write(f"# Frame {label1} {label2}\n")
        for fr_id, (_, _, v1), (_, _, v2) in zip(frame_source, rows1, rows2):
            out.write(f"{fr_id} {v1} {v2}\n")
    return len(rows1)


def parse_cli_arguments():
    parser = argparse.ArgumentParser(
        description="MD Analysis & FEL Automation Pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("-b", "--batch", action="store_true", help="Enable non-interactive batch mode (bypasses all prompts)")
    parser.add_argument("-p", "--params", default=None, help="Path to the configuration file (default: parameters.in in script directory)")
    parser.add_argument("-m", "--mode", choices=["analysis", "fel", "export", "equilibration", "eq"], default=None, help="Execution mode (analysis, fel, export, or equilibration/eq)")
    parser.add_argument("--eq-check", action="store_true", help="Run FEL equilibration check (block convergence analysis)")
    parser.add_argument("--eq-blocks", type=int, default=None, help="Number of equal chronological time blocks for FEL equilibration check (default: 2)")
    parser.add_argument("-d", "--dim", type=int, choices=[1, 2, 3], default=None, help="Dimension of the FEL (1, 2, or 3)")
    parser.add_argument("-t", "--top", default=None, help="Topology file path")
    parser.add_argument("-x", "--traj", default=None, help="Trajectory list file path")
    parser.add_argument("-o", "--out", default=None, help="Output directory name")
    parser.add_argument("--temp", type=float, default=None, help="Simulation temperature in Kelvin")
    parser.add_argument("-v", "--vars", default=None, help="Comma-separated list of variables for analysis/export modes (alternative to var1/2/3)")
    parser.add_argument("--var1", default=None, help="First reaction coordinate/variable")
    parser.add_argument("--var2", default=None, help="Second reaction coordinate (required for 2D/3D)")
    parser.add_argument("--var3", default=None, help="Third reaction coordinate (required for 3D)")
    
    return parser.parse_args()


def _validate_float(val, name, min_exclusive=None, min_inclusive=None):
    try:
        f = float(val)
        if not math.isfinite(f):
            raise ValueError
    except (TypeError, ValueError):
        print(f"Error: {name} must be a finite number (got '{val}')!")
        sys.exit(1)
    if min_exclusive is not None and f <= min_exclusive:
        print(f"Error: {name} must be > {min_exclusive} (got '{val}')!")
        sys.exit(1)
    if min_inclusive is not None and f < min_inclusive:
        print(f"Error: {name} must be >= {min_inclusive} (got '{val}')!")
        sys.exit(1)
    return f


def _validate_int(val, name, min_val=0):
    try:
        if isinstance(val, bool):
            raise ValueError
        if isinstance(val, float) and not val.is_integer():
            raise ValueError
        s = str(val).strip()
        if not s or (s.startswith('-') and not s[1:].isdigit()) or (not s.startswith('-') and not s.isdigit()):
            # allow float string only if integer-valued? reject non-int strings cleanly
            i = int(val)
        else:
            i = int(s)
    except (TypeError, ValueError):
        print(f"Error: {name} must be an integer (got '{val}')!")
        sys.exit(1)
    if i < min_val:
        print(f"Error: {name} must be >= {min_val} (got '{val}')!")
        sys.exit(1)
    return i


def main():
    print("--- MD Analysis & FEL Automation ---")
    
    # Parse CLI arguments
    cli_args = parse_cli_arguments()
    
    # Load default configurations
    defaults, config_file = load_parameters(cli_args.params)
    
    # Merge CLI arguments into defaults
    if cli_args.mode is not None:
        defaults['mode'] = cli_args.mode
    if cli_args.dim is not None:
        defaults['dimension'] = cli_args.dim
    if cli_args.top is not None:
        defaults['topology'] = cli_args.top
    if cli_args.traj is not None:
        defaults['trajectory'] = cli_args.traj
    if cli_args.out is not None:
        defaults['output_dir'] = cli_args.out
    if cli_args.temp is not None:
        defaults['temperature'] = cli_args.temp
    if cli_args.vars is not None:
        defaults['vars'] = cli_args.vars
    if cli_args.var1 is not None:
        defaults['var1'] = cli_args.var1
    if cli_args.var2 is not None:
        defaults['var2'] = cli_args.var2
    if cli_args.var3 is not None:
        defaults['var3'] = cli_args.var3
    if cli_args.eq_check:
        defaults['fel_equilibration_check'] = 'true'
    if cli_args.eq_blocks is not None:
        defaults['fel_equilibration_blocks'] = cli_args.eq_blocks

    # Initialize flags defensively to prevent NameError if code flow changes
    has_secstruct = False
    
    # Get masks and parameters
    autoimage = defaults.get('autoimage', 'true')
    pca_mask = defaults.get('pca_mask', '@CA')
    pca_modes_visualize = _validate_int(defaults.get('pca_modes_visualize', 4), 'pca_modes_visualize', min_val=0)
    pca_mass_weighted = defaults.get('pca_mass_weighted', 'false')
    rmsd_mask = defaults.get('rmsd_mask', '@CA')
    rg_mask = defaults.get('rg_mask', '@CA')
    sasa_mask = defaults.get('sasa_mask', ':1-auto&!@H*')
    sasa_strip_solvent = defaults.get('sasa_strip_solvent', 'true')
    sasa_strip_divalent = defaults.get('sasa_strip_divalent', 'false')
    export_min_bin_count = _validate_int(defaults.get('export_min_bin_count', 5), 'export_min_bin_count', min_val=1)
    export_max_dg = defaults.get('export_max_dg', 'auto')
    export_max_dg_norm = str(export_max_dg).strip().lower()
    if export_max_dg_norm not in ('auto', 'none', 'off', 'false', '0'):
        export_max_dg = _validate_float(export_max_dg, 'export_max_dg', min_exclusive=0.0)
    export_strip_solvent = defaults.get('export_strip_solvent', 'false')
    hbond_mask = defaults.get('hbond_mask', ':1-auto')
    hbond_distance = defaults.get('hbond_distance', 3.0)
    hbond_angle = defaults.get('hbond_angle', 135.0)
    dihedral_mask1 = defaults.get('dihedral_mask1', ':1-13@CA')
    dihedral_mask2 = defaults.get('dihedral_mask2', ':14@CA')
    dihedral_mask3 = defaults.get('dihedral_mask3', ':49@CA')
    dihedral_mask4 = defaults.get('dihedral_mask4', ':50-auto@CA')
    periodic_vars = defaults.get('periodic_vars', '')
    distance1_mask1 = defaults.get('distance1_mask1', ':1@CA')
    distance1_mask2 = defaults.get('distance1_mask2', 'auto')
    distance2_mask1 = defaults.get('distance2_mask1', ':1@CA')
    distance2_mask2 = defaults.get('distance2_mask2', 'auto')
    distance_noimage = defaults.get('distance_noimage', 'true')
    rmsd_reference = defaults.get('rmsd_reference', 'average')
    secstruct_res = defaults.get('secstruct_res', '1-auto')
    secstruct_type = defaults.get('secstruct_type', 'total')
    secstruct_betadetail = defaults.get('secstruct_betadetail', 'true')
    plot_format_3d = str(defaults.get('plot_format_3d', 'html')).lower().strip()
    if plot_format_3d not in ['html', 'png', 'both']:
        print(f"Warning: Invalid plot_format_3d '{plot_format_3d}' in config. Using default: html")
        plot_format_3d = 'html'
    fel_equilibration_check = _parse_bool(defaults.get('fel_equilibration_check', 'false'), False, param_name='fel_equilibration_check')
    fel_equilibration_blocks = _validate_int(defaults.get('fel_equilibration_blocks', 2), 'fel_equilibration_blocks', min_val=2)
        
    dim = defaults.get('dimension', 2)
    var1 = defaults.get('var1', '')
    var2 = defaults.get('var2', '')
    var3 = defaults.get('var3', '')

    try:
        validated_traj_type = validate_trajectory_type(defaults.get('trajectory_type', 'md'))
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    _validate_float(defaults.get('kB', 0.001987), 'kB', min_exclusive=0.0)
    
    # Get the output directory name first
    if cli_args.batch:
        output_dir = defaults.get('output_dir', 'kulustur_folder')
    else:
        d_dir = defaults.get('output_dir', 'kulustur_folder')
        output_dir = safe_input(f"Output directory name [default: {d_dir}]: ").strip()
        if not output_dir:
            output_dir = d_dir
    os.makedirs(output_dir, exist_ok=True)
    
    # Get execution mode (analysis, fel, export, or equilibration)
    if cli_args.batch:
        mode = str(defaults.get('mode', 'analysis')).lower().strip()
        if mode not in ['analysis', 'fel', 'export', 'equilibration', 'eq', '1', '2', '3', '4']:
            print(f"Error: Invalid mode '{mode}' in batch mode! Must be 'analysis', 'fel', 'export', 'equilibration', 'eq', '1', '2', '3', or '4'.")
            sys.exit(1)
        if mode == '1': mode = 'analysis'
        if mode == '2': mode = 'fel'
        if mode == '3': mode = 'export'
        if mode in ('4', 'eq'): mode = 'equilibration'
    else:
        d_mode = str(defaults.get('mode', 'analysis')).lower().strip()
        if d_mode in ['1', 'analysis']:
            d_mode_str = 'analysis'
        elif d_mode in ['3', 'export', 'export frames']:
            d_mode_str = 'export'
        elif d_mode in ['4', 'eq', 'equilibration', 'fel equilibration check']:
            d_mode_str = 'equilibration'
        else:
            d_mode_str = 'fel'
        
        print("Choose execution mode:")
        print(f"1. Analysis{' (default)' if d_mode_str == 'analysis' else ''}")
        print(f"2. FEL{' (default)' if d_mode_str == 'fel' else ''}")
        print(f"3. Export Frames{' (default)' if d_mode_str == 'export' else ''}")
        print(f"4. FEL Equilibration Check{' (default)' if d_mode_str == 'equilibration' else ''}")
        mode = safe_input("> ").strip().lower()
        if not mode:
            mode = d_mode_str
            
        if mode in ['1', 'analysis']:
            mode = 'analysis'
        elif mode in ['2', 'fel']:
            mode = 'fel'
        elif mode in ['3', 'export', 'export frames']:
            mode = 'export'
        elif mode in ['4', 'eq', 'equilibration', 'fel equilibration check']:
            mode = 'equilibration'
        else:
            print("Error: Mode must be 1, 2, 3, 4, 'analysis', 'fel', 'export', or 'equilibration'!")
            sys.exit(1)
            
    # Get inputs based on mode
    variables = []
    temp = defaults.get('temperature', 310.0)
    if mode == 'analysis':
        raw_vars = ""
        if cli_args.batch:
            if cli_args.vars:
                raw_vars = cli_args.vars
            elif defaults.get('vars'):
                raw_vars = defaults['vars']
            else:
                # fallback to var1, var2, var3
                fallback_list = []
                for vkey in ['var1', 'var2', 'var3']:
                    val = defaults.get(vkey, '')
                    if val:
                        fallback_list.append(val)
                raw_vars = ",".join(fallback_list)
                
            if not raw_vars:
                print("Error: No variables specified for analysis mode!")
                sys.exit(1)
        else:
            # Interactive mode
            d_vars = defaults.get('vars', '')
            if not d_vars:
                # build from var1, var2, var3 defaults
                fallback_list = []
                for vkey in ['var1', 'var2', 'var3']:
                    val = defaults.get(vkey, '')
                    if val:
                        fallback_list.append(val)
                d_vars = ", ".join(fallback_list)
            if not d_vars:
                d_vars = "PC1, PC2"
                
            print("Options: PC1, PC2, RMSD, RG, SASA, HBOND, DIHD, DIST, DSSP")
            raw_vars = safe_input(f"Enter variables to calculate (comma-separated) [default: {d_vars}]: ").strip()
            if not raw_vars:
                raw_vars = d_vars

            if validated_traj_type in ('remd', 'mix'):
                d_temp = defaults.get('temperature', 310.0)
                temp_str = safe_input(f"Target REMD temperature in Kelvin [default: {d_temp}]: ").strip()
                temp = d_temp if not temp_str else _validate_float(temp_str, "Temperature", min_exclusive=0.0)
                
        # Split and clean variables
        variables = [v.strip() for v in raw_vars.split(',') if v.strip()]
        if not variables:
            print("Error: Variable list cannot be empty!")
            sys.exit(1)
            
    elif mode == 'export':
        dim = 2
        try:
            exp_var1, exp_var2 = resolve_export_vars(
                cli_args.vars,
                defaults.get('var1', ''),
                defaults.get('var2', ''),
                defaults.get('vars', ''),
            )
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)

        if cli_args.batch:
            var1 = exp_var1
            var2 = exp_var2
            if not var1 or not var2:
                print("Error: Variable 1 and 2 must be specified for export in batch mode!")
                sys.exit(1)
            top_n = str(_validate_int(defaults.get('export_top_n', 10), 'export_top_n', min_val=1))
            frames_per_well = str(_validate_int(defaults.get('export_frames_per_well', 1), 'export_frames_per_well', min_val=1))
        else:
            print("--- Export Frames Configuration ---")
            exp_var1_def = exp_var1 or 'PC1'
            exp_var2_def = exp_var2 or 'PC2'
            var1 = safe_input(f"Variable 1 [default: {exp_var1_def}]: ").strip() or exp_var1_def
            var2 = safe_input(f"Variable 2 [default: {exp_var2_def}]: ").strip() or exp_var2_def
            if not var1 or not var2:
                print("Error: Variable 1 and Variable 2 cannot be empty!")
                sys.exit(1)
            
            d_top_n = str(defaults.get('export_top_n', 10))
            d_fpw = str(defaults.get('export_frames_per_well', 1))
            top_n_raw = safe_input(f"How many distinct local minima to find? [default: {d_top_n}]: ").strip() or d_top_n
            frames_per_well_raw = safe_input(f"How many frames to extract per minimum? [default: {d_fpw}]: ").strip() or d_fpw
            top_n = str(_validate_int(top_n_raw, 'export_top_n', min_val=1))
            frames_per_well = str(_validate_int(frames_per_well_raw, 'export_frames_per_well', min_val=1))

            d_temp = defaults.get('temperature', 310.0)
            temp_str = safe_input(f"Temperature in Kelvin [default: {d_temp}]: ").strip()
            temp = d_temp if not temp_str else _validate_float(temp_str, "Temperature", min_exclusive=0.0)
        
        _validate_int(defaults.get('bins_2d', 50), 'bins_2d', min_val=2)
        _validate_float(defaults.get('export_distance_ratio', 0.10), 'export_distance_ratio', min_inclusive=0.0)

        # Save these for later
        os.environ['EXPORT_TOP_N'] = top_n
        os.environ['EXPORT_FPW'] = frames_per_well
        
        variables = [var1, var2]
        
    else: # mode in ('fel', 'equilibration')
        if cli_args.vars is not None and str(cli_args.vars).strip():
            print(f"Warning: --vars is ignored in '{mode}' mode; please use --var1, --var2, and --var3.")

        # Get the dimension selection (1, 2, or 3)
        if cli_args.batch:
            dim = defaults.get('dimension', 2)
            if dim not in [1, 2, 3]:
                print(f"Error: Invalid dimension '{dim}' in batch mode! Must be 1, 2, or 3.")
                sys.exit(1)
        else:
            d_dim = defaults.get('dimension', 2)
            dim_str = safe_input(f"Choose dimension (1, 2, or 3) [default: {d_dim}]: ").strip()
            if not dim_str:
                dim = d_dim
            else:
                try:
                    dim = int(dim_str)
                    if dim not in [1, 2, 3]:
                        raise ValueError
                except ValueError:
                    print("Error: Dimension must be 1, 2, or 3!")
                    sys.exit(1)
                
        # Get the temperature (default: 310 K)
        if cli_args.batch:
            temp = _validate_float(defaults.get('temperature', 310.0), "Temperature", min_exclusive=0.0)
        else:
            d_temp = defaults.get('temperature', 310.0)
            temp_str = safe_input(f"Temperature in Kelvin [default: {d_temp}]: ").strip()
            temp = d_temp if not temp_str else _validate_float(temp_str, "Temperature", min_exclusive=0.0)

        # For 3D, get the energy threshold silently from parameters.in (default: auto)
        energy_threshold = "auto"
        if dim == 3:
            d_thresh = defaults.get('energy_threshold_3d', 'auto')
            if str(d_thresh).strip().lower() == "auto":
                energy_threshold = "auto"
            else:
                energy_threshold = _validate_float(d_thresh, "energy_threshold_3d", min_exclusive=0.0)

        bins_key = {1: 'bins_1d', 2: 'bins_2d', 3: 'bins_3d'}[dim]
        _validate_int(defaults.get(bins_key, 50 if dim < 3 else 30), bins_key, min_val=2)

        if mode == 'equilibration' and not cli_args.batch:
            d_blocks = fel_equilibration_blocks
            b_str = safe_input(f"Number of time blocks for equilibration check (>= 2) [default: {d_blocks}]: ").strip()
            if b_str:
                fel_equilibration_blocks = _validate_int(b_str, "fel_equilibration_blocks", min_val=2)

        # Get variables
        if cli_args.batch:
            var1 = defaults.get('var1', '')
            if not var1:
                print("Error: Variable 1 must be specified in batch mode!")
                sys.exit(1)
            var2 = defaults.get('var2', '') if dim >= 2 else None
            if dim >= 2 and not var2:
                print("Error: Variable 2 must be specified in batch mode for dimension >= 2!")
                sys.exit(1)
            var3 = defaults.get('var3', '') if dim == 3 else None
            if dim == 3 and not var3:
                print("Error: Variable 3 must be specified in batch mode for dimension 3!")
                sys.exit(1)
        else:
            print("Options: PC1, PC2, RMSD, RG, SASA, HBOND, DIHD, DIST, DSSP")
            d_var1 = defaults.get('var1', '')
            d_var2 = defaults.get('var2', '')
            d_var3 = defaults.get('var3', '')
            
            prompt_var1 = f" [default: {d_var1}]" if d_var1 else ""
            prompt_var2 = f" [default: {d_var2}]" if d_var2 else ""
            prompt_var3 = f" [default: {d_var3}]" if d_var3 else ""
            
            if dim == 1:
                var1 = safe_input(f"Variable 1{prompt_var1}: ").strip()
                if not var1:
                    var1 = d_var1
            elif dim == 2:
                var1 = safe_input(f"Variable 1{prompt_var1}: ").strip()
                if not var1:
                    var1 = d_var1
                var2 = safe_input(f"Variable 2{prompt_var2}: ").strip()
                if not var2:
                    var2 = d_var2
            else:
                var1 = safe_input(f"Variable 1{prompt_var1}: ").strip()
                if not var1:
                    var1 = d_var1
                var2 = safe_input(f"Variable 2{prompt_var2}: ").strip()
                if not var2:
                    var2 = d_var2
                var3 = safe_input(f"Variable 3{prompt_var3}: ").strip()
                if not var3:
                    var3 = d_var3
                    
            if not var1:
                print("Error: Variable 1 cannot be empty!")
                sys.exit(1)
            if dim >= 2 and not var2:
                print("Error: Variable 2 cannot be empty!")
                sys.exit(1)
            if dim == 3 and not var3:
                print("Error: Variable 3 cannot be empty!")
                sys.exit(1)

        variables = [var1]
        if dim >= 2:
            variables.append(var2)
        if dim == 3:
            variables.append(var3)

    # Validate final temperature before running calculations
    final_temp = _validate_float(temp, "Temperature", min_exclusive=0.0)

    # Check if calculation is needed for any variable
    needs_calc = False
    calc_vars = []
    for v in variables:
        path_part = v.strip()
        if ":" in path_part:
            parts = path_part.rsplit(":", 1)
            if len(parts) == 2 and parts[1].isdigit():
                path_part = parts[0].strip()
        if not os.path.isfile(path_part):
            needs_calc = True
            calc_vars.append(v.upper().strip())

    # Validate HBOND geometry cutoffs early if HBOND will be calculated
    if any(vc in ["HBOND", "HBONDS", "HYDROGENBOND", "HYDROGENBONDS"] for vc in calc_vars):
        hbond_distance = _validate_float(hbond_distance, "hbond_distance", min_exclusive=0.0)
        hb_ang_f = _validate_float(hbond_angle, "hbond_angle")
        if hb_ang_f != -1.0 and not (0.0 <= hb_ang_f <= 180.0):
            print(f"Error: hbond_angle must be -1 (disabled) or within [0, 180] (got '{hbond_angle}')!")
            sys.exit(1)
        hbond_angle = hb_ang_f

    # Get topology and trajectory if needed (always needed in export mode for frame extraction)
    topology = None
    traj_list = None
    if needs_calc or mode == 'export':
        # Get topology
        if cli_args.batch:
            topology = defaults.get('topology', '')
            if not topology:
                print("Error: Topology file path must be specified in batch mode (via CLI or config file)!")
                sys.exit(1)
        else:
            d_top = defaults.get('topology', '')
            prompt_top = f" [default: {d_top}]" if d_top else ""
            topology = safe_input(f"Topology file path{prompt_top}: ").strip()
            if not topology:
                topology = d_top
        check_file(topology, "Topology file")
        
        # Get trajectory
        if cli_args.batch:
            traj_list = defaults.get('trajectory', '')
            if not traj_list:
                print("Error: Trajectory list file path must be specified in batch mode (via CLI or config file)!")
                sys.exit(1)
        else:
            d_traj = defaults.get('trajectory', '')
            prompt_traj = f" [default: {d_traj}]" if d_traj else ""
            traj_list = safe_input(f"Trajectory list file path{prompt_traj}: ").strip()
            if not traj_list:
                traj_list = d_traj
        check_file(traj_list, "Trajectory list file")

    # Compute highest requested PC index so calculate_projection.sh generates enough eigenvectors on first run
    max_pc_requested = 10
    for vc in calc_vars:
        if vc.startswith("PC") and len(vc) > 2 and vc[2:].isdigit():
            pc_idx = int(vc[2:])
            if pc_idx < 1:
                print(f"Error: Invalid principal component '{vc}'. PC index must be >= 1 (e.g., PC1, PC2).")
                sys.exit(1)
            max_pc_requested = max(max_pc_requested, pc_idx)
    os.environ['MAX_PC_REQUESTED'] = str(max_pc_requested)
    
    # Resolve masks only if calculations are needed
    if needs_calc:
        # Caching variables to query cpptraj at most once for last residue index
        last_res_idx = None
        queried_last_res = False

        def _require_last_res(context_label):
            nonlocal last_res_idx, queried_last_res
            if not queried_last_res:
                last_res_idx = get_last_residue_index(topology)
                queried_last_res = True
            if last_res_idx is None:
                print(
                    f"Error: Could not automatically detect the last solute residue index from topology '{topology}' "
                    f"(needed for {context_label}). Please replace 'auto' with an explicit residue number in your configuration."
                )
                sys.exit(1)
            return last_res_idx

        def _resolve_mask(mask_val, standalone_ca=False):
            s = str(mask_val)
            if standalone_ca and s.strip().lower() == 'auto':
                return f":{last_res_idx}@CA"
            return re.sub(r'auto', str(last_res_idx), s, flags=re.IGNORECASE)

        # Check for Distance 1
        has_dist1 = any(v in ["DISTANCE", "DIST", "DISTANCE1", "DIST1"] for v in calc_vars)
        if has_dist1 and ("auto" in str(distance1_mask1).lower() or "auto" in str(distance1_mask2).lower()):
            print("--> Auto-detecting last residue index from topology for Distance 1...")
            _require_last_res("Distance 1")
            if "auto" in str(distance1_mask1).lower():
                distance1_mask1 = _resolve_mask(distance1_mask1, standalone_ca=True)
            if "auto" in str(distance1_mask2).lower():
                distance1_mask2 = _resolve_mask(distance1_mask2, standalone_ca=True)
            print(f"--> Auto-detected Distance 1 masks: {distance1_mask1}, {distance1_mask2}")

        # Check for Distance 2
        has_dist2 = any(v in ["DISTANCE2", "DIST2"] for v in calc_vars)
        if has_dist2 and ("auto" in str(distance2_mask1).lower() or "auto" in str(distance2_mask2).lower()):
            print("--> Auto-detecting last residue index from topology for Distance 2...")
            _require_last_res("Distance 2")
            if "auto" in str(distance2_mask1).lower():
                distance2_mask1 = _resolve_mask(distance2_mask1, standalone_ca=True)
            if "auto" in str(distance2_mask2).lower():
                distance2_mask2 = _resolve_mask(distance2_mask2, standalone_ca=True)
            print(f"--> Auto-detected Distance 2 masks: {distance2_mask1}, {distance2_mask2}")

        # Check for SASA
        has_sasa = any(v == "SASA" for v in calc_vars)
        if has_sasa and "auto" in str(sasa_mask).lower():
            print("--> Auto-detecting last residue index for SASA mask...")
            _require_last_res("SASA")
            sasa_mask = _resolve_mask(sasa_mask)
            print(f"--> Auto-detected SASA mask: {sasa_mask}")

        # Check for HBOND
        has_hbond = any(v in ["HBOND", "HBONDS", "HYDROGENBOND", "HYDROGENBONDS"] for v in calc_vars)
        if has_hbond and "auto" in str(hbond_mask).lower():
            print("--> Auto-detecting last residue index for Hydrogen Bond mask...")
            _require_last_res("HBOND")
            hbond_mask = _resolve_mask(hbond_mask)
            print(f"--> Auto-detected Hydrogen Bond mask: {hbond_mask}")

        # Check for SECSTRUCT
        has_secstruct = any(v in ["SECSTRUCT", "DSSP", "SECONDARYSTRUCTURE"] for v in calc_vars)
        if has_secstruct and "auto" in str(secstruct_res).lower():
            print("--> Auto-detecting last residue index for Secondary Structure (DSSP) mask...")
            _require_last_res("SECSTRUCT")
            secstruct_res = _resolve_mask(secstruct_res)
            print(f"--> Auto-detected Secondary Structure mask: {secstruct_res}")

        # Check for DIHEDRAL
        has_dihedral = any(v in ["DIHEDRAL", "DIHD", "DIH", "DIHEDRALS"] for v in calc_vars)
        if has_dihedral:
            needs_auto = any("auto" in str(m).lower() for m in [dihedral_mask1, dihedral_mask2, dihedral_mask3, dihedral_mask4])
            if needs_auto:
                print("--> Auto-detecting last residue index for Dihedral masks...")
                _require_last_res("DIHEDRAL")
                dihedral_mask1 = _resolve_mask(dihedral_mask1)
                dihedral_mask2 = _resolve_mask(dihedral_mask2)
                dihedral_mask3 = _resolve_mask(dihedral_mask3)
                dihedral_mask4 = _resolve_mask(dihedral_mask4)
                print(f"--> Resolved Dihedral masks: {dihedral_mask1}, {dihedral_mask2}, {dihedral_mask3}, {dihedral_mask4}")
    
    # Clean up old intermediate files and logs from previous runs only when relevant
    cleanup_output_dir(
        output_dir,
        needs_calc=needs_calc,
        mode=mode,
        dim=dim,
        pca_modes_visualize=pca_modes_visualize,
        var_names=[var1, var2, var3][:dim] if mode in ('fel', 'equilibration') else None,
        calc_vars=calc_vars,
        fel_equilibration_check=fel_equilibration_check,
    )

    analysis_config = {
        'trajectory_type': validated_traj_type,
        'temperature': final_temp,
        'autoimage': autoimage,
        'pca_mask': pca_mask,
        'pca_modes_visualize': pca_modes_visualize,
        'pca_mass_weighted': pca_mass_weighted,
        'rmsd_mask': rmsd_mask,
        'rg_mask': rg_mask,
        'sasa_mask': sasa_mask,
        'sasa_strip_solvent': sasa_strip_solvent,
        'sasa_strip_divalent': sasa_strip_divalent,
        'hbond_mask': hbond_mask,
        'hbond_distance': hbond_distance,
        'hbond_angle': hbond_angle,
        'secstruct_res': secstruct_res,
        'secstruct_type': secstruct_type,
        'secstruct_betadetail': secstruct_betadetail,
        'dihedral_mask1': dihedral_mask1,
        'dihedral_mask2': dihedral_mask2,
        'dihedral_mask3': dihedral_mask3,
        'dihedral_mask4': dihedral_mask4,
        'distance1_mask1': distance1_mask1,
        'distance1_mask2': distance1_mask2,
        'distance2_mask1': distance2_mask1,
        'distance2_mask2': distance2_mask2,
        'distance_noimage': distance_noimage,
        'rmsd_reference': rmsd_reference,
        'plot_format_3d': plot_format_3d
    }

    if mode == 'analysis':
        # Step 1: Run calculations
        print("\n>>> STEP 1: Running Analysis Scripts <<<")
        calculated_files = []
        for var in variables:
            data_file, label = process_variable(var, topology, traj_list, output_dir, analysis_config)
            check_file(data_file, f"Analysis output for {var}")
            calculated_files.append((var, data_file))
            
        # Generate 2D Heatmap if secondary structure analysis was performed
        has_secstruct = any(v in ["SECSTRUCT", "DSSP", "SECONDARYSTRUCTURE"] for v in calc_vars)
        if has_secstruct:
            plot_dssp_heatmap(output_dir, default_betadetail=_parse_bool(secstruct_betadetail, True, param_name='secstruct_betadetail'))
            
        print(f"\n[Success] Analysis completed! Calculated files:")
        for var, path in calculated_files:
            print(f"  - {var}: {path}")
            
    elif mode in ('fel', 'equilibration'):
        # Step 1: Run calculations
        print("\n>>> STEP 1: Running Analysis Scripts <<<")
        if dim == 1:
            data_file1, label1 = process_variable(var1, topology, traj_list, output_dir, analysis_config)
            check_file(data_file1, f"Analysis output for {var1}")
            plot_args_base = [data_file1, label1]
        elif dim == 2:
            data_file1, label1 = process_variable(var1, topology, traj_list, output_dir, analysis_config)
            data_file2, label2 = process_variable(var2, topology, traj_list, output_dir, analysis_config)
            check_file(data_file1, f"Analysis output for {var1}")
            check_file(data_file2, f"Analysis output for {var2}")
            plot_args_base = [data_file1, data_file2, label1, label2]
        else:
            data_file1, label1 = process_variable(var1, topology, traj_list, output_dir, analysis_config)
            data_file2, label2 = process_variable(var2, topology, traj_list, output_dir, analysis_config)
            data_file3, label3 = process_variable(var3, topology, traj_list, output_dir, analysis_config)
            check_file(data_file1, f"Analysis output for {var1}")
            check_file(data_file2, f"Analysis output for {var2}")
            check_file(data_file3, f"Analysis output for {var3}")
            plot_args_base = [data_file1, data_file2, data_file3, label1, label2, label3]

        eq_prefix = "_".join(clean_var_filename(v) for v in variables)
        eq_image = os.path.join(output_dir, f"{eq_prefix}_fel_equilibration.png")
        eq_log = os.path.splitext(eq_image)[0] + ".log"

        output_image = None
        if mode == 'fel':
            # Step 2: Plot the Free Energy Landscape (FEL)
            print("\n>>> STEP 2: Plotting Free Energy Landscape (FEL) <<<")
            if dim == 1:
                output_image = os.path.join(output_dir, f"{clean_var_filename(var1)}_fel.png")
                run_script([sys.executable, os.path.join(SCRIPT_DIR, "plot_fel.py"), data_file1, label1, output_image, "--temp", str(final_temp), "--config", config_file])
            elif dim == 2:
                output_image = os.path.join(output_dir, f"{clean_var_filename(var1)}_{clean_var_filename(var2)}_fel.png")
                run_script([sys.executable, os.path.join(SCRIPT_DIR, "plot_fel.py"), data_file1, data_file2, label1, label2, output_image, "--temp", str(final_temp), "--config", config_file])
            else:
                ext = ".html" if plot_format_3d in ['html', 'both'] else ".png"
                output_image = os.path.join(output_dir, f"{clean_var_filename(var1)}_{clean_var_filename(var2)}_{clean_var_filename(var3)}_fel{ext}")
                run_script([sys.executable, os.path.join(SCRIPT_DIR, "plot_fel.py"), data_file1, data_file2, data_file3, label1, label2, label3, output_image, "--temp", str(final_temp), "--threshold", str(energy_threshold), "--format", plot_format_3d, "--config", config_file])

            if fel_equilibration_check:
                print(f"\n>>> STEP 2b: Running FEL Equilibration Check ({fel_equilibration_blocks} Blocks) <<<")
                run_script([sys.executable, os.path.join(SCRIPT_DIR, "plot_fel.py"), *plot_args_base, eq_image, "--temp", str(final_temp), "--config", config_file, "--equilibration", "--eq-blocks", str(fel_equilibration_blocks)])
        else:
            print(f"\n>>> STEP 2: Running FEL Equilibration Check ({fel_equilibration_blocks} Blocks) <<<")
            run_script([sys.executable, os.path.join(SCRIPT_DIR, "plot_fel.py"), *plot_args_base, eq_image, "--temp", str(final_temp), "--config", config_file, "--equilibration", "--eq-blocks", str(fel_equilibration_blocks)])

        # Generate 2D Heatmap if secondary structure analysis was performed
        has_secstruct = any(v in ["SECSTRUCT", "DSSP", "SECONDARYSTRUCTURE"] for v in calc_vars)
        if has_secstruct:
            plot_dssp_heatmap(output_dir, default_betadetail=_parse_bool(secstruct_betadetail, True, param_name='secstruct_betadetail'))

        if mode == 'fel':
            print(f"\n[Success] Process completed! Your plot has been created: {output_image}")
            if dim == 3 and plot_format_3d == 'both':
                png_output = os.path.splitext(output_image)[0] + ".png"
                print(f"                                                     and: {png_output}")
            if fel_equilibration_check:
                print(f"          Equilibration plot: {eq_image}")
                print(f"          Equilibration log : {eq_log}")
        else:
            print(f"\n[Success] FEL Equilibration Check completed!")
            print(f"  - Plot  : {eq_image}")
            print(f"  - Report: {eq_log}")
            
    elif mode == 'export':
        # Step 1: Run calculations
        print("\n>>> STEP 1: Running Analysis Scripts for Export <<<")
        data_file1, label1 = process_variable(variables[0], topology, traj_list, output_dir, analysis_config)
        data_file2, label2 = process_variable(variables[1], topology, traj_list, output_dir, analysis_config)
        check_file(data_file1, f"Analysis output for {variables[0]}")
        check_file(data_file2, f"Analysis output for {variables[1]}")
        
        # Merge the two files safely by Frame ID (preventing frame desynchronization)
        combined_file = os.path.join(output_dir, "total_data.dat")
        print(f"--> Merging data into {combined_file}")
        try:
            merge_data_files_by_frame(data_file1, data_file2, label1, label2, combined_file)
        except Exception as e:
            print(f"Error merging files: {e}")
            sys.exit(1)
            
        # Run farkli_min_bulma.sh
        top_n = os.environ.get('EXPORT_TOP_N', '10')
        fpw = os.environ.get('EXPORT_FPW', '1')
        top_file = os.path.abspath(topology)
        traj_file = os.path.abspath(traj_list)
        bins = str(defaults.get('bins_2d', 50))
        dist_ratio = str(defaults.get('export_distance_ratio', 0.10))
        os.environ['VAR1_LABEL'] = label1
        os.environ['VAR2_LABEL'] = label2
        is_per1 = _is_dihedral_var(label1, periodic_vars) or _is_dihedral_var(variables[0], periodic_vars)
        is_per2 = _is_dihedral_var(label2, periodic_vars) or _is_dihedral_var(variables[1], periodic_vars)
        os.environ['VAR1_PERIODIC'] = 'true' if is_per1 else 'false'
        os.environ['VAR2_PERIODIC'] = 'true' if is_per2 else 'false'
        os.environ['EXPORT_PREFIX'] = os.path.basename(os.path.abspath(output_dir))
        os.environ['AUTOIMAGE'] = 'true' if _parse_bool(autoimage, True, param_name='autoimage') else 'false'
        os.environ['EXPORT_MIN_BIN_COUNT'] = str(export_min_bin_count)
        os.environ['EXPORT_MAX_DG'] = str(export_max_dg).strip()
        os.environ['EXPORT_STRIP_SOLVENT'] = 'true' if _parse_bool(export_strip_solvent, False, param_name='export_strip_solvent') else 'false'
        os.environ['SASA_STRIP_DIVALENT'] = 'true' if _parse_bool(sasa_strip_divalent, False, param_name='sasa_strip_divalent') else 'false'
        os.environ['TEMPERATURE'] = str(final_temp)
        os.environ['kB'] = str(defaults.get('kB', 0.001987))
        if defaults.get('energy_unit'):
            os.environ['ENERGY_UNIT'] = str(defaults.get('energy_unit')).strip()
        else:
            os.environ.pop('ENERGY_UNIT', None)
        os.environ['TRAJ_TYPE'] = validated_traj_type
        os.environ['ORIG_CWD'] = os.getcwd()
        
        script_path = os.path.join(SCRIPT_DIR, "farkli_min_bulma.sh")
        print("\n>>> STEP 2: Finding Local Minima and Extracting Frames <<<")
        
        combined_file_absolute = os.path.abspath(combined_file)
        cmd = ["bash", script_path, combined_file_absolute, top_file, traj_file, bins, top_n, fpw, dist_ratio]
        # Execute it from within the output directory so generated files go there
        print(f"Running command: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True, cwd=output_dir)
            print(f"\n[Success] Frames extracted! Check the {output_dir} directory.")
        except subprocess.CalledProcessError as e:
            print(f"Error: Command failed (Exit code: {e.returncode})")
            sys.exit(1)
            
        print("\n>>> STEP 3: Plotting Free Energy Landscape (FEL) <<<")
        var1_name = clean_var_filename(variables[0])
        var2_name = clean_var_filename(variables[1])
        output_image = os.path.join(output_dir, f"{var1_name}_{var2_name}_fel.png")
        run_script([sys.executable, os.path.join(SCRIPT_DIR, "plot_fel.py"), data_file1, data_file2, label1, label2, output_image, "--temp", str(final_temp), "--config", config_file])
        
        # Generate 2D Heatmap if secondary structure analysis was performed
        has_secstruct = any(v in ["SECSTRUCT", "DSSP", "SECONDARYSTRUCTURE"] for v in calc_vars)
        if has_secstruct:
            plot_dssp_heatmap(output_dir, default_betadetail=_parse_bool(secstruct_betadetail, True, param_name='secstruct_betadetail'))
        
        print(f"\n[Success] Export process completed! PDBs extracted and plot created: {output_image}")

if __name__ == "__main__":
    main()
