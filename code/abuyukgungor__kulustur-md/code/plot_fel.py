import sys
import os
import re
import argparse
import numpy as np
import matplotlib.pyplot as plt

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def load_parameters(config_file=None):
    defaults = {
        'kB': 0.001987,
        'bins_1d': 50,
        'bins_2d': 50,
        'bins_3d': 30,
        'color_1d': '#1f77b4',
        'colormap_2d': 'viridis',
        'colormap_3d': 'Jet',
        'plot_title': 'Free Energy Landscape ({dir_name})',
        'plot_format_3d': 'html',
        'energy_unit': '',
        'periodic_vars': '',
        'fel_equilibration_check': 'false',
        'fel_equilibration_blocks': 2
    }
    
    if config_file is None:
        config_file = os.path.join(SCRIPT_DIR, 'parameters.in')
        
    config_file = os.path.abspath(config_file)
    
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
                        if key in ['kB', 'temperature']:
                            try:
                                defaults[key] = float(val)
                            except ValueError:
                                fallback = defaults.get(key, 310.0 if key == 'temperature' else 0.0)
                                defaults[key] = fallback
                                print(f"Warning: Invalid float value '{val}' for parameter '{key}'. Using default: {fallback}")
                        elif key in ['bins_1d', 'bins_2d', 'bins_3d', 'fel_equilibration_blocks']:
                            try:
                                defaults[key] = int(val)
                            except ValueError:
                                print(f"Warning: Invalid integer value '{val}' for parameter '{key}'. Using default: {defaults.get(key)}")
                        elif key == 'fel_equilibration_check':
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
    return defaults

def get_custom_label(var_label, defaults):
    clean = str(var_label).lower().strip()
    key = f"label_{clean}"
    if key in defaults:
        return defaults[key]
    base = re.sub(r'_col\d+$', '', clean)
    if f"label_{base}" in defaults:
        return defaults[f"label_{base}"]
    base_no_out = re.sub(r'_output$', '', base)
    if f"label_{base_no_out}" in defaults:
        return defaults[f"label_{base_no_out}"]
    return var_label

def get_energy_unit(defaults):
    unit = str(defaults.get('energy_unit', '')).strip()
    if unit:
        return unit
    try:
        kb_val = float(defaults.get('kB', 0.001987))
        if abs(kb_val - 0.008314) < 0.001:
            return 'kJ/mol'
    except (TypeError, ValueError):
        pass
    return 'kcal/mol'

def resolve_colormap(name, default='viridis'):
    import matplotlib as mpl
    name_clean = str(name).strip()
    if hasattr(mpl, 'colormaps'):
        available_cmaps = list(mpl.colormaps.keys())
    else:
        available_cmaps = plt.colormaps()
    cmap_lower = name_clean.lower()
    for c in available_cmaps:
        if c.lower() == cmap_lower:
            return c
    print(f"Warning: Invalid or unsupported Matplotlib colormap '{name}'. Using default: '{default}'.")
    return default

def resolve_plotly_colorscale(name, default='Jet'):
    import plotly.colors as pc
    name_clean = str(name).strip()
    named = []
    if hasattr(pc, 'named_colorscales'):
        named = list(pc.named_colorscales())
    else:
        for mod_name in ('sequential', 'diverging', 'cyclical'):
            mod = getattr(pc, mod_name, None)
            if mod is not None:
                named.extend(k for k in dir(mod) if not k.startswith('_'))
    if not named:
        return name_clean or default
    name_lower = name_clean.lower()
    for c in named:
        if str(c).lower() == name_lower:
            return name_clean
    print(f"Warning: Invalid or unsupported Plotly 3D colorscale '{name}'. Using default: '{default}'.")
    return default

DEFAULTS = None
LAST_CONFIG_FILE = None
kB = 0.001987

def get_defaults(config_file=None):
    global DEFAULTS, kB, LAST_CONFIG_FILE
    if config_file is not None:
        resolved_config = os.path.abspath(config_file)
    elif DEFAULTS is None:
        resolved_config = os.path.abspath(os.path.join(SCRIPT_DIR, 'parameters.in'))
    else:
        resolved_config = None

    if DEFAULTS is None or (resolved_config is not None and resolved_config != LAST_CONFIG_FILE):
        DEFAULTS = load_parameters(resolved_config)
        kB = DEFAULTS.get('kB', 0.001987)
        if resolved_config is not None:
            LAST_CONFIG_FILE = resolved_config
    return DEFAULTS

def _is_dihedral_label(label, defaults=None):
    s = str(label).upper().strip()
    if re.match(r'^(EXT_)?(DIHEDRALS?|DIHD?|PHI|PSI|OMEGA|CHI\d*|TORSIONS?)([_.\-]|$)', s):
        return True
    cfg = defaults if defaults is not None else (DEFAULTS or {})
    raw_pvars = str(cfg.get('periodic_vars', '')).strip()
    if raw_pvars:
        s_no_col = re.sub(r'_COL\d+$', '', s)
        s_no_out = re.sub(r'_OUTPUT$', '', s_no_col)
        s_base = os.path.splitext(os.path.basename(s))[0]
        s_ext = re.sub(r'^EXT_(.+)_[0-9A-F]{8}_\d+$', r'\1', s_base)
        candidates = {s, s_no_col, s_no_out, s_base, s_ext}
        for tok in raw_pvars.split(','):
            t = tok.strip().upper()
            if not t:
                continue
            t_base = os.path.splitext(os.path.basename(t))[0]
            if t in candidates or (t_base and t_base in candidates):
                return True
    return False

def _validate_fel_params(T, kB_val, nbins):
    if T is None or not np.isfinite(T) or T <= 0:
        raise ValueError(f"Temperature must be a positive number (got {T}).")
    if kB_val is None or not np.isfinite(kB_val) or kB_val <= 0:
        raise ValueError(f"Boltzmann constant kB must be a positive number (got {kB_val}).")
    if nbins is None or int(nbins) < 2:
        raise ValueError(f"Bin count must be an integer >= 2 (got {nbins}).")

def load_data_with_frames(filepath):
    # Reads cpptraj data file, skipping comments (# or @) and extracts
    # (frame_id_or_None, value_float).
    frames = []
    data = []
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('@'):
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    val = float(parts[1])
                except ValueError:
                    continue
                if not np.isfinite(val):
                    continue
                frame_id = None
                try:
                    f_val = float(parts[0])
                    if np.isfinite(f_val) and abs(f_val - round(f_val)) < 1e-9:
                        frame_id = int(round(f_val))
                except ValueError:
                    frame_id = None
                frames.append(frame_id)
                data.append(val)
    arr = np.array(data, dtype=float)
    has_unique_int_frames = (
        len(arr) > 0
        and all(fr is not None for fr in frames)
        and len(set(frames)) == len(frames)
    )
    return frames, arr, has_unique_int_frames

def load_data(filepath):
    # Reads cpptraj data file, skipping comments (# or @) and extracts
    # the value from the second column (index 1).
    _, arr, _ = load_data_with_frames(filepath)
    return arr

def align_datasets(*datasets):
    if not datasets:
        return []
    for _, values, label in datasets:
        if len(values) == 0:
            raise ValueError(f"No readable numeric data found for '{label}'.")

    all_unique = all(
        len(frames) == len(values)
        and all(fr is not None and isinstance(fr, (int, np.integer)) for fr in frames)
        and len(set(int(fr) for fr in frames)) == len(frames)
        for frames, values, _ in datasets
    )

    if all_unique:
        dicts = [
            {int(fr): float(val) for fr, val in zip(frames, values)}
            for frames, values, _ in datasets
        ]
        key_sets = [set(d.keys()) for d in dicts]
        mins = [min(ks) for ks in key_sets]
        if 0 in mins and 1 in mins:
            zero_idx = [i for i, m in enumerate(mins) if m == 0]
            one_idx = [i for i, m in enumerate(mins) if m == 1]
            exact_shift = any(
                {k + 1 for k in key_sets[zi]} == key_sets[oi]
                for zi in zero_idx
                for oi in one_idx
            )
            lbl_zero = ", ".join(datasets[i][2] for i in zero_idx)
            lbl_one = ", ".join(datasets[i][2] for i in one_idx)
            shift_note = " (exact +1 frame shift)" if exact_shift else ""
            print(
                f"Warning: Potential 0-based vs 1-based Frame ID mismatch between 0-based '{lbl_zero}' "
                f"and 1-based '{lbl_one}'{shift_note}. Continuing with Frame ID intersection; "
                "verify whether one dataset needs a +1 frame offset."
            )
        common_frames = sorted(set.intersection(*key_sets))
        if not common_frames:
            raise ValueError("No overlapping frame IDs found across datasets; cannot synchronize frames.")
        if any(len(d) != len(common_frames) for d in dicts):
            orig_desc = ", ".join(f"{lbl}: {len(d)}" for (_, _, lbl), d in zip(datasets, dicts))
            print(f"--> [Info] Aligned datasets by Frame ID ({orig_desc}) -> {len(common_frames)} common frames.")
        return [np.array([d[fr] for fr in common_frames], dtype=float) for d in dicts]

    lens = [len(values) for _, values, _ in datasets]
    if len(set(lens)) != 1:
        desc = ", ".join(f"{lbl}: {len(values)}" for _, values, lbl in datasets)
        raise ValueError(
            f"Data lengths differ ({desc}) and datasets do not share unique integer frame IDs for alignment. "
            "Frame synchronization is not guaranteed."
        )
    return [np.asarray(values, dtype=float) for _, values, _ in datasets]

def _compute_bins(arr, nbins, is_periodic_dihedral=False, max_unit_span=100):
    if is_periodic_dihedral:
        arr_w = ((arr + 180.0) % 360.0) - 180.0
        return arr_w, np.linspace(-180.0, 180.0, int(nbins) + 1), False

    is_discrete = bool(np.all(np.abs(arr - np.round(arr)) < 1e-9))
    if is_discrete:
        vmin = int(np.round(np.min(arr)))
        vmax = int(np.round(np.max(arr)))
        span = vmax - vmin + 1
        if span <= max_unit_span:
            w = 1
        else:
            w = max(1, int(np.ceil(span / float(nbins))))
        num_bins = int(np.ceil(span / float(w)))
        edges = (vmin - 0.5) + np.arange(num_bins + 1) * float(w)
        return arr, edges, True

    if np.min(arr) == np.max(arr):
        val = float(arr[0])
        return arr, np.array([val - 0.5, val + 0.5], dtype=float), False

    return arr, int(nbins), False

def plot_1d(file1, label1, output_image, T=310.0, config_file=None):
    print(f"--> Loading 1D data: {file1}...")
    _, x_raw, _ = load_data_with_frames(file1)
    
    if len(x_raw) == 0:
        raise ValueError("No readable numeric data found in 1D data file.")
        
    print("--> Calculating 1D histogram and Free Energy Landscape...")
    defaults = get_defaults(config_file)
    kB = defaults.get('kB', 0.001987)
    nbins = defaults.get('bins_1d', 50)
    energy_unit = get_energy_unit(defaults)
    _validate_fel_params(T, kB, nbins)

    per1 = _is_dihedral_label(label1, defaults)
    x, bins_x, _ = _compute_bins(x_raw, nbins, is_periodic_dihedral=per1)
        
    hist, xedges = np.histogram(x, bins=bins_x, density=True)
    
    hist = np.where(hist == 0, np.nan, hist)
    
    with np.errstate(divide='ignore', invalid='ignore'):
        G = -(kB * T) * np.log(hist)
    G = G - np.nanmin(G)
    
    xcenters = (xedges[:-1] + xedges[1:]) / 2
    
    # 1D Plotting
    dir_name = os.path.basename(os.path.dirname(os.path.abspath(output_image)))
    lbl1 = get_custom_label(label1, defaults)
    color1d = defaults.get('color_1d', '#1f77b4')
    finite_mask = np.isfinite(G)
    if per1 and len(xcenters) >= 2:
        left_finite = np.roll(finite_mask, 1)
        right_finite = np.roll(finite_mask, -1)
        isolated_mask = finite_mask & (~left_finite) & (~right_finite)
        xc_plot = np.concatenate(([xcenters[-1] - 360.0], xcenters, [xcenters[0] + 360.0]))
        G_plot = np.concatenate(([G[-1]], G, [G[0]]))
    else:
        left_finite = np.concatenate(([False], finite_mask[:-1]))
        right_finite = np.concatenate((finite_mask[1:], [False]))
        isolated_mask = finite_mask & (~left_finite) & (~right_finite)
        xc_plot = xcenters
        G_plot = G

    plt.figure(figsize=(8, 6))
    plt.plot(xc_plot, G_plot, color=color1d, linewidth=2.5)

    if np.any(isolated_mask):
        plt.scatter(xcenters[isolated_mask], G[isolated_mask], color=color1d, s=36, zorder=5)

    if per1:
        plt.xlim(-180, 180)
    
    plt.xlabel(lbl1, fontsize=12, fontweight='bold', labelpad=10)
    plt.ylabel(f'ΔG ({energy_unit})', fontsize=12, fontweight='bold', labelpad=10)
    
    # Resolve custom plot title
    title_tmpl = defaults.get('plot_title', 'Free Energy Landscape ({dir_name})')
    try:
        resolved_title = title_tmpl.format(dir_name=dir_name)
    except Exception:
        resolved_title = title_tmpl
    plt.title(resolved_title, fontsize=14, fontweight='bold', pad=15)
    
    plt.tight_layout()
    out_dir = os.path.dirname(os.path.abspath(output_image))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    plt.savefig(output_image, dpi=300)
    plt.close()
    print(f"--> Plot saved successfully: {output_image}")

def plot_2d(file1, file2, label1, label2, output_image, T=310.0, config_file=None):
    print(f"--> Loading 2D data: {file1} and {file2}...")
    frames1, raw1, _ = load_data_with_frames(file1)
    frames2, raw2, _ = load_data_with_frames(file2)
    data1, data2 = align_datasets((frames1, raw1, label1), (frames2, raw2, label2))
        
    print("--> Calculating 2D histogram and Free Energy Landscape...")
    defaults = get_defaults(config_file)
    kB = defaults.get('kB', 0.001987)
    nbins = defaults.get('bins_2d', 50)
    energy_unit = get_energy_unit(defaults)
    _validate_fel_params(T, kB, nbins)

    per1 = _is_dihedral_label(label1, defaults)
    per2 = _is_dihedral_label(label2, defaults)
    data1, bins_1, _ = _compute_bins(data1, nbins, is_periodic_dihedral=per1)
    data2, bins_2, _ = _compute_bins(data2, nbins, is_periodic_dihedral=per2)
        
    hist, xedges, yedges = np.histogram2d(data1, data2, bins=[bins_1, bins_2], density=True)
    
    hist = np.where(hist == 0, np.nan, hist)
    
    with np.errstate(divide='ignore', invalid='ignore'):
        G = -(kB * T) * np.log(hist)
    G = G - np.nanmin(G)
    
    xcenters = (xedges[:-1] + xedges[1:]) / 2
    ycenters = (yedges[:-1] + yedges[1:]) / 2
    
    # 2D Plotting
    plt.figure(figsize=(9, 7.5))
    max_g = np.nanmax(G)
    if np.isnan(max_g) or max_g <= 0:
        max_g = 1.0
    cmap2d = resolve_colormap(defaults.get('colormap_2d', 'viridis'), 'viridis')

    if G.shape[0] < 2 or G.shape[1] < 2:
        print("--> [Warning] At least one 2D axis has only 1 populated bin; using pcolormesh instead of contourf.")
        pm = plt.pcolormesh(xedges, yedges, G.T, cmap=cmap2d, vmin=0, vmax=max_g, shading='flat')
        mappable = pm
    else:
        pm = plt.pcolormesh(xedges, yedges, G.T, cmap=cmap2d, vmin=0, vmax=max_g, shading='flat', zorder=1)
        xc_c = xcenters
        yc_c = ycenters
        G_c = G
        if per1:
            xc_c = np.concatenate(([xcenters[-1] - 360.0], xcenters, [xcenters[0] + 360.0]))
            G_c = np.concatenate((G_c[-1:, :], G_c, G_c[:1, :]), axis=0)
        if per2:
            yc_c = np.concatenate(([ycenters[-1] - 360.0], ycenters, [ycenters[0] + 360.0]))
            G_c = np.concatenate((G_c[:, -1:], G_c, G_c[:, :1]), axis=1)

        X_c, Y_c = np.meshgrid(xc_c, yc_c)
        levels = np.linspace(0, max_g, 50)
        cf = plt.contourf(X_c, Y_c, G_c.T, levels=levels, cmap=cmap2d, zorder=2)

        # Add energy contour lines (scaled by kB*T relative to kcal/mol at 310 K)
        kT_ref = 0.001987 * 310.0
        contour_scale = max(1.0, float(np.round((kB * T) / kT_ref)))
        max_contour = min(10.0 * contour_scale, max_g)
        contour_levels = np.arange(0.5 * contour_scale, max_contour, 1.0 * contour_scale)
        if len(contour_levels) > 0:
            contours = plt.contour(X_c, Y_c, G_c.T, levels=contour_levels, colors='black', linewidths=0.5, alpha=0.3, zorder=3)
            plt.clabel(contours, inline=True, fontsize=8, fmt=f'%.1f {energy_unit}')

        plt.xlim(xedges[0], xedges[-1])
        plt.ylim(yedges[0], yedges[-1])
        mappable = cf
        
    cbar = plt.colorbar(mappable, format='%.2f')
    cbar.set_label(f'ΔG ({energy_unit})', rotation=270, labelpad=20, fontsize=12, fontweight='bold')
    cbar.ax.tick_params(labelsize=10)
    
    dir_name = os.path.basename(os.path.dirname(os.path.abspath(output_image)))
    lbl1 = get_custom_label(label1, defaults)
    lbl2 = get_custom_label(label2, defaults)
    plt.xlabel(lbl1, fontsize=12, fontweight='bold', labelpad=10)
    plt.ylabel(lbl2, fontsize=12, fontweight='bold', labelpad=10)
    
    # Resolve custom plot title
    title_tmpl = defaults.get('plot_title', 'Free Energy Landscape ({dir_name})')
    try:
        resolved_title = title_tmpl.format(dir_name=dir_name)
    except Exception:
        resolved_title = title_tmpl
    plt.title(resolved_title, fontsize=14, fontweight='bold', pad=15)
    plt.grid(True, which='both', linestyle='--', linewidth=0.5, alpha=0.5)
    
    plt.tight_layout()
    out_dir = os.path.dirname(os.path.abspath(output_image))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    plt.savefig(output_image, dpi=300)
    plt.close()
    print(f"--> Plot saved successfully: {output_image}")

def plot_3d(file1, file2, file3, label1, label2, label3, output_path, T=310.0, threshold='auto', fmt='html', config_file=None):
    print(f"--> Loading 3D data: {file1}, {file2}, {file3}...")
    frames1, raw1, _ = load_data_with_frames(file1)
    frames2, raw2, _ = load_data_with_frames(file2)
    frames3, raw3, _ = load_data_with_frames(file3)
    x, y, z = align_datasets(
        (frames1, raw1, label1),
        (frames2, raw2, label2),
        (frames3, raw3, label3),
    )
        
    print("--> Calculating 3D histogram and Free Energy Landscape...")
    defaults = get_defaults(config_file)
    kB = defaults.get('kB', 0.001987)
    bins_xyz = defaults.get('bins_3d', 30)
    energy_unit = get_energy_unit(defaults)
    _validate_fel_params(T, kB, bins_xyz)

    max_unit_3d = int(bins_xyz)
    x, bins_x, _ = _compute_bins(x, bins_xyz, is_periodic_dihedral=_is_dihedral_label(label1, defaults), max_unit_span=max_unit_3d)
    y, bins_y, _ = _compute_bins(y, bins_xyz, is_periodic_dihedral=_is_dihedral_label(label2, defaults), max_unit_span=max_unit_3d)
    z, bins_z, _ = _compute_bins(z, bins_xyz, is_periodic_dihedral=_is_dihedral_label(label3, defaults), max_unit_span=max_unit_3d)
        
    hist, edges = np.histogramdd((x, y, z), bins=(bins_x, bins_y, bins_z), density=True)
    
    # Avoid ln(0) error by setting 0 values to NaN (matching 1D and 2D methods)
    hist = np.where(hist == 0, np.nan, hist)
    
    with np.errstate(divide='ignore', invalid='ignore'):
        G = -(kB * T) * np.log(hist)
    G = G - np.nanmin(G)
    
    # Calculate threshold if set to auto (scaled by kB*T relative to kcal/mol at 310 K)
    if str(threshold).lower().strip() == 'auto':
        kT_ref = 0.001987 * 310.0
        unit_scale = (kB * T) / kT_ref
        try:
            detected_thresh = min(6.0 * unit_scale, max(2.0 * unit_scale, float(np.nanpercentile(G, 35))))
            print(f"--> Auto-detected 3D energy threshold: {detected_thresh:.2f} {energy_unit}")
            threshold_val = detected_thresh
        except Exception:
            threshold_val = 3.0 * unit_scale
    else:
        try:
            threshold_val = float(threshold)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid 3D energy threshold '{threshold}'. Must be 'auto' or a positive number.")
        if not np.isfinite(threshold_val) or threshold_val <= 0:
            raise ValueError(f"Invalid 3D energy threshold '{threshold}'. Must be a positive number (> 0).")
            
    xcenters = (edges[0][:-1] + edges[0][1:]) / 2
    ycenters = (edges[1][:-1] + edges[1][1:]) / 2
    zcenters = (edges[2][:-1] + edges[2][1:]) / 2
    X, Y, Z = np.meshgrid(xcenters, ycenters, zcenters, indexing='ij')
    
    # Filtering lower energy states (e.g. G < threshold_val)
    mask = G < threshold_val
    X_plot = X[mask]
    Y_plot = Y[mask]
    Z_plot = Z[mask]
    G_plot = G[mask]

    if len(X_plot) == 0:
        print(f"--> [Warning] No 3D points found below energy threshold {threshold_val:.2f} {energy_unit}.")
    
    base_path, ext = os.path.splitext(output_path)
    
    # 1. HTML generation using Plotly
    if fmt in ['html', 'both']:
        try:
            import plotly.graph_objects as go
        except ImportError:
            raise ImportError("plotly library is required for 3D HTML plotting! Please install it using: pip install plotly")
            
        print("--> Generating interactive 3D HTML plot (Plotly)...")
        colorscale_3d = resolve_plotly_colorscale(defaults.get('colormap_3d', 'Jet'), 'Jet')
        fig = go.Figure(data=[go.Scatter3d(
            x=X_plot,
            y=Y_plot,
            z=Z_plot,
            mode='markers',
            marker=dict(
                size=5,
                color=G_plot,
                colorscale=colorscale_3d,
                opacity=0.8,
                colorbar=dict(title=f'ΔG ({energy_unit})')
            )
        )])
        
        dir_name = os.path.basename(os.path.dirname(os.path.abspath(output_path)))
        title_tmpl = defaults.get('plot_title', 'Free Energy Landscape ({dir_name})')
        try:
            resolved_title = title_tmpl.format(dir_name=dir_name)
        except Exception:
            resolved_title = title_tmpl
            
        fig.update_layout(
            title=dict(
                text=resolved_title,
                x=0.5,
                y=0.95,
                font=dict(size=16, color='black', family='Arial')
            ),
            scene=dict(
                xaxis_title=get_custom_label(label1, defaults),
                yaxis_title=get_custom_label(label2, defaults),
                zaxis_title=get_custom_label(label3, defaults)
            ),
            margin=dict(l=0, r=0, b=40, t=60)
        )
        
        html_out = base_path + ".html"
        out_dir = os.path.dirname(os.path.abspath(html_out))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        fig.write_html(html_out)
        print(f"--> Interactive 3D plot saved successfully: {html_out}")
        
    # 2. PNG generation using Matplotlib 3D scatter
    if fmt in ['png', 'both']:
        print("--> Generating static 3D PNG plot (Matplotlib)...")
        fig = plt.figure(figsize=(10, 8))
        ax = fig.add_subplot(111, projection='3d')
        
        cmap_name = resolve_colormap(defaults.get('colormap_3d', 'jet'), 'jet')
        sc = ax.scatter(X_plot, Y_plot, Z_plot, c=G_plot, cmap=cmap_name, alpha=0.7, marker='o')
        
        cbar = fig.colorbar(sc, ax=ax, shrink=0.5, pad=0.1)
        cbar.set_label(f'ΔG ({energy_unit})', fontsize=11, fontweight='bold')
        
        ax.set_xlabel(get_custom_label(label1, defaults), fontsize=11, fontweight='bold', labelpad=10)
        ax.set_ylabel(get_custom_label(label2, defaults), fontsize=11, fontweight='bold', labelpad=10)
        ax.set_zlabel(get_custom_label(label3, defaults), fontsize=11, fontweight='bold', labelpad=10)
        
        dir_name = os.path.basename(os.path.dirname(os.path.abspath(output_path)))
        title_tmpl = defaults.get('plot_title', 'Free Energy Landscape ({dir_name})')
        try:
            resolved_title = title_tmpl.format(dir_name=dir_name)
        except Exception:
            resolved_title = title_tmpl
            
        plt.title(resolved_title, fontsize=13, fontweight='bold', pad=15)
        
        png_out = base_path + ".png"
        out_dir = os.path.dirname(os.path.abspath(png_out))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        plt.savefig(png_out, dpi=300)
        plt.close()
        print(f"--> Static 3D plot saved successfully: {png_out}")


def _resolve_equilibration_log_path(output_image):
    base_no_ext = os.path.splitext(output_image)[0]
    if base_no_ext.endswith('_equilibration'):
        return base_no_ext + '.log'
    return base_no_ext + '_equilibration.log'


def _resolve_plot_title(defaults, output_path):
    dir_name = os.path.basename(os.path.dirname(os.path.abspath(output_path)))
    title_tmpl = defaults.get('plot_title', 'Free Energy Landscape ({dir_name})')
    try:
        return title_tmpl.format(dir_name=dir_name)
    except Exception:
        return title_tmpl


def _resolve_n_blocks(n_blocks, defaults):
    raw = defaults.get('fel_equilibration_blocks', 2) if n_blocks is None else n_blocks
    try:
        if isinstance(raw, bool):
            raise ValueError
        b = int(raw)
        if str(raw).strip() and float(raw) != b:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError(f"Number of equilibration blocks must be an integer >= 2 (got {raw!r}).")
    if b < 2:
        raise ValueError(f"Number of equilibration blocks must be an integer >= 2 (got {b}).")
    return b


def _compute_equilibration_metrics(
    block_hists, hist_full,
    block_counts, counts_full,
    kB_val, T, energy_unit,
    block_sizes, n_total,
    log_path=None,
    coord_info=None,
    print_report=True,
):
    n_blocks = len(block_hists)
    G_blocks = []
    with np.errstate(divide='ignore', invalid='ignore'):
        for hb in block_hists:
            gb = -(kB_val * T) * np.log(np.where(hb > 0, hb, np.nan))
            if np.any(np.isfinite(gb)):
                gb = gb - np.nanmin(gb)
            G_blocks.append(gb)
        G_full = -(kB_val * T) * np.log(np.where(hist_full > 0, hist_full, np.nan))
        if np.any(np.isfinite(G_full)):
            G_full = G_full - np.nanmin(G_full)

    G_stack = np.stack(G_blocks, axis=0)
    full_mask = np.isfinite(G_full)
    common_mask = np.all(np.isfinite(G_stack), axis=0)
    n_bins_full = int(np.sum(full_mask))
    n_bins_common = int(np.sum(common_mask))
    overlap_pct = (100.0 * n_bins_common / n_bins_full) if n_bins_full > 0 else 0.0
    total_count_full = float(np.sum(counts_full))
    mass_overlap_pct = (100.0 * float(np.sum(counts_full[common_mask])) / total_count_full) if total_count_full > 0 else 0.0

    spread_grid = np.full_like(G_full, np.nan, dtype=float)
    se_grid = np.full_like(G_full, np.nan, dtype=float)
    max_pair_diff = float('nan')

    if n_bins_common > 0:
        w = counts_full[common_mask].astype(float)
        w_sum = float(np.sum(w))
        g_full_common = G_full[common_mask]
        for b_idx in range(n_blocks):
            gb_common = G_blocks[b_idx][common_mask]
            if w_sum > 0:
                offset_b = float(np.sum(w * (gb_common - g_full_common)) / w_sum)
            else:
                offset_b = float(np.mean(gb_common - g_full_common))
            G_blocks[b_idx] = G_blocks[b_idx] - offset_b
        G_stack = np.stack(G_blocks, axis=0)

        vals_common = G_stack[:, common_mask]
        std_common = np.std(vals_common, axis=0, ddof=1)
        se_common = std_common / np.sqrt(float(n_blocks))
        spread_common = std_common
        if n_blocks == 2:
            max_pair_diff = float(np.max(np.abs(vals_common[1] - vals_common[0])))

        spread_grid[common_mask] = spread_common
        se_grid[common_mask] = se_common

        rmsd_dg = float(np.sqrt(np.mean(spread_common ** 2)))
        mae_dg = float(np.mean(spread_common))
        max_abs_diff = float(np.max(spread_common))
        if w_sum > 0:
            wrmsd_dg = float(np.sqrt(np.sum(w * (spread_common ** 2)) / w_sum))
            wse_dg = float(np.sqrt(np.sum(w * (se_common ** 2)) / w_sum))
        else:
            wrmsd_dg = float('nan')
            wse_dg = float('nan')
    else:
        rmsd_dg = float('nan')
        mae_dg = float('nan')
        max_abs_diff = float('nan')
        wrmsd_dg = float('nan')
        wse_dg = float('nan')

    sums = [float(np.sum(cb)) for cb in block_counts]
    if all(s > 0 for s in sums):
        p_blocks = [cb.astype(float) / s for cb, s in zip(block_counts, sums)]
        m = np.mean(np.stack(p_blocks, axis=0), axis=0)
        kls = []
        for pb in p_blocks:
            mask_b = pb > 0
            kls.append(float(np.sum(pb[mask_b] * np.log(pb[mask_b] / m[mask_b]))))
        jsd = max(0.0, float(np.mean(kls)))
    else:
        jsd = float('nan')

    jsd_max = float(np.log(float(n_blocks)))
    jsd_norm = (jsd / jsd_max) if (np.isfinite(jsd) and jsd_max > 0.0) else float('nan')

    kT = float(kB_val * T)
    if (
        n_bins_common == 0
        or mass_overlap_pct < 60.0
        or not np.isfinite(wse_dg)
        or wse_dg > 1.0 * kT
        or (np.isfinite(jsd_norm) and jsd_norm > 0.25)
    ):
        status = "POOR CONVERGENCE / DRIFT DETECTED (wSE > 1 kB*T, Mass Overlap < 60%, or JSD/ln(B) > 0.25)"
    elif (
        wse_dg <= 0.5 * kT
        and mass_overlap_pct >= 80.0
        and (not np.isfinite(jsd_norm) or jsd_norm <= 0.10)
    ):
        status = "WELL CONVERGED (wSE <= 0.5 kB*T, Mass Overlap >= 80%, JSD/ln(B) <= 0.10)"
    else:
        status = "MODERATE CONVERGENCE (0.5 < wSE/kB*T <= 1.0, 60% <= Mass Overlap < 80%, or 0.10 < JSD/ln(B) <= 0.25)"

    block_desc = "First Half vs Second Half" if n_blocks == 2 else f"{n_blocks} Equal Time Blocks"
    sizes_str = " / ".join(str(sz) for sz in block_sizes)
    if n_blocks == 2 and np.isfinite(max_abs_diff):
        max_spread_line = f"Max Block Std(dG)   : {max_abs_diff:.4f} {energy_unit} (Max |dG2 - dG1| = {max_pair_diff:.4f} {energy_unit})"
    elif np.isfinite(max_abs_diff):
        max_spread_line = f"Max Block Std(dG)   : {max_abs_diff:.4f} {energy_unit}"
    else:
        max_spread_line = "Max Block Std(dG)   : N/A"

    report_lines = [
        f"--- FEL Equilibration & Convergence Report ({block_desc}) ---",
        f"Coordinates         : {coord_info or 'N/A'}",
        f"Number of Blocks (B): {n_blocks}",
        f"Temperature / kB*T  : {T:.2f} K  (1 kB*T = {kT:.4f} {energy_unit})",
        f"Frames (Total / Blk): {n_total} / [{sizes_str}]",
        f"Sampled Bins (Common/Full): {n_bins_common} / {n_bins_full} ({overlap_pct:.1f}% bin overlap; {mass_overlap_pct:.1f}% mass overlap)",
        f"Boltzmann wSE(dG)   : {wse_dg:.4f} {energy_unit}" if np.isfinite(wse_dg) else "Boltzmann wSE(dG)   : N/A",
        f"Boltzmann wRMSD(std): {wrmsd_dg:.4f} {energy_unit}" if np.isfinite(wrmsd_dg) else "Boltzmann wRMSD(std): N/A",
        f"Unweighted RMSD(std): {rmsd_dg:.4f} {energy_unit}" if np.isfinite(rmsd_dg) else "Unweighted RMSD(std): N/A",
        f"Unweighted Mean(std): {mae_dg:.4f} {energy_unit}" if np.isfinite(mae_dg) else "Unweighted Mean(std): N/A",
        max_spread_line,
        f"Jensen-Shannon Div  : {jsd:.5f} nats (JSD/ln({n_blocks}) = {jsd_norm:.4f}, max = {jsd_max:.5f})" if np.isfinite(jsd) else "Jensen-Shannon Div  : N/A",
        f"Assessment          : {status}",
        "Note                : Block SE assumes weakly correlated blocks (block duration >> conformational autocorrelation time).",
    ]
    report_text = "\n".join(report_lines)
    if print_report:
        print(report_text)

    if log_path:
        out_dir = os.path.dirname(os.path.abspath(log_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(log_path, 'w') as lf:
            lf.write(report_text + "\n")
        print(f"--> Equilibration report saved: {log_path}")

    return {
        'G_blocks': G_blocks,
        'G1': G_blocks[0],
        'G2': G_blocks[-1],
        'G_full': G_full,
        'spread_grid': spread_grid,
        'se_grid': se_grid,
        'n_blocks': n_blocks,
        'common_mask': common_mask,
        'n_bins_full': n_bins_full,
        'n_bins_common': n_bins_common,
        'overlap_pct': overlap_pct,
        'mass_overlap_pct': mass_overlap_pct,
        'rmsd_dg': rmsd_dg,
        'mae_dg': mae_dg,
        'wrmsd_dg': wrmsd_dg,
        'wse_dg': wse_dg,
        'max_abs_diff': max_abs_diff,
        'jsd': jsd,
        'jsd_norm': jsd_norm,
        'jsd_max': jsd_max,
        'kT': kT,
        'status': status,
    }


def plot_equilibration_1d(file1, label1, output_image, T=310.0, config_file=None, write_log=True, n_blocks=None):
    print(f"--> Loading 1D data for equilibration check: {file1}...")
    frames, x_raw, has_unique = load_data_with_frames(file1)
    if len(x_raw) == 0:
        raise ValueError("No readable numeric data found in 1D data file.")
    if has_unique:
        order = np.argsort(np.array(frames, dtype=int))
        x_raw = x_raw[order]

    defaults = get_defaults(config_file)
    B = _resolve_n_blocks(n_blocks, defaults)
    if len(x_raw) < 2 * B:
        raise ValueError(f"At least {2 * B} frames are required for {B}-block FEL equilibration analysis (got {len(x_raw)}).")

    kB_val = defaults.get('kB', 0.001987)
    nbins = defaults.get('bins_1d', 50)
    energy_unit = get_energy_unit(defaults)
    _validate_fel_params(T, kB_val, nbins)

    per1 = _is_dihedral_label(label1, defaults)
    x, bins_x, _ = _compute_bins(x_raw, nbins, is_periodic_dihedral=per1)
    hist_full, xedges = np.histogram(x, bins=bins_x, density=True)
    counts_full, _ = np.histogram(x, bins=xedges, density=False)

    x_blocks = np.array_split(x, B)
    block_hists = []
    block_counts = []
    for xb in x_blocks:
        hb, _ = np.histogram(xb, bins=xedges, density=True)
        cb, _ = np.histogram(xb, bins=xedges, density=False)
        block_hists.append(hb)
        block_counts.append(cb)

    log_path = _resolve_equilibration_log_path(output_image) if write_log else None
    lbl1 = get_custom_label(label1, defaults)
    metrics = _compute_equilibration_metrics(
        block_hists, hist_full,
        block_counts, counts_full,
        kB_val, T, energy_unit,
        [len(xb) for xb in x_blocks], len(x),
        log_path=log_path,
        coord_info=f"1D ({lbl1})",
    )

    G_blocks = metrics['G_blocks']
    G_full = metrics['G_full']
    spread_grid = metrics['spread_grid']
    se_grid = metrics['se_grid']
    xcenters = (xedges[:-1] + xedges[1:]) / 2

    def _wrap_1d(arr):
        if per1 and len(xcenters) >= 2:
            return np.concatenate(([arr[-1]], arr, [arr[0]]))
        return arr

    if per1 and len(xcenters) >= 2:
        xc_plot = np.concatenate(([xcenters[-1] - 360.0], xcenters, [xcenters[0] + 360.0]))
    else:
        xc_plot = xcenters

    G_full_plot = _wrap_1d(G_full)
    se_plot = _wrap_1d(se_grid)
    spread_plot = _wrap_1d(spread_grid)

    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(9.5, 7.8), sharex=True, gridspec_kw={'height_ratios': [2.2, 1.0]}
    )
    color1d = defaults.get('color_1d', '#1f77b4')
    ax_top.plot(xc_plot, G_full_plot, color=color1d, linewidth=2.4, label='Full (1–100%)', zorder=4)
    ax_top.fill_between(
        xc_plot,
        G_full_plot - se_plot,
        G_full_plot + se_plot,
        color=color1d, alpha=0.20,
        label='Block SE (±|ΔG₂ - ΔG₁|/2)' if B == 2 else f'Block SE (±σ/{B}^0.5)'
    )

    block_colors = ['#d62728', '#2ca02c', '#ff7f0e', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
    line_styles = ['--', ':', '-.', (0, (5, 2, 1, 2)), (0, (3, 1, 1, 1))]
    for idx, gb in enumerate(G_blocks):
        if B == 2:
            b_lbl = 'First Half (1–50%)' if idx == 0 else 'Second Half (50–100%)'
        else:
            p0 = 100.0 * idx / B
            p1 = 100.0 * (idx + 1) / B
            b_lbl = f'Block {idx + 1}/{B} ({p0:.0f}–{p1:.0f}%)'
        b_col = block_colors[idx % len(block_colors)]
        b_ls = line_styles[idx % len(line_styles)]
        ax_top.plot(xc_plot, _wrap_1d(gb), color=b_col, linestyle=b_ls, linewidth=1.6, label=b_lbl)

    ax_top.set_ylabel(f'ΔG ({energy_unit})', fontsize=11, fontweight='bold')
    ax_top.legend(loc='best', fontsize=8.5, ncol=2 if B > 4 else 1)
    ax_top.grid(True, linestyle='--', linewidth=0.5, alpha=0.5)

    wse_str = f"{metrics['wse_dg']:.3f}" if np.isfinite(metrics['wse_dg']) else "N/A"
    jsd_norm_str = f"{metrics['jsd_norm']:.3f}" if np.isfinite(metrics['jsd_norm']) else "N/A"
    base_title = _resolve_plot_title(defaults, output_image)
    ax_top.set_title(
        f"{base_title} — Equilibration Check ({B} Blocks)\n"
        f"wSE: {wse_str} {energy_unit} | Mass Overlap: {metrics['mass_overlap_pct']:.1f}% "
        f"(Bin: {metrics['overlap_pct']:.1f}%) | JSD/ln({B}): {jsd_norm_str}",
        fontsize=11.5, fontweight='bold', pad=12
    )

    spread_name = 'Block Std Dev σ(ΔG) (|ΔG₂ - ΔG₁|/√2)' if B == 2 else f'Block Std Dev σ(ΔG) ({B} blocks)'
    ax_bot.plot(xc_plot, spread_plot, color='#9467bd', linewidth=1.8, label=spread_name)
    ax_bot.axhline(metrics['kT'], color='black', linestyle='--', linewidth=1.0, alpha=0.7,
                   label=f"1 kBT ({metrics['kT']:.3f} {energy_unit})")
    ax_bot.set_xlabel(lbl1, fontsize=11, fontweight='bold')
    ax_bot.set_ylabel(f'Spread ({energy_unit})', fontsize=11, fontweight='bold')
    ax_bot.legend(loc='best', fontsize=9)
    ax_bot.grid(True, linestyle='--', linewidth=0.5, alpha=0.5)

    if per1:
        ax_bot.set_xlim(-180, 180)

    plt.tight_layout()
    out_dir = os.path.dirname(os.path.abspath(output_image))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    plt.savefig(output_image, dpi=300)
    plt.close()
    print(f"--> 1D equilibration plot saved successfully: {output_image}")
    return metrics


def plot_equilibration_2d(
    file1, file2, label1, label2, output_image,
    T=310.0, config_file=None, write_log=True, n_blocks=None,
    override_metrics=None, aligned_data=None,
):
    if aligned_data is not None:
        data1 = np.asarray(aligned_data[0], dtype=float)
        data2 = np.asarray(aligned_data[1], dtype=float)
    else:
        print(f"--> Loading 2D data for equilibration check: {file1} and {file2}...")
        frames1, raw1, _ = load_data_with_frames(file1)
        frames2, raw2, _ = load_data_with_frames(file2)
        data1, data2 = align_datasets((frames1, raw1, label1), (frames2, raw2, label2))

    defaults = get_defaults(config_file)
    B = _resolve_n_blocks(n_blocks, defaults)
    if len(data1) < 2 * B:
        raise ValueError(f"At least {2 * B} aligned frames are required for {B}-block FEL equilibration analysis (got {len(data1)}).")

    kB_val = defaults.get('kB', 0.001987)
    nbins = defaults.get('bins_2d', 50)
    energy_unit = get_energy_unit(defaults)
    _validate_fel_params(T, kB_val, nbins)

    per1 = _is_dihedral_label(label1, defaults)
    per2 = _is_dihedral_label(label2, defaults)
    data1, bins_1, _ = _compute_bins(data1, nbins, is_periodic_dihedral=per1)
    data2, bins_2, _ = _compute_bins(data2, nbins, is_periodic_dihedral=per2)

    hist_full, xedges, yedges = np.histogram2d(data1, data2, bins=[bins_1, bins_2], density=True)
    counts_full, _, _ = np.histogram2d(data1, data2, bins=[xedges, yedges], density=False)

    idx_blocks = np.array_split(np.arange(len(data1)), B)
    block_hists = []
    block_counts = []
    for ib in idx_blocks:
        hb, _, _ = np.histogram2d(data1[ib], data2[ib], bins=[xedges, yedges], density=True)
        cb, _, _ = np.histogram2d(data1[ib], data2[ib], bins=[xedges, yedges], density=False)
        block_hists.append(hb)
        block_counts.append(cb)

    lbl1 = get_custom_label(label1, defaults)
    lbl2 = get_custom_label(label2, defaults)
    log_path = _resolve_equilibration_log_path(output_image) if (write_log and override_metrics is None) else None
    metrics = _compute_equilibration_metrics(
        block_hists, hist_full,
        block_counts, counts_full,
        kB_val, T, energy_unit,
        [len(ib) for ib in idx_blocks], len(data1),
        log_path=log_path,
        coord_info=f"2D ({lbl1} vs {lbl2})",
        print_report=(override_metrics is None),
    )

    G_blocks = metrics['G_blocks']
    G_full = metrics['G_full']
    spread_grid = metrics['spread_grid']
    both_first_last = np.isfinite(G_blocks[0]) & np.isfinite(G_blocks[-1])
    G_drift = np.where(both_first_last, G_blocks[-1] - G_blocks[0], np.nan)

    all_energy_grids = [G_full] + list(G_blocks)
    finite_maxs = [float(np.nanmax(g)) for g in all_energy_grids if np.any(np.isfinite(g))]
    finite_mins = [float(np.nanmin(g)) for g in all_energy_grids if np.any(np.isfinite(g))]
    max_g = max(finite_maxs) if finite_maxs else 1.0
    if not np.isfinite(max_g) or max_g <= 0:
        max_g = 1.0
    min_g = min(0.0, min(finite_mins)) if finite_mins else 0.0
    if not np.isfinite(min_g) or min_g >= max_g:
        min_g = 0.0
    max_diff = float(np.nanmax(np.abs(G_drift))) if np.any(np.isfinite(G_drift)) else 1.0
    if not np.isfinite(max_diff) or max_diff <= 0:
        max_diff = 1.0
    max_spread = float(np.nanmax(spread_grid)) if np.any(np.isfinite(spread_grid)) else 1.0
    if not np.isfinite(max_spread) or max_spread <= 0:
        max_spread = 1.0

    cmap2d = resolve_colormap(defaults.get('colormap_2d', 'viridis'), 'viridis')
    panel_specs = []
    for idx, (gb, ib) in enumerate(zip(G_blocks, idx_blocks)):
        if B == 2:
            ptitle = f"First Half (1–50%, n={len(ib)})" if idx == 0 else f"Second Half (50–100%, n={len(ib)})"
        else:
            p0 = 100.0 * idx / B
            p1 = 100.0 * (idx + 1) / B
            ptitle = f"Block {idx + 1}/{B} ({p0:.0f}–{p1:.0f}%, n={len(ib)})"
        panel_specs.append((gb, ptitle, cmap2d, min_g, max_g, f"ΔG ({energy_unit})"))

    panel_specs.append((G_full, f"Full Trajectory (1–100%, n={len(data1)})", cmap2d, min_g, max_g, f"ΔG ({energy_unit})"))
    drift_title = "Difference (ΔG₂ - ΔG₁)" if B == 2 else f"Net Drift (Block {B} - Block 1)"
    panel_specs.append((G_drift, drift_title, 'coolwarm', -max_diff, max_diff, f"ΔΔG ({energy_unit})"))
    if B > 2:
        panel_specs.append((spread_grid, f"Block Std Dev σ(ΔG)", 'magma', 0.0, max_spread, f"σ(ΔG) ({energy_unit})"))

    total_panels = len(panel_specs)
    if B == 2:
        nrows, ncols = 2, 2
        figsize = (13, 10.5)
    else:
        ncols = 3 if total_panels <= 9 else 4
        nrows = int(np.ceil(total_panels / float(ncols)))
        figsize = (5.0 * ncols, 4.4 * nrows + 1.0)

    fig, axes = plt.subplots(nrows, ncols, figsize=figsize, sharex=True, sharey=True)
    axes_arr = np.atleast_2d(axes)
    axes_flat = axes_arr.flatten()

    for idx, (grid, ptitle, cmap_use, vmin, vmax, clabel) in enumerate(panel_specs):
        ax = axes_flat[idx]
        pm = ax.pcolormesh(xedges, yedges, grid.T, cmap=cmap_use, vmin=vmin, vmax=vmax, shading='flat')
        ax.set_title(ptitle, fontsize=11, fontweight='bold')
        ax.grid(True, linestyle='--', linewidth=0.4, alpha=0.4)
        cbar = fig.colorbar(pm, ax=ax, format='%.2f')
        cbar.set_label(clabel, fontsize=9, fontweight='bold')

    for idx in range(total_panels, len(axes_flat)):
        axes_flat[idx].set_visible(False)

    # Label leftmost visible panels and bottom-most visible panel in each column
    for r in range(nrows):
        if r * ncols < total_panels:
            axes_arr[r, 0].set_ylabel(lbl2, fontsize=11, fontweight='bold')
    for c in range(ncols):
        for r in range(nrows - 1, -1, -1):
            p_idx = r * ncols + c
            if p_idx < total_panels:
                axes_arr[r, c].set_xlabel(lbl1, fontsize=11, fontweight='bold')
                axes_arr[r, c].tick_params(labelbottom=True)
                break

    title_metrics = override_metrics if override_metrics is not None else metrics
    wse_str = f"{title_metrics['wse_dg']:.3f}" if np.isfinite(title_metrics['wse_dg']) else "N/A"
    wrmsd_str = f"{title_metrics['wrmsd_dg']:.3f}" if np.isfinite(title_metrics['wrmsd_dg']) else "N/A"
    jsd_norm_str = f"{title_metrics['jsd_norm']:.3f}" if np.isfinite(title_metrics['jsd_norm']) else "N/A"
    b_title = title_metrics['n_blocks']
    base_title = _resolve_plot_title(defaults, output_image)
    if override_metrics is not None:
        fig.suptitle(
            f"{base_title} — 3D FEL Equilibration Check ({B} Blocks, 2D Projection: {lbl1} vs {lbl2})\n"
            f"3D Metrics — wSE: {wse_str} {energy_unit} (wRMSD: {wrmsd_str}) | "
            f"Mass Overlap: {title_metrics['mass_overlap_pct']:.1f}% (Bin: {title_metrics['overlap_pct']:.1f}%) | "
            f"JSD/ln({b_title}): {jsd_norm_str}",
            fontsize=11.5, fontweight='bold', y=0.98
        )
    else:
        fig.suptitle(
            f"{base_title} — FEL Equilibration Check ({B} Blocks)\n"
            f"wSE: {wse_str} {energy_unit} (wRMSD: {wrmsd_str}) | "
            f"Mass Overlap: {title_metrics['mass_overlap_pct']:.1f}% (Bin: {title_metrics['overlap_pct']:.1f}%) | "
            f"JSD/ln({b_title}): {jsd_norm_str}",
            fontsize=12, fontweight='bold', y=0.98
        )

    plt.tight_layout(rect=[0, 0, 1, 0.94])
    out_dir = os.path.dirname(os.path.abspath(output_image))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    plt.savefig(output_image, dpi=300)
    plt.close()
    print(f"--> 2D equilibration plot saved successfully: {output_image}")
    return title_metrics


def plot_equilibration_3d(file1, file2, file3, label1, label2, label3, output_path, T=310.0, config_file=None, n_blocks=None):
    print(f"--> Loading 3D data for equilibration check: {file1}, {file2}, {file3}...")
    frames1, raw1, _ = load_data_with_frames(file1)
    frames2, raw2, _ = load_data_with_frames(file2)
    frames3, raw3, _ = load_data_with_frames(file3)
    x, y, z = align_datasets(
        (frames1, raw1, label1),
        (frames2, raw2, label2),
        (frames3, raw3, label3),
    )
    x_aligned, y_aligned = x.copy(), y.copy()

    defaults = get_defaults(config_file)
    B = _resolve_n_blocks(n_blocks, defaults)
    if len(x) < 2 * B:
        raise ValueError(f"At least {2 * B} aligned frames are required for {B}-block 3D FEL equilibration analysis (got {len(x)}).")

    kB_val = defaults.get('kB', 0.001987)
    bins_xyz = defaults.get('bins_3d', 30)
    energy_unit = get_energy_unit(defaults)
    _validate_fel_params(T, kB_val, bins_xyz)

    max_unit_3d = int(bins_xyz)
    x, bins_x, _ = _compute_bins(x, bins_xyz, is_periodic_dihedral=_is_dihedral_label(label1, defaults), max_unit_span=max_unit_3d)
    y, bins_y, _ = _compute_bins(y, bins_xyz, is_periodic_dihedral=_is_dihedral_label(label2, defaults), max_unit_span=max_unit_3d)
    z, bins_z, _ = _compute_bins(z, bins_xyz, is_periodic_dihedral=_is_dihedral_label(label3, defaults), max_unit_span=max_unit_3d)

    hist_full, edges = np.histogramdd((x, y, z), bins=(bins_x, bins_y, bins_z), density=True)
    counts_full, _ = np.histogramdd((x, y, z), bins=edges, density=False)

    idx_blocks = np.array_split(np.arange(len(x)), B)
    block_hists = []
    block_counts = []
    for ib in idx_blocks:
        hb, _ = np.histogramdd((x[ib], y[ib], z[ib]), bins=edges, density=True)
        cb, _ = np.histogramdd((x[ib], y[ib], z[ib]), bins=edges, density=False)
        block_hists.append(hb)
        block_counts.append(cb)

    lbl1 = get_custom_label(label1, defaults)
    lbl2 = get_custom_label(label2, defaults)
    lbl3 = get_custom_label(label3, defaults)
    png_out = os.path.splitext(output_path)[0] + ".png"
    log_path = _resolve_equilibration_log_path(png_out)
    metrics_3d = _compute_equilibration_metrics(
        block_hists, hist_full,
        block_counts, counts_full,
        kB_val, T, energy_unit,
        [len(ib) for ib in idx_blocks], len(x),
        log_path=log_path,
        coord_info=f"3D ({lbl1}, {lbl2}, {lbl3})",
    )

    print(f"--> Generating 2D projection equilibration figure for ({lbl1}, {lbl2})...")
    plot_equilibration_2d(
        file1, file2, label1, label2, png_out,
        T=T, config_file=config_file, write_log=False, n_blocks=B,
        override_metrics=metrics_3d, aligned_data=(x_aligned, y_aligned),
    )
    return metrics_3d

def main():
    parser = argparse.ArgumentParser(
        description="Free Energy Landscape Plotter",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""Usage examples:
  1D: python plot_fel.py <file1> <label1> <out>
  2D: python plot_fel.py <file1> <file2> <label1> <label2> <out>
  3D: python plot_fel.py <file1> <file2> <file3> <label1> <label2> <label3> <out> [--format html|png|both]"""
    )
    parser.add_argument("pos_args", nargs="*", help="Positional arguments for files, labels, and output path.")
    parser.add_argument("--config", default=None, help="Path to parameters.in configuration file")
    parser.add_argument("--temp", type=float, default=None, help="Temperature in Kelvin (default from config or 310.0)")
    parser.add_argument("--threshold", default=None, help="Energy threshold for 3D plot (default from config or auto)")
    parser.add_argument("--format", default=None, choices=["html", "png", "both"], help="Output format for 3D plot (default from config or html)")
    parser.add_argument("--equilibration", action="store_true", help="Run block-based FEL equilibration and convergence analysis")
    parser.add_argument("--blocks", "--eq-blocks", dest="blocks", type=int, default=None, help="Number of equal chronological time blocks for equilibration analysis (default from config or 2)")
    
    args = parser.parse_args()
    
    # Initialize parameters lazily from config_file
    defaults = get_defaults(args.config)
    
    # Resolve temperature, threshold, format: CLI arg > Config file > Default
    final_temp = args.temp if args.temp is not None else defaults.get('temperature', 310.0)
    final_threshold = args.threshold if args.threshold is not None else defaults.get('energy_threshold_3d', 'auto')
    final_format = args.format if args.format is not None else str(defaults.get('plot_format_3d', 'html')).lower().strip()
    if final_format not in ['html', 'png', 'both']:
        print(f"Warning: Invalid plot_format_3d '{final_format}' in config. Using default: html")
        final_format = 'html'
    
    pos = args.pos_args
    try:
        if args.equilibration:
            if len(pos) == 3:
                plot_equilibration_1d(pos[0], pos[1], pos[2], T=final_temp, config_file=args.config, n_blocks=args.blocks)
            elif len(pos) == 5:
                plot_equilibration_2d(pos[0], pos[1], pos[2], pos[3], pos[4], T=final_temp, config_file=args.config, n_blocks=args.blocks)
            elif len(pos) == 7:
                plot_equilibration_3d(pos[0], pos[1], pos[2], pos[3], pos[4], pos[5], pos[6], T=final_temp, config_file=args.config, n_blocks=args.blocks)
            else:
                parser.print_help()
                print("\nError: Invalid number of positional arguments.")
                sys.exit(1)
        elif len(pos) == 3:
            plot_1d(pos[0], pos[1], pos[2], T=final_temp, config_file=args.config)
        elif len(pos) == 5:
            plot_2d(pos[0], pos[1], pos[2], pos[3], pos[4], T=final_temp, config_file=args.config)
        elif len(pos) == 7:
            plot_3d(pos[0], pos[1], pos[2], pos[3], pos[4], pos[5], pos[6], T=final_temp, threshold=final_threshold, fmt=final_format, config_file=args.config)
        else:
            parser.print_help()
            print("\nError: Invalid number of positional arguments.")
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
