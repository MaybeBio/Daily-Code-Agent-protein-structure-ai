"""
Analysis of Verlet (and OpenMM) runs: radial distribution functions, density
with block-averaged errors, diffusion from the mean squared displacement, and
free energies from alchemical windows (MBAR and thermodynamic integration).
Units: nm, ps, kJ/mol, K.
"""
module VerletAnalysis

using LinearAlgebra
using Printf
using Statistics

export read_vtrj, read_atom_names, read_csv, rdf, block_average, msd, diffusion, mbar, ti, rmsd, to_json

const KB = 0.00831446261815324  # kJ/mol/K

"""Frames of a VTRJ file: (positions :: Vector{Matrix{Float32}} (3 x n), boxes, times)."""
function read_vtrj(path)
    open(path) do io
        String(read(io, 4)) == "VTRJ" || error("$path: not a VTRJ trajectory")
        n = Int(read(io, Int32))
        xs, boxes, times = Matrix{Float32}[], Vector{Float64}[], Float64[]
        while !eof(io)
            read(io, Int64)  # step
            push!(times, read(io, Float64))
            push!(boxes, [read(io, Float64) for _ in 1:3])
            x = Matrix{Float32}(undef, 3, n)
            read!(io, x)
            push!(xs, x)
        end
        xs, boxes, times
    end
end

"""Atom names from a .vsys file."""
function read_atom_names(path)
    lines = readlines(path)
    i = findfirst(l -> startswith(l, "atoms "), lines)
    n = parse(Int, split(lines[i])[2])
    [split(lines[i+k])[1] for k in 1:n]
end

"""A CSV file with a header line (lines starting with # skipped): Dict column => values."""
function read_csv(path)
    rows = [l for l in readlines(path) if !isempty(l) && !startswith(l, "#")]
    head = split(rows[1], ',')
    cols = Dict(h => Float64[] for h in head)
    for l in rows[2:end]
        for (h, v) in zip(head, split(l, ','))
            push!(cols[h], parse(Float64, v))
        end
    end
    cols
end

"""
g(r) between atom sets A and B over frames (minimum image, orthorhombic box);
pairs with i == j are skipped. Returns (r centers, g).
"""
function rdf(frames, boxes, A::Vector{Int}, B::Vector{Int}; rmax = 1.0, nbins = 200, exclude = (a, b) -> false)
    # pairs that `exclude` rejects (e.g. within a molecule) are left out of the counts and of the normalization
    nex = count(b -> b != A[1] && exclude(A[1], b), B)
    dr = rmax / nbins
    hist = zeros(nbins)
    norm_sum = 0.0
    same = A == B
    for (x, L) in zip(frames, boxes)
        V = prod(L)
        @inbounds for a in A
            xa = x[1, a]; ya = x[2, a]; za = x[3, a]
            for b in B
                (same && b <= a) && continue
                exclude(a, b) && continue
                dx = x[1, b] - xa; dy = x[2, b] - ya; dz = x[3, b] - za
                dx -= L[1] * round(dx / L[1]); dy -= L[2] * round(dy / L[2]); dz -= L[3] * round(dz / L[3])
                r = sqrt(dx * dx + dy * dy + dz * dz)
                r < rmax || continue
                hist[Int(floor(r / dr))+1] += same ? 2 : 1
            end
        end
        # expected count per unit volume for an ideal gas of B around every A
        norm_sum += length(A) * ((same ? length(B) - 1 : length(B)) - nex) / V
    end
    r = [(k - 0.5) * dr for k in 1:nbins]
    shell = [4π / 3 * ((k * dr)^3 - ((k - 1) * dr)^3) for k in 1:nbins]
    r, hist ./ (shell .* norm_sum)
end

"""Mean and standard error from block averages (the statistical inefficiency of correlated samples)."""
function block_average(x::AbstractVector; blocks = 10)
    m = length(x) ÷ blocks
    means = [mean(x[(k-1)*m+1:k*m]) for k in 1:blocks]
    mean(x), std(means) / sqrt(blocks)
end

"""Mean squared displacement of atoms `idx` (unwrapped positions) for lags 1..maxlag frames."""
function msd(frames, idx; maxlag = length(frames) ÷ 2)
    out = zeros(maxlag)
    for lag in 1:maxlag
        s = 0.0
        cnt = 0
        for t in 1:length(frames)-lag
            a, b = frames[t], frames[t+lag]
            @inbounds for i in idx
                s += (b[1, i] - a[1, i])^2 + (b[2, i] - a[2, i])^2 + (b[3, i] - a[3, i])^2
            end
            cnt += length(idx)
        end
        out[lag] = s / cnt
    end
    out
end

"""
Self-diffusion coefficient (cm^2/s) from the slope of the MSD over [fit_from, fit_to] ps,
and with the Yeh-Hummer finite-size correction kT xi / (6 pi eta L) for a cubic box.
"""
function diffusion(lag_ps, msd_nm2; fit_from = 5.0, fit_to = 20.0, T = 298.15, L = 4.0, eta = 0.321e-3)
    sel = (lag_ps .>= fit_from) .& (lag_ps .<= fit_to)
    X = [ones(count(sel)) lag_ps[sel]]
    slope = (X \ msd_nm2[sel])[2]                # nm^2/ps
    d = slope / 6 * 1e-2  # 1 nm^2/ps = 1e-2 cm^2/s
    xi = 2.837297
    kb = 1.380649e-23
    corr = kb * T * xi / (6π * eta * L * 1e-9) * 1e4  # m^2/s -> cm^2/s
    d, d + corr
end

"""
MBAR (Shirts and Chodera 2008): free energies f_k (in kT) of K states from
u[n, k], the reduced energy of sample n in state k, with N[k] samples from
each state (samples grouped by state in order). Returns f and its
statistical uncertainty against state 1 (from the asymptotic covariance).
"""
function mbar(u::Matrix{Float64}, N::Vector{Int}; tol = 1e-10, maxiter = 10000)
    nt, K = size(u)
    f = zeros(K)
    logN = log.(N)
    for it in 1:maxiter
        # log denominator for every sample: log sum_k N_k exp(f_k - u_nk)
        ld = similar(u, nt)
        for n in 1:nt
            m = maximum(logN .+ f .- u[n, :])
            ld[n] = m + log(sum(exp.(logN .+ f .- u[n, :] .- m)))
        end
        fnew = [-(let a = -u[:, k] .- ld; m = maximum(a); m + log(sum(exp.(a .- m))) end) for k in 1:K]
        fnew .-= fnew[1]
        done = maximum(abs.(fnew .- f)) < tol
        f = fnew
        done && break
    end
    # weights W[n, k] and the asymptotic covariance of f
    W = zeros(nt, K)
    for n in 1:nt
        a = logN .+ f .- u[n, :]
        m = maximum(a)
        den = m + log(sum(exp.(a .- m)))
        for k in 1:K
            W[n, k] = exp(f[k] - u[n, k] - den)
        end
    end
    Theta = pinv(I - W' * W * Diagonal(N)) * W' * W
    err = [sqrt(max(Theta[k, k] + Theta[1, 1] - 2Theta[1, k], 0.0)) for k in 1:K]
    f, err
end

"""
RMSD (nm) of atoms `idx` between two 3 x n coordinate sets after the best
superposition (Kabsch: centers removed, rotation from the SVD of the covariance).
"""
function rmsd(a::AbstractMatrix, b::AbstractMatrix, idx)
    P = Float64.(a[:, idx])
    Q = Float64.(b[:, idx])
    P .-= sum(P, dims = 2) ./ size(P, 2)
    Q .-= sum(Q, dims = 2) ./ size(Q, 2)
    U, _, V = svd(P * Q')
    d = sign(det(V * U'))
    R = V * Diagonal([1.0, 1.0, d]) * U'
    sqrt(sum(abs2, R * P .- Q) / length(idx))
end

"""Thermodynamic integration by the trapezoid rule over lambda, with propagated standard errors."""
function ti(lambdas, means, errs)
    dG = 0.0
    var = 0.0
    for k in 1:length(lambdas)-1
        h = lambdas[k+1] - lambdas[k]
        dG += h * (means[k] + means[k+1]) / 2
        var += (h / 2)^2 * (errs[k]^2 + errs[k+1]^2)
    end
    dG, sqrt(var)
end

"""A tiny JSON writer for Dicts, vectors, numbers and strings."""
to_json(x::AbstractDict) = "{" * join(["\"$(k)\": $(to_json(v))" for (k, v) in x], ", ") * "}"
to_json(x::AbstractVector) = "[" * join(map(to_json, x), ", ") * "]"
to_json(x::AbstractString) = "\"" * replace(x, "\"" => "\\\"") * "\""
to_json(x::Bool) = x ? "true" : "false"
to_json(x::Integer) = string(x)
to_json(x::Real) = isfinite(x) ? @sprintf("%.6g", x) : "null"
to_json(::Nothing) = "null"

end
