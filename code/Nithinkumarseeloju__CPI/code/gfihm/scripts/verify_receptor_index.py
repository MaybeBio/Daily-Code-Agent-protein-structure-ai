"""Validate independently indexed receptors and the reported manual-query error."""
import json
from cpi_data import ROOT,connect,find_receptor,find_receptor_homolog
with connect() as c:
    count=c.execute('SELECT count(*) FROM receptor_scanned').fetchone()[0]
    assert count==17479,count
    sequence=c.execute("SELECT sequence FROM receptors WHERE pdb_id='2ity' AND chain='A'").fetchone()[0]
    supplied=dict(c.execute("SELECT * FROM pairs WHERE id='ecac5d3b84dbd959044d85af7595ae718126117ab9aaf6edbcbb1365e9f72724'").fetchone())
    homology_pair=dict(c.execute("SELECT * FROM pairs WHERE id='836fc3a3aaf51618a2aa2869157d98a1bccb2394b0e06dc9f58e0d661309c44b'").fetchone())
matched=find_receptor(sequence)
assert matched and matched['query_coverage']==1 and matched['identity']==1,matched
assert matched['method'].startswith('Protein-only lookup')
missing=find_receptor(supplied['sequence'])
homolog=find_receptor_homolog(homology_pair['sequence'])
assert missing is None
assert homolog and homolog['identity']>=.90 and homolog['query_coverage']>=.60 and homolog['chain_coverage']>=.95,homolog
assert homolog['pocket_identity']==1.0 and homolog['pocket_residues']>0,homolog
assert find_receptor_homolog('A'*len(homology_pair['sequence'])) is None
report=dict(result='PASS',scanned_structures=count,protein_only_example=matched,
            reported_query=dict(pair_id=supplied['id'],sequence_length=len(supplied['sequence']),exact_receptor=missing),
            homology_query=dict(pair_id=homology_pair['id'],sequence_length=len(homology_pair['sequence']),template=homolog),
            scope='Exact matches remain separate from homolog templates. Homologs require a high-identity, high-coverage alignment and fully sequence-identical contacting pocket.')
(ROOT/'reports/receptor_validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
