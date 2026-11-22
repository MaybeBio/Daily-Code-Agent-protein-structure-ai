#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GRACE held-out evaluation suite (revision round, 2026-11-06).

Upload this file to /root/run_heldout_suite.py on the AutoDL instance, then run
ONE subcommand per terminal (absolute paths; original files are never modified):

  A terminal (long, ~1-2 h):
    python /root/run_heldout_suite.py baselines 2>&1 | tee /root/repro/baselines/suite_baselines.log

  B terminal (minutes):
    python /root/run_heldout_suite.py stratify 2>&1 | tee /root/repro/baselines/suite_stratify.log

  B terminal (10-30 min):
    python /root/run_heldout_suite.py overlap 2>&1 | tee /root/repro/baselines/suite_overlap.log

All outputs land in /root/repro/baselines/.
"""
import os, sys, re, json, csv, glob, time, pickle

B = '/root/overlap73/'
H = '/root/LLM/Model-Heltout/'
G = H + 'Dataset/Graph_init/'
CORPUS = '/root/LLM73/pretrain_combined_73_20m.json'
SCORE_KEYS = ['num_known_complexes', 'num_pred_complexes',
              'Precision', 'Recall', 'F1', 'Global_MMR', 'Mean_MMR']

sys.path.insert(0, H)
# token_id_gene.pkl was pickled from a __main__ script; register the class name.
sys.modules['__main__'].TokenIDGene = type('TokenIDGene', (), {})
import Eval as E


def log(*a):
    print(*a, flush=True)


def mapping():
    return pickle.load(open(G + 'token_id_gene.pkl', 'rb')).id_to_gene


def heldout(id_to_gene):
    """768 known complexes as gene sets, plus size / mean PPI degree / subset label."""
    tests = pickle.load(open('/root/LLM73/split73/Complex_Test.pkl', 'rb'))
    known = [{id_to_gene[n] for n in c.nodes() if n in id_to_gene} for c in tests]
    sizes = [len(c.nodes()) for c in tests]
    graph = pickle.load(open(G + 'graph.pkl', 'rb'))
    deg = [sum(graph.degree(n) for n in c.nodes()) / float(max(1, len(c.nodes())))
           for c in tests]
    try:
        un = {frozenset(c.nodes()) for c in pickle.load(open('/root/LLM73/split73/Test_truly_unseen.pkl', 'rb'))}
        ov = {frozenset(c.nodes()) for c in pickle.load(open('/root/LLM73/split73/Test_has_overlap.pkl', 'rb'))}
        groups = ['unseen' if frozenset(c.nodes()) in un else
                  ('overlap' if frozenset(c.nodes()) in ov else 'unassigned')
                  for c in tests]
    except Exception as ex:
        log('GROUP_WARN', repr(ex)[:200])
        groups = ['all'] * len(tests)
    log('HELDOUT', len(known), 'sizes', min(sizes), max(sizes),
        'groups', {g: groups.count(g) for g in set(groups)})
    return known, sizes, deg, groups


def score(known, pred):
    r = E.evaluate(known, pred, threshold=0.2)
    return {k: round(float(r[k]), 4) for k in SCORE_KEYS}


def pred_pkl(path):
    return [set(x['sft_response'].split()) for x in pickle.load(open(path, 'rb'))]


def pred_txt(path, id_to_gene):
    out = []
    for line in open(path):
        s = {id_to_gene[int(i)] for i in line.split() if int(i) in id_to_gene}
        if s:
            out.append(s)
    return out


def write_csv(path, header, rows):
    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    log('WROTE', path, len(rows), 'rows')


# ------------------------------------------------------------------ S1
def cmd_baselines():
    import protclus
    id_to_gene = mapping()
    known, _, _, _ = heldout(id_to_gene)
    inputs = {}
    # A run interrupted by shutdown can leave a partial pred file. Only skip
    # when the log contains an explicit DONE line for that method.
    done = set()
    logfile = B + 'suite_baselines.log'
    if os.path.exists(logfile):
        for ln in open(logfile, errors='ignore'):
            if ln.startswith('DONE '):
                done.add(ln.split()[1])
    for name, cls in [('dpclus', protclus.DPCLUS), ('ipca', protclus.IPCA)]:
        out = B + 'pred_%s.txt' % name
        if name in done and os.path.exists(out) and os.path.getsize(out) > 0:
            log('SKIP', name, 'completed in log')
            inputs[name] = 'existing'
            continue
        if os.path.exists(out):
            os.remove(out)
            log('DISCARD_PARTIAL', name)
        t = time.time()
        c, used = None, None
        for fn in ('ppi_edges.txt', 'ppi_edges_w1.txt'):
            try:
                log('START', name, fn)
                c = cls(B + fn)
                c.cluster()
                used = fn
                break
            except Exception as ex:
                log('RETRY', name, fn, repr(ex)[:200])
                c = None
        if c is None:
            log('FAILED', name)
            continue
        c.save_clusters(out)
        inputs[name] = used
        log('DONE', name, 'clusters', len(getattr(c, 'clusters', [])),
            'input', used, 'sec', round(time.time() - t, 1))

    grace = pred_pkl(H + 'generation_results.pkl')
    r = score(known, grace)
    rows = [['GRACE', 'Model-Heltout/generation_results.pkl'] + [r[k] for k in SCORE_KEYS]]
    log('GRACE', r)
    for p in sorted(glob.glob(B + 'pred_*.txt')):
        name = os.path.basename(p)[5:-4]
        r = score(known, pred_txt(p, id_to_gene))
        rows.append([name, inputs.get(name, 'existing')] + [r[k] for k in SCORE_KEYS])
        log('BASE', name, r)
    write_csv(B + 'table_b.csv', ['method', 'input_file'] + SCORE_KEYS, rows)
    log('S1_DONE')


# ------------------------------------------------------------------ S2
def size_bin(n):
    if n <= 3: return '2-3'
    if n <= 5: return '4-5'
    if n <= 10: return '6-10'
    if n <= 20: return '11-20'
    return '>20'


def deg_bin(d):
    if d <= 5: return '<=5'
    if d <= 15: return '6-15'
    if d <= 30: return '16-30'
    return '>30'


def cmd_stratify():
    id_to_gene = mapping()
    known, sizes, deg, groups = heldout(id_to_gene)
    pred = pred_pkl(H + 'generation_results.pkl')
    combos = [('all', lambda i: True)]
    combos += [(g, (lambda i, g=g: groups[i] == g)) for g in ('overlap', 'unseen')]
    bins = [('size', [size_bin(n) for n in sizes]),
            ('ppi_degree', [deg_bin(d) for d in deg])]
    rows = []
    for subset, keep in combos:
        idx = [i for i in range(len(known)) if keep(i)]
        for btype, labels in bins:
            for lab in sorted(set(labels)):
                sel = [i for i in idx if labels[i] == lab]
                if not sel:
                    continue
                r = score([known[i] for i in sel], pred)
                note = 'descriptive_only_small_n' if len(sel) < 10 else ''
                rows.append([subset, btype, lab, len(sel)] + [r[k] for k in SCORE_KEYS] + [note])
                log('BIN', subset, btype, lab, 'n', len(sel), 'Mean_MMR', r['Mean_MMR'])
    write_csv(B + 'stratified_heldout.csv',
              ['subset', 'bin_type', 'bin', 'n_known'] + SCORE_KEYS + ['note'], rows)
    log('S2_DONE', 'same full prediction set against each gold-standard subset; no p-values')


# ------------------------------------------------------------------ S3
def cmd_overlap():
    id_to_gene = mapping()
    known, sizes, _, groups = heldout(id_to_gene)
    inv = {}
    for i, s in enumerate(known):
        for g in s:
            inv.setdefault(g, []).append(i)
    hit_sup = [0] * len(known)
    hit_exact = [0] * len(known)
    first = [-1] * len(known)
    pat = re.compile(r'<\|im_start\|>(.*?)<\|im_end\|>')
    n_text = n_seq = 0
    t = time.time()
    with open(CORPUS, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if not s.startswith('"text"'):
                continue
            if s.endswith(','):
                s = s[:-1]
            try:
                text = json.loads('{' + s + '}')['text']
            except Exception:
                continue
            n_text += 1
            if n_text % 200000 == 0:
                log('PROGRESS', n_text, 'text lines', n_seq, 'seqs',
                    round(time.time() - t, 1), 's')
            for seq in pat.findall(text):
                n_seq += 1
                gs = set(seq.split())
                ngs = len(gs)
                cand = set()
                for g in gs:
                    cand.update(inv.get(g, ()))
                for i in cand:
                    ks = known[i]
                    if len(ks) <= ngs and ks <= gs:
                        hit_sup[i] += 1
                        if first[i] < 0:
                            first[i] = n_text
                        if len(ks) == ngs:
                            hit_exact[i] += 1
    rows = [[i, groups[i], sizes[i], hit_sup[i], hit_exact[i], first[i]]
            for i in range(len(known))]
    write_csv(B + 'corpus_overlap.csv',
              ['idx', 'subset', 'size', 'n_hit_superset', 'n_hit_exact',
               'first_hit_text_line'], rows)
    lines = ['text_lines %d' % n_text, 'bfs_sequences %d' % n_seq,
             'heldout_complexes %d' % len(known),
             'elapsed_sec %.1f' % (time.time() - t)]
    for g in sorted(set(groups)):
        idx = [i for i in range(len(known)) if groups[i] == g]
        lines.append('%s n=%d hit_superset>=1 %d (%.1f%%) hit_exact>=1 %d (%.1f%%)' % (
            g, len(idx), sum(hit_sup[i] > 0 for i in idx),
            100.0 * sum(hit_sup[i] > 0 for i in idx) / max(1, len(idx)),
            sum(hit_exact[i] > 0 for i in idx),
            100.0 * sum(hit_exact[i] > 0 for i in idx) / max(1, len(idx))))
    lines.append('DISCLOSURE_ONLY: report these frequencies; do NOT claim test members were excluded.')
    open(B + 'corpus_overlap_summary.txt', 'w').write('\n'.join(lines) + '\n')
    log('\n'.join(lines))
    log('S3_DONE')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'baselines':
        cmd_baselines()
    elif cmd == 'stratify':
        cmd_stratify()
    elif cmd == 'overlap':
        cmd_overlap()
    else:
        print(__doc__)
