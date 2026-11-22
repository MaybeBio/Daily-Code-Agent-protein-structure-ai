#!/bin/bash
export LC_ALL=C

# Komut satırı argümanları veya varsayılan değerler
INPUT_FILE=${1:-"total_data.dat"}
PRMTOP=${2:-"../../h2h3mono.top"}
TRAJIN=${3:-"traj.in"}
BINS=${4:-100}
TOP_N=${5:-10}          # Kaç tane FARKLI lokal minimum istediğiniz
FRAMES_PER_WELL=${6:-1} # Her bir kuyudan kaçar adet frame çekileceği
DISTANCE_RATIO=${7:-0.10}  # FEL uzayının diyagonal genişliğinin yüzde kaçı kadar mesafe aransın (0.10 = %10)
VAR1_LBL=${VAR1_LABEL:-"Var1"}
VAR2_LBL=${VAR2_LABEL:-"Var2"}

LOG_FILE="export_info.log"
echo "--- Finding Distinct Local Minima ---" | tee "$LOG_FILE"

for req_file in "$INPUT_FILE" "$PRMTOP" "$TRAJIN"; do
    if [ ! -f "$req_file" ]; then
        echo "Error: Required input file '$req_file' was not found!" | tee -a "$LOG_FILE"
        exit 1
    fi
done

MIN_BIN_COUNT=${EXPORT_MIN_BIN_COUNT:-5}
AUTOIMAGE=${AUTOIMAGE:-"true"}
STRIP_SOLVENT=${EXPORT_STRIP_SOLVENT:-"false"}
STRIP_DIVALENT=${SASA_STRIP_DIVALENT:-"false"}
KB_VAL=${kB:-"0.001987"}
TEMP=${TEMPERATURE:-"310.0"}
MAX_DG_RAW=${EXPORT_MAX_DG:-"auto"}

validate_int_ge() {
    local name="$1" val="$2" min_val="$3"
    if ! [[ "$val" =~ ^[0-9]+$ ]] || [ "$((10#$val))" -lt "$min_val" ]; then
        echo "Error: $name must be an integer >= $min_val (got '$val')." | tee -a "$LOG_FILE"
        exit 1
    fi
}

validate_float_cond() {
    local name="$1" val="$2" op="$3"
    if ! [[ "$val" =~ ^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$ ]]; then
        echo "Error: $name must be a finite number (got '$val')." | tee -a "$LOG_FILE"
        exit 1
    fi
    if ! awk -v x="$val" -v op="$op" 'BEGIN {
        v = x + 0.0
        if (op == ">0") exit !(v > 0.0)
        if (op == ">=0") exit !(v >= 0.0)
        exit 1
    }'; then
        echo "Error: $name must satisfy $op (got '$val')." | tee -a "$LOG_FILE"
        exit 1
    fi
}

validate_int_ge "BINS" "$BINS" 2
validate_int_ge "TOP_N" "$TOP_N" 1
validate_int_ge "FRAMES_PER_WELL" "$FRAMES_PER_WELL" 1
validate_int_ge "EXPORT_MIN_BIN_COUNT" "$MIN_BIN_COUNT" 1
validate_float_cond "DISTANCE_RATIO" "$DISTANCE_RATIO" ">=0"
validate_float_cond "kB" "$KB_VAL" ">0"
validate_float_cond "TEMPERATURE" "$TEMP" ">0"

MAX_DG_LOWER=$(printf '%s' "$MAX_DG_RAW" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
if [[ "$MAX_DG_LOWER" == "auto" ]]; then
    MAX_DG_VAL=$(awk -v kb="$KB_VAL" -v t="$TEMP" 'BEGIN { printf "%.10g", 5.0 * kb * t }')
    USE_MAX_DG=1
elif [[ "$MAX_DG_LOWER" == "none" || "$MAX_DG_LOWER" == "off" || "$MAX_DG_LOWER" == "false" || "$MAX_DG_LOWER" == "0" ]]; then
    MAX_DG_VAL=0
    USE_MAX_DG=0
else
    validate_float_cond "EXPORT_MAX_DG" "$MAX_DG_RAW" ">0"
    MAX_DG_VAL="$MAX_DG_RAW"
    USE_MAX_DG=1
fi

is_truthy() {
    local val
    val=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
    [[ "$val" == "true" || "$val" == "1" || "$val" == "yes" || "$val" == "on" ]]
}

is_dihedral_lbl() {
    local val
    val=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
    [[ "$val" =~ ^(ext_)?(dihedrals?|dihd?|phi|psi|omega|chi[0-9]*|torsions?)([_.-]|$) ]]
}

P1=0
if is_dihedral_lbl "$VAR1_LBL" || is_truthy "${VAR1_PERIODIC:-false}"; then
    P1=1
fi
P2=0
if is_dihedral_lbl "$VAR2_LBL" || is_truthy "${VAR2_PERIODIC:-false}"; then
    P2=1
fi

# Min/Max değerlerini, kesikli tam sayı durumunu ve otomatik (normalize) MIN_DISTANCE'ı bul
read n_rows min2 max2 min3 max3 min_dist disc2 disc3 < <(awk -v ratio="$DISTANCE_RATIO" -v p1="$P1" -v p2="$P2" '
BEGIN {
    n_rows = 0
    disc2 = 1
    disc3 = 1
}
{
    sub(/\r$/, "")
    if ($0 ~ /^[[:space:]]*#/ || $0 ~ /^[[:space:]]*@/ || NF < 3) next
    if ($2 !~ /^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$/ || $3 !~ /^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$/) next
    v2 = $2 + 0.0
    v3 = $3 + 0.0
    if (n_rows == 0) {
        m2 = M2 = v2
        m3 = M3 = v3
    } else {
        if (v2 < m2) m2 = v2
        if (v2 > M2) M2 = v2
        if (v3 < m3) m3 = v3
        if (v3 > M3) M3 = v3
    }
    r2_int = int(v2 + (v2 >= 0 ? 0.5 : -0.5))
    d2 = v2 - r2_int; if (d2 < 0) d2 = -d2
    if (d2 > 1e-9) disc2 = 0
    r3_int = int(v3 + (v3 >= 0 ? 0.5 : -0.5))
    d3 = v3 - r3_int; if (d3 < 0) d3 = -d3
    if (d3 > 1e-9) disc3 = 0
    n_rows++
}
END {
    if (n_rows == 0) {
        print 0, 0, 0, 0, 0, 0, 0, 0
        exit
    }
    if (p1 == 1) {
        disc2 = 0
        m2 = -180.0
        M2 = 180.0
    }
    if (p2 == 1) {
        disc3 = 0
        m3 = -180.0
        M3 = 180.0
    }
    # Min-Max Normalizasyonunda grafik 1x1 boyutlarında bir kareye dönüşür.
    # Bu karenin köşegeni her zaman sqrt(1^2 + 1^2) = 1.4142... olacaktır.
    md = sqrt(2.0) * ratio
    printf "%d %.17g %.17g %.17g %.17g %.17g %d %d\n", n_rows, m2, M2, m3, M3, md, disc2, disc3
}' "$INPUT_FILE")

if [ "${n_rows:-0}" -eq 0 ]; then
    echo "Error: No valid data rows found in '$INPUT_FILE'." | tee -a "$LOG_FILE"
    exit 1
fi

echo "FEL space dimensions analyzed." | tee -a "$LOG_FILE"
printf "Auto-assigned Normalized Distance (between wells): %.3f\n" "$min_dist" | tee -a "$LOG_FILE"


# Histogram oluştur, gerçek lokal maksimumları (8-komşuluk) bul ve mesafe filtresinden geçir
TOP_CENTERS=$(awk -v b="$BINS" -v m2="$min2" -v M2="$max2" -v m3="$min3" -v M3="$max3" \
    -v d2="$disc2" -v d3="$disc3" -v p1="$P1" -v p2="$P2" -v min_bin_count="$MIN_BIN_COUNT" \
    -v use_max_dg="$USE_MAX_DG" -v max_dg="$MAX_DG_VAL" -v kb="$KB_VAL" -v temp="$TEMP" '
BEGIN {
    if (d2 == 1) {
        im2 = int(m2 + (m2 >= 0 ? 0.5 : -0.5))
        iM2 = int(M2 + (M2 >= 0 ? 0.5 : -0.5))
        span2 = iM2 - im2 + 1
        if ((M2 - m2) < 100) {
            nx = span2
            x0_2 = m2 - 0.5
            w2 = 1.0
        } else {
            w2 = int(span2 / b)
            if (span2 > w2 * b) w2++
            if (w2 < 1) w2 = 1
            x0_2 = m2 - 0.5
            nx = int((iM2 - im2) / w2) + 1
        }
    } else {
        nx = (b > 0) ? int(b) : 100
        x0_2 = m2
        r2 = (M2 - m2 > 0) ? (M2 - m2) : 1.0
        w2 = (M2 - m2) / nx
    }

    if (d3 == 1) {
        im3 = int(m3 + (m3 >= 0 ? 0.5 : -0.5))
        iM3 = int(M3 + (M3 >= 0 ? 0.5 : -0.5))
        span3 = iM3 - im3 + 1
        if ((M3 - m3) < 100) {
            ny = span3
            x0_3 = m3 - 0.5
            w3 = 1.0
        } else {
            w3 = int(span3 / b)
            if (span3 > w3 * b) w3++
            if (w3 < 1) w3 = 1
            x0_3 = m3 - 0.5
            ny = int((iM3 - im3) / w3) + 1
        }
    } else {
        ny = (b > 0) ? int(b) : 100
        x0_3 = m3
        r3 = (M3 - m3 > 0) ? (M3 - m3) : 1.0
        w3 = (M3 - m3) / ny
    }
}
{
    sub(/\r$/, "")
    if ($0 ~ /^[[:space:]]*#/ || $0 ~ /^[[:space:]]*@/ || NF < 3) next
    if ($2 !~ /^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$/ || $3 !~ /^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$/) next
    v2 = $2 + 0.0
    v3 = $3 + 0.0

    if (d2 == 1) {
        iv2 = int(v2 + (v2 >= 0 ? 0.5 : -0.5))
        if ((M2 - m2) < 100) {
            ix = iv2 - im2
        } else {
            ix = int((iv2 - im2) / w2)
        }
    } else if (p1 == 1) {
        while (v2 < -180.0) v2 += 360.0
        while (v2 >= 180.0) v2 -= 360.0
        ix = int((v2 + 180.0) / 360.0 * nx)
    } else if (M2 == m2) {
        ix = 0
    } else {
        ix = int((v2 - m2) / r2 * nx)
    }
    if (ix < 0) ix = 0
    if (ix >= nx) ix = nx - 1

    if (d3 == 1) {
        iv3 = int(v3 + (v3 >= 0 ? 0.5 : -0.5))
        if ((M3 - m3) < 100) {
            iy = iv3 - im3
        } else {
            iy = int((iv3 - im3) / w3)
        }
    } else if (p2 == 1) {
        while (v3 < -180.0) v3 += 360.0
        while (v3 >= 180.0) v3 -= 360.0
        iy = int((v3 + 180.0) / 360.0 * ny)
    } else if (M3 == m3) {
        iy = 0
    } else {
        iy = int((v3 - m3) / r3 * ny)
    }
    if (iy < 0) iy = 0
    if (iy >= ny) iy = ny - 1

    count[ix "," iy]++
}
END {
    PI2 = 2.0 * atan2(0.0, -1.0)
    max_count = 0
    for (idx in count) {
        if (count[idx] > max_count) max_count = count[idx]
    }
    eff_min = (max_count >= min_bin_count) ? min_bin_count : 1

    for (idx in count) {
        if (idx in visited) continue
        c = count[idx]
        if (c < eff_min) continue

        # 8-connected BFS over equal-count plateau; reject if any boundary neighbor is strictly higher
        q_head = 1
        q_tail = 1
        q[1] = idx
        visited[idx] = 1
        comp_n = 0
        has_higher = 0

        while (q_head <= q_tail) {
            cur = q[q_head]
            delete q[q_head]
            q_head++
            split(cur, cs, ",")
            cix = cs[1] + 0
            ciy = cs[2] + 0
            comp_n++
            comp_ix[comp_n] = cix
            comp_iy[comp_n] = ciy

            for (dx = -1; dx <= 1; dx++) {
                nix = cix + dx
                if (p1 == 1) {
                    nix = (nix % nx + nx) % nx
                } else if (nix < 0 || nix >= nx) {
                    continue
                }
                for (dy = -1; dy <= 1; dy++) {
                    niy = ciy + dy
                    if (p2 == 1) {
                        niy = (niy % ny + ny) % ny
                    } else if (niy < 0 || niy >= ny) {
                        continue
                    }
                    if (nix == cix && niy == ciy) continue
                    nkey = nix "," niy
                    nc = (nkey in count) ? count[nkey] : 0
                    if (nc > c) {
                        has_higher = 1
                    } else if (nc == c && !(nkey in visited)) {
                        visited[nkey] = 1
                        q[++q_tail] = nkey
                    }
                }
            }
        }

        if (has_higher == 0) {
            if (comp_n == 1) {
                best_ix = comp_ix[1]
                best_iy = comp_iy[1]
            } else {
                if (p1 == 1) {
                    sx = 0.0; sy = 0.0
                    for (k = 1; k <= comp_n; k++) {
                        ang = PI2 * (comp_ix[k] + 0.5) / nx
                        sx += cos(ang); sy += sin(ang)
                    }
                    if (sx*sx + sy*sy > 1e-12) {
                        cx = (atan2(sy, sx) / PI2) * nx - 0.5
                        while (cx < 0.0) cx += nx
                        while (cx >= nx) cx -= nx
                    } else {
                        cx = comp_ix[1]
                    }
                } else {
                    sum_x = 0.0
                    for (k = 1; k <= comp_n; k++) sum_x += comp_ix[k]
                    cx = sum_x / comp_n
                }

                if (p2 == 1) {
                    sx = 0.0; sy = 0.0
                    for (k = 1; k <= comp_n; k++) {
                        ang = PI2 * (comp_iy[k] + 0.5) / ny
                        sx += cos(ang); sy += sin(ang)
                    }
                    if (sx*sx + sy*sy > 1e-12) {
                        cy = (atan2(sy, sx) / PI2) * ny - 0.5
                        while (cy < 0.0) cy += ny
                        while (cy >= ny) cy -= ny
                    } else {
                        cy = comp_iy[1]
                    }
                } else {
                    sum_y = 0.0
                    for (k = 1; k <= comp_n; k++) sum_y += comp_iy[k]
                    cy = sum_y / comp_n
                }

                best_ix = comp_ix[1]
                best_iy = comp_iy[1]
                best_d2 = 1e30
                for (k = 1; k <= comp_n; k++) {
                    kix = comp_ix[k]
                    kiy = comp_iy[k]
                    ddx = kix - cx
                    if (ddx < 0.0) ddx = -ddx
                    if (p1 == 1 && ddx > nx / 2.0) ddx = nx - ddx
                    ddy = kiy - cy
                    if (ddy < 0.0) ddy = -ddy
                    if (p2 == 1 && ddy > ny / 2.0) ddy = ny - ddy
                    d2_c = ddx * ddx + ddy * ddy
                    if (d2_c < best_d2 - 1e-12 || (d2_c <= best_d2 + 1e-12 && (kix < best_ix || (kix == best_ix && kiy < best_iy)))) {
                        best_d2 = d2_c
                        best_ix = kix
                        best_iy = kiy
                    }
                }
            }

            if (d2 == 1 && (M2 - m2) < 100) {
                tx = im2 + best_ix
            } else {
                tx = x0_2 + (best_ix + 0.5) * w2
            }
            if (d3 == 1 && (M3 - m3) < 100) {
                ty = im3 + best_iy
            } else {
                ty = x0_3 + (best_iy + 0.5) * w3
            }
            if (use_max_dg != 1 || c >= max_count || (-kb * temp * log(c / max_count)) <= max_dg + 1e-12) {
                printf "%d %.10f %.10f %d %d %d\n", c, tx, ty, max_count, best_ix, best_iy
            }
        }
    }
}' "$INPUT_FILE" | sort -k1,1rn -k5,5n -k6,6n | awk -v min_dist="$min_dist" -v top_n="$TOP_N" -v m2="$min2" -v M2="$max2" -v m3="$min3" -v M3="$max3" -v p1="$P1" -v p2="$P2" '
BEGIN {
    accepted = 0
    r2 = (p1 == 1) ? 180.0 : ((M2 - m2 > 0) ? (M2 - m2) : 1.0)
    r3 = (p2 == 1) ? 180.0 : ((M3 - m3 > 0) ? (M3 - m3) : 1.0)
}
{
    c = $1; tx = $2; ty = $3; mc = $4; bix = $5; biy = $6
    is_valid = 1
    # Daha önce kabul edilen merkezlere uzaklığı kontrol et
    for (i = 1; i <= accepted; i++) {
        # Öklid uzaklığını her iki ekseni kendi maksimum açıklığına bölerek normalize ediyoruz (periyodik dihedralde max 180 deg)
        if (p1 == 1) {
            dx = tx - acc_tx[i]
            if (dx < 0) dx = -dx
            if (dx > 180.0) dx = 360.0 - dx
            norm_dx = dx / 180.0
        } else {
            norm_dx = (tx - acc_tx[i]) / r2
        }
        if (p2 == 1) {
            dy = ty - acc_ty[i]
            if (dy < 0) dy = -dy
            if (dy > 180.0) dy = 360.0 - dy
            norm_dy = dy / 180.0
        } else {
            norm_dy = (ty - acc_ty[i]) / r3
        }
        dist = sqrt(norm_dx^2 + norm_dy^2)

        if (dist < min_dist) {
            is_valid = 0
            break
        }
    }
    
    if (is_valid == 1) {
        accepted++
        acc_tx[accepted] = tx
        acc_ty[accepted] = ty
        print c, tx, ty, mc, bix, biy
        if (accepted == top_n) exit
    }
}')

# Eğer yeterli sayıda farklı merkez bulunamadıysa uyar
if [ -z "$TOP_CENTERS" ]; then
    echo "Error: No centers could be found." | tee -a "$LOG_FILE"
    exit 1
fi
FOUND_CENTERS=$(echo "$TOP_CENTERS" | wc -l)

# Her bir hedef merkez için en yakın gerçek Frame'i bul (yalnızca hedef bin içinden)
echo "$FOUND_CENTERS distinct regional centers detected." | tee -a "$LOG_FILE"
echo "Calculating representative frames..." | tee -a "$LOG_FILE"

FRAME_LIST=""
idx=1
while read -r count tx ty max_count bix biy; do
    # Yalnızca (bix, biy) binine düşen kullanılmamış kareler arasından merkeze en yakın K kareyi bul
    center_frames=$(awk -v t2="$tx" -v t3="$ty" -v bix="$bix" -v biy="$biy" -v b="$BINS" \
        -v m2="$min2" -v M2="$max2" -v m3="$min3" -v M3="$max3" \
        -v d2="$disc2" -v d3="$disc3" -v p1="$P1" -v p2="$P2" -v used="$FRAME_LIST" '
    BEGIN {
        if (d2 == 1) {
            im2 = int(m2 + (m2 >= 0 ? 0.5 : -0.5))
            iM2 = int(M2 + (M2 >= 0 ? 0.5 : -0.5))
            span2 = iM2 - im2 + 1
            if ((M2 - m2) < 100) {
                nx = span2
                w2 = 1.0
            } else {
                w2 = int(span2 / b)
                if (span2 > w2 * b) w2++
                if (w2 < 1) w2 = 1
                nx = int((iM2 - im2) / w2) + 1
            }
        } else {
            nx = (b > 0) ? int(b) : 100
            r2_bin = (M2 - m2 > 0) ? (M2 - m2) : 1.0
        }

        if (d3 == 1) {
            im3 = int(m3 + (m3 >= 0 ? 0.5 : -0.5))
            iM3 = int(M3 + (M3 >= 0 ? 0.5 : -0.5))
            span3 = iM3 - im3 + 1
            if ((M3 - m3) < 100) {
                ny = span3
                w3 = 1.0
            } else {
                w3 = int(span3 / b)
                if (span3 > w3 * b) w3++
                if (w3 < 1) w3 = 1
                ny = int((iM3 - im3) / w3) + 1
            }
        } else {
            ny = (b > 0) ? int(b) : 100
            r3_bin = (M3 - m3 > 0) ? (M3 - m3) : 1.0
        }

        r2 = (p1 == 1) ? 360.0 : ((M2 - m2 > 0) ? (M2 - m2) : 1.0)
        r3 = (p2 == 1) ? 360.0 : ((M3 - m3 > 0) ? (M3 - m3) : 1.0)
        n_used = split(used, uarr, ",")
        for (i = 1; i <= n_used; i++) {
            if (uarr[i] != "") seen[uarr[i]] = 1
        }
    }
    {
        sub(/\r$/, "")
        if ($0 ~ /^[[:space:]]*#/ || $0 ~ /^[[:space:]]*@/ || NF < 3) next
        if ($1 in seen) next
        if ($2 !~ /^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$/ || $3 !~ /^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$/) next
        v2 = $2 + 0.0
        v3 = $3 + 0.0

        if (d2 == 1) {
            iv2 = int(v2 + (v2 >= 0 ? 0.5 : -0.5))
            if ((M2 - m2) < 100) {
                ix = iv2 - im2
            } else {
                ix = int((iv2 - im2) / w2)
            }
        } else if (p1 == 1) {
            while (v2 < -180.0) v2 += 360.0
            while (v2 >= 180.0) v2 -= 360.0
            ix = int((v2 + 180.0) / 360.0 * nx)
        } else if (M2 == m2) {
            ix = 0
        } else {
            ix = int((v2 - m2) / r2_bin * nx)
        }
        if (ix < 0) ix = 0
        if (ix >= nx) ix = nx - 1

        if (d3 == 1) {
            iv3 = int(v3 + (v3 >= 0 ? 0.5 : -0.5))
            if ((M3 - m3) < 100) {
                iy = iv3 - im3
            } else {
                iy = int((iv3 - im3) / w3)
            }
        } else if (p2 == 1) {
            while (v3 < -180.0) v3 += 360.0
            while (v3 >= 180.0) v3 -= 360.0
            iy = int((v3 + 180.0) / 360.0 * ny)
        } else if (M3 == m3) {
            iy = 0
        } else {
            iy = int((v3 - m3) / r3_bin * ny)
        }
        if (iy < 0) iy = 0
        if (iy >= ny) iy = ny - 1

        if (ix != bix || iy != biy) next

        if (p1 == 1) {
            dx = v2 - t2
            if (dx < 0) dx = -dx
            if (dx > 180.0) dx = 360.0 - dx
        } else {
            dx = v2 - t2
        }
        if (p2 == 1) {
            dy = v3 - t3
            if (dy < 0) dy = -dy
            if (dy > 180.0) dy = 360.0 - dy
        } else {
            dy = v3 - t3
        }
        dist = (dx / r2)^2 + (dy / r3)^2
        printf "%s %.17g\n", $1, dist
    }' "$INPUT_FILE" | sort -k2,2g -k1,1n | head -n "$FRAMES_PER_WELL" | awk '{print $1}' | paste -sd, -)

    selected_n=0
    if [ -n "$center_frames" ]; then
        selected_n=$(awk -F',' '{print NF}' <<< "$center_frames")
    fi
    if [ "$selected_n" -lt "$FRAMES_PER_WELL" ]; then
        echo "Note: Well #$idx bin ($bix, $biy) contains only $selected_n available unused frame(s) (requested $FRAMES_PER_WELL)." | tee -a "$LOG_FILE"
    fi
    
    # Genel listeye ekle
    if [ -n "$center_frames" ]; then
        if [ -z "$FRAME_LIST" ]; then
            FRAME_LIST="$center_frames"
        else
            FRAME_LIST="$FRAME_LIST,$center_frames"
        fi
    fi
    
    dg=$(awk -v c="$count" -v mc="$max_count" -v kb="$KB_VAL" -v t="$TEMP" 'BEGIN {
        if (c > 0 && mc > 0) {
            printf "%.3f", -kb * t * log(c / mc)
        } else {
            printf "0.000"
        }
    }')

    ENERGY_UNIT_LBL="${ENERGY_UNIT:-}"
    if [ -z "$ENERGY_UNIT_LBL" ]; then
        ENERGY_UNIT_LBL=$(awk -v kb="$KB_VAL" 'BEGIN { d = kb - 0.008314; if (d < 0) d = -d; print (d < 0.001 ? "kJ/mol" : "kcal/mol") }')
    fi

    # Ekrana bas ve log dosyasına yaz
    msg=$(printf "%d. Distinct Well Center -> %s: %.3f, %s: %.3f | Count: %d | dG: %s %s | Extracted Frame(s): %s" "$idx" "$VAR1_LBL" "$tx" "$VAR2_LBL" "$ty" "$count" "$dg" "$ENERGY_UNIT_LBL" "${center_frames:-none}")
    echo "$msg" | tee -a "$LOG_FILE"
    ((idx++))
done <<< "$TOP_CENTERS"

if [ -z "$FRAME_LIST" ]; then
    echo "Error: No representative frames could be selected." | tee -a "$LOG_FILE"
    exit 1
fi


TRAJ_TYPE=$(printf '%s' "${TRAJ_TYPE:-md}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
BASE_DIR=${ORIG_CWD:-$(dirname "$TRAJIN")}

if [ "$TRAJ_TYPE" != "md" ] && [ "$TRAJ_TYPE" != "remd" ] && [ "$TRAJ_TYPE" != "mix" ]; then
    echo "ERROR: Invalid TRAJ_TYPE '$TRAJ_TYPE'! Must be 'md', 'remd', or 'mix'." | tee -a "$LOG_FILE"
    exit 1
fi

TRAJIN_LINES=$(awk -v mode="$TRAJ_TYPE" -v t="$TEMP" -v d="$BASE_DIR" '
BEGIN { err = 0 }
{
    sub(/\r$/, "")
    line = $0
    sub(/^[[:space:]]+/, "", line)
    if (line == "" || substr(line, 1, 1) == "#") next
    if (tolower(substr(line, 1, 7)) ~ /^trajin[[:space:]]/) {
        sub(/^[Tt][Rr][Aa][Jj][Ii][Nn][[:space:]]+/, "", line)
        sub(/^[[:space:]]+/, "", line)
        if (line == "" || substr(line, 1, 1) == "#") next
    }
    q = substr(line, 1, 1)
    if (q == "\"" || q == "\047") {
        idx = index(substr(line, 2), q)
        if (idx == 0) {
            printf("ERROR: Unclosed quote in trajectory list at line %d: %s\n", NR, $0) > "/dev/stderr"
            err = 2
            exit 2
        }
        f = substr(line, 2, idx - 1)
        rest_str = substr(line, idx + 2)
        sub(/#.*/, "", rest_str)
    } else {
        sub(/#.*/, "", line)
        sub(/[[:space:]]+$/, "", line)
        if (line == "") next
        if (match(line, /[[:space:]]+/)) {
            f = substr(line, 1, RSTART - 1)
            rest_str = substr(line, RSTART + RLENGTH)
        } else {
            f = line
            rest_str = ""
        }
    }
    if (f == "") {
        printf("ERROR: Empty trajectory path in trajectory list at line %d.\n", NR) > "/dev/stderr"
        err = 2
        exit 2
    }
    p = (f ~ /^\// || f ~ /^[A-Za-z]:[\/\\]/) ? f : d "/" f
    sub(/^[[:space:]]+/, "", rest_str)
    sub(/[[:space:]]+$/, "", rest_str)
    if (mode == "remd") {
        print "trajin \"" p "\"" (rest_str != "" ? " " rest_str : "") " remdtraj remdtrajtemp " t
    } else if (mode == "mix") {
        n_tok = split(rest_str, toks, /[[:space:]]+/)
        tag = (n_tok >= 1) ? tolower(toks[1]) : ""
        if (tag == "remd") {
            rem_rest = ""
            for (i = 2; i <= n_tok; i++) rem_rest = rem_rest " " toks[i]
            print "trajin \"" p "\"" rem_rest " remdtraj remdtrajtemp " t
        } else if (tag == "md") {
            rem_rest = ""
            for (i = 2; i <= n_tok; i++) rem_rest = rem_rest " " toks[i]
            print "trajin \"" p "\"" rem_rest
        } else {
            print "trajin \"" p "\"" (rest_str != "" ? " " rest_str : "")
        }
    } else {
        print "trajin \"" p "\"" (rest_str != "" ? " " rest_str : "")
    }
}
END { if (err) exit err }
' "$TRAJIN")
AWK_RC=$?
if [ "$AWK_RC" -ne 0 ]; then
    echo "ERROR: Failed to parse trajectory list '$TRAJIN'." | tee -a "$LOG_FILE"
    exit 1
fi

if [ -z "$TRAJIN_LINES" ]; then
    echo "ERROR: No trajectory entries found in '$TRAJIN'." | tee -a "$LOG_FILE"
    exit 1
fi

AUTOIMAGE_BLOCK=""
if is_truthy "$AUTOIMAGE"; then
    AUTOIMAGE_BLOCK=$'\nautoimage'
fi

STRIP_BLOCK=""
if is_truthy "$STRIP_SOLVENT"; then
    STRIP_MASK=":WAT,HOH,TIP3,TIP3P,TIP4,TIP4P,T4E,TIP5,TIP5P,OPC,SOL,SPC,SPCE,TP3,T3P,H2O,NA,CL,K,Na+,Cl-,K+,NA+,CL-,SOD,CLA,POT,CS,Cs+,CS+,RB,Rb+,RB+,LI,Li+,LI+,F,F-,BR,Br-,BR-,I,I-"
    if is_truthy "$STRIP_DIVALENT"; then
        STRIP_MASK="${STRIP_MASK},MG,CA,ZN,Mg2+,Ca2+,Zn2+,MG2+,CA2+,ZN2+,CAL"
    fi
    STRIP_BLOCK=$'\nstrip '"${STRIP_MASK}"
fi

OUT_PREFIX=${EXPORT_PREFIX:-$(basename "$PWD")}

cat << EOF > extract_minima.cpptraj
parm "$PRMTOP"
$TRAJIN_LINES$AUTOIMAGE_BLOCK$STRIP_BLOCK
trajout "${OUT_PREFIX}.pdb" multi onlyframes $FRAME_LIST
run
quit
EOF

echo "--------------------------------------------------------------" | tee -a "$LOG_FILE"
echo "Extracting frames in PDB format (running cpptraj)..." | tee -a "$LOG_FILE"
cpptraj -i extract_minima.cpptraj > cpptraj_export.log 2>&1

if [ $? -eq 0 ]; then
    echo "Converting file extensions to standard format (${OUT_PREFIX}.pdb.X -> ${OUT_PREFIX}_X.pdb) ..." | tee -a "$LOG_FILE"
    # cpptraj'ın ürettiği garip uzantılı dosyaları standart .pdb formatına çevir
    # Sadece bu scriptin ürettiği (başlangıcı belli olan) dosyaları hedefler ki veri kaybı yaşanmasın.
    converted_count=0
    for file in "${OUT_PREFIX}.pdb."*; do 
        # Dosya gerçekten varsa işlem yap (hata almamak için)
        if [ -e "$file" ]; then
            frame_num="${file#${OUT_PREFIX}.pdb.}"
            mv "$file" "${OUT_PREFIX}_${frame_num}.pdb"
            ((converted_count++))
        fi
    done
    if [ "$converted_count" -eq 0 ]; then
        echo "ERROR: cpptraj finished but no PDB files were generated! Check cpptraj_export.log and extract_minima.cpptraj." | tee -a "$LOG_FILE"
        exit 1
    fi
    rm -f extract_minima.cpptraj
    echo "Process Completed! All your PDB files have been added to the folder ready for use." | tee -a "$LOG_FILE"
else
    echo "ERROR: An error occurred while running cpptraj. Details in cpptraj_export.log; extract_minima.cpptraj preserved for inspection." | tee -a "$LOG_FILE"
    cat cpptraj_export.log | tee -a "$LOG_FILE"
    exit 1
fi
