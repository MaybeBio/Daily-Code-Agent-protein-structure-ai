using Test
using Random
using Statistics
using VerletAnalysis

@testset "VerletAnalysis" begin
    @testset "rdf of an ideal gas is 1" begin
        rng = MersenneTwister(1)
        L = [3.0, 3.0, 3.0]
        frames = [rand(rng, Float32, 3, 2000) .* 3.0f0 for _ in 1:5]
        r, g = rdf(frames, fill(L, 5), collect(1:2000), collect(1:2000); rmax = 1.4, nbins = 14)
        @test all(abs.(g[3:end] .- 1) .< 0.05)
        # leaving out pairs within groups of 3 keeps an ideal gas at 1
        _, g2 = rdf(frames, fill(L, 5), collect(1:2000), collect(1:2000); rmax = 1.4, nbins = 14, exclude = (a, b) -> (a - 1) ÷ 3 == (b - 1) ÷ 3)
        @test all(abs.(g2[3:end] .- 1) .< 0.05)
    end

    @testset "msd and diffusion of a random walk" begin
        rng = MersenneTwister(2)
        n, T, s = 500, 400, 0.05  # step size per frame (nm per axis)
        x = zeros(Float32, 3, n)
        frames = Matrix{Float32}[]
        for t in 1:T
            x .+= s .* randn(rng, Float32, 3, n)
            push!(frames, copy(x))
        end
        m = msd(frames, collect(1:n); maxlag = 50)
        @test m[10] ≈ 3 * 10 * s^2 rtol = 0.05
        lag = collect(1.0:50.0)  # one frame per ps
        d, _ = diffusion(lag, m; fit_from = 1, fit_to = 50)
        @test d ≈ 3 * s^2 / 6 * 1e-2 rtol = 0.05
    end

    @testset "block average" begin
        m, e = block_average(collect(1.0:100.0))
        @test m == 50.5 && e > 0
    end

    @testset "mbar and ti on harmonic states" begin
        # states: U_k(x) = k_k x^2 / 2 (in kT); exact f_k - f_1 = log(sqrt(k_k / k_1))
        rng = MersenneTwister(3)
        ks = [1.0, 2.0, 4.0, 8.0]
        N = fill(4000, 4)
        xs = vcat([randn(rng, 4000) ./ sqrt(k) for k in ks]...)
        u = [k * x^2 / 2 for x in xs, k in ks]
        f, err = mbar(u, N)
        exact = 0.5 .* log.(ks ./ ks[1])
        @test all(abs.(f .- exact) .< 4 .* err .+ 1e-3)
        @test err[1] < 1e-8 && all(err[2:end] .> 0)
        dG, e = ti([0.0, 0.5, 1.0], [1.0, 2.0, 3.0], [0.1, 0.1, 0.1])
        @test dG ≈ 2.0 && e > 0
    end

    @testset "json" begin
        @test to_json(Dict("a" => [1, 2.5], "b" => "x")) in ("{\"a\": [1, 2.5], \"b\": \"x\"}", "{\"b\": \"x\", \"a\": [1, 2.5]}")
    end
end

@testset "rmsd after superposition" begin
    rng = MersenneTwister(4)
    P = randn(rng, 3, 20)
    t = 0.7
    R = [cos(t) -sin(t) 0; sin(t) cos(t) 0; 0 0 1]
    Q = R * P .+ [1.0, -2.0, 0.5]
    @test rmsd(P, Q, 1:20) < 1e-10              # a rigid motion
    Q2 = Q .+ 0.1 .* [1, 0, 0] .* (-1) .^ (1:20)'  # plus alternating shifts of 0.1
    @test rmsd(P, Q2, 1:20) ≈ 0.1 rtol = 0.05
end
