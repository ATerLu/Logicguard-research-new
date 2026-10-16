"""Read-only defense review probes. Uses in-memory toy data, no model/API calls."""
import json
from pathlib import Path
from dataclasses import replace
from logicguard.defense.risk_aware_recovery import detect_non_oracle_source_risk, build_stage28_context_rows
from logicguard.defense.non_oracle_recovery import NonOracleCandidateSource
from logicguard.defense.chain_completion import build_stage38_chain_rows
from logicguard.data.schemas import NormalizedSample, CorpusDocument

def cand(doc,text,title='Target',number=1):
    return NonOracleCandidateSource(id='tu-'+doc,text_unit_id='tu-'+doc,logicguard_doc_id=doc,official_document_id=doc,human_readable_id=number,title=title,text=f'Document ID: {doc}\nTitle: {title}\n\n{text}',n_tokens=10)
def src(doc,text,title='Target',state='official_poisoned_context'):
    return {'id':doc,'logicguard_doc_id':doc,'title':title,'text':f'Document ID: {doc}\nTitle: {title}\n\n{text}','source_state':state}
def brief(r):
    return dict(is_risky=r.is_risky,status=r.verification_status,entity_drift=r.entity_drift,title_overlap=r.title_overlap,text_jaccard=r.text_token_jaccard,reasons=r.risk_reasons,candidate_doc_id=r.candidate_doc_id)

out={}
for label, clean, changed in [
 ('year_flip','Alice was born in 1980 and won 3 awards.','Alice was born in 1990 and won 3 awards.'),
 ('negation_flip','Alice was born in 1980 and won 3 awards.','Alice was not born in 1980 and won 3 awards.'),
 ('relation_direction_flip','Alice hired Bob.','Bob hired Alice.'),
]:
    out[label]=brief(detect_non_oracle_source_risk(query='Who is Alice?',source=src('d1',changed,'Alice'),candidate_sources=[cand('d1',clean,'Alice')],entities=['Alice']))
# Missing trusted candidate: unverifiable sources survive every policy.
missing=build_stage28_context_rows(source_context_rows=[{'query_id':'q','query':'Who wrote Alpha?','method':'full_query_guard','include_entity_names':['Alpha'],'unknown_entity_names':[],'context_data':{'sources':[src('x','Poisoned Alpha fact','Alpha')],'entities':[]}}],candidate_sources=[])
out['missing_candidate']= [dict(method=row['method'],source_count=len(row['context_data']['sources']),status=row['context_data']['sources'][0].get('risk_non_oracle_verification_status')) for row in missing]
# A complete context still gets an unrelated zero-score append.
sample=NormalizedSample('q','Who is Alice?','Alice',['d1'],[CorpusDocument('d1','Alice','Alice')])
complete={'query_id':'q','method':'full_query_guard','query':sample.query,'context_data':{'sources':[src('d1','Alice is Alice','Alice','clean_reference')]}}
rows=build_stage38_chain_rows(samples=[sample],context_rows=[complete],candidate_sources=[cand('d2','Banana grows somewhere','Banana')],judged_rows=[],dataset='toy',methods=['full_query_guard'],max_sources=2,max_chars_per_source=500,candidate_pool_top_k=2)
out['stage38_complete_context']= [dict(chain_complete=row.chain_complete,targeted_chain_complete=row.targeted_chain_complete,base_ids=row.context_doc_ids,targeted_ids=row.targeted_context_doc_ids,added=row.targeted_added_doc_ids,added_score=row.targeted_sources[-1].get('stage38_candidate_score')) for row in rows]
# Support IDs plus clean flag are sufficient for chain_complete, despite contradictory body / missing answer.
sample2=NormalizedSample('q','Who did Alice hire?','Bob',['d1'],[CorpusDocument('d1','Alice','Alice hired Bob.')])
wrong={'query_id':'q','method':'full_query_guard','query':sample2.query,'context_data':{'sources':[src('d1','Alice hired Charlie.','Alice','clean_reference')]}}
row=build_stage38_chain_rows(samples=[sample2],context_rows=[wrong],candidate_sources=[],judged_rows=[],dataset='toy',methods=['full_query_guard'],max_sources=1,max_chars_per_source=500,candidate_pool_top_k=2)[0]
out['stage38_wrong_fact_marked_complete']=dict(chain_complete=row.chain_complete,context_has_gold_answer=row.context_has_gold_answer,diagnosis=row.chain_diagnosis)
# A valid unchanged source not marked clean_reference is diagnosed unsafe regardless of actual content.
normal={'query_id':'q','method':'full_query_guard','query':sample2.query,'context_data':{'sources':[src('d1','Alice hired Bob.','Alice')]}}
row=build_stage38_chain_rows(samples=[sample2],context_rows=[normal],candidate_sources=[],judged_rows=[],dataset='toy',methods=['full_query_guard'],max_sources=1,max_chars_per_source=500,candidate_pool_top_k=2)[0]
out['stage38_unchanged_source_marked_unsafe']=dict(chain_complete=row.chain_complete,context_has_gold_answer=row.context_has_gold_answer,diagnosis=row.chain_diagnosis,unrecovered_changed_doc_ids=row.unrecovered_changed_doc_ids)
# Same-title candidates select first numeric order, and replacement is copied without a claim gate.
colliding=[cand('d2','Mallory hired Dave.','Alice',0),cand('d1','Alice hired Bob.','Alice',1)]
rows=build_stage28_context_rows(source_context_rows=[{'query_id':'q','query':'Who did Alice hire?','method':'full_query_guard','context_data':{'sources':[src('d1','Alice hired Charlie.','Alice')]}}],candidate_sources=colliding)
rec=next(row for row in rows if row['method']=='risk_non_oracle_title_entity_bm25')['context_data']['sources'][0]
out['same_title_recovery']=dict(recovered_doc=rec['logicguard_doc_id'],recovered_text=rec['text'],state=rec['source_state'],risk_status=rec['risk_non_oracle_verification_status'])
Path('/tmp/logicguard_review_20261016/defense_probe.json').write_text(json.dumps(out,indent=2,ensure_ascii=False))
print(json.dumps(out,indent=2,ensure_ascii=False))
# Legacy MVP: explicit reference mismatch can be cancelled by bridge support.
from logicguard.defense.reranker import build_guarded_trace
from logicguard.graph.schemas import PathCandidate, RetrievalTrace
tr=RetrievalTrace(query_id='q',query='Alice?',answer='Bob',gold_doc_ids=['d1'],query_entities=[],candidates=[PathCandidate(doc_id='d1',title='Target',score=1.0,path_nodes=['q','bridge','d1'],matched_query_entities=['Alice'],bridge_entities=['Bob'])])
kept=build_guarded_trace(tr,risk_penalty=.75,risk_threshold=.9,reference_doc_ids={'d1'},changed_doc_ids={'d1'})
out['legacy_mvp_changed_bridge_retained']=[dict(doc=c.doc_id,risk=c.risk_score,reasons=c.risk_reasons) for c in kept.candidates]
Path('/tmp/logicguard_review_20261016/defense_probe.json').write_text(json.dumps(out,indent=2,ensure_ascii=False))
print('legacy_mvp_changed_bridge_retained:',out['legacy_mvp_changed_bridge_retained'])
# Detector FPR denominator must be the pre-defense negatives; currently post-filter survivors are used.
from logicguard.defense.risk_aware_recovery import build_stage28_metric_rows
m=build_stage28_metric_rows(samples=[sample],integrity_rows=[{'query_id':'q','changed_support_doc_ids':[]}],context_rows=[{'query_id':'q','method':'risk_non_oracle_guarded_sources','context_data':{'sources':[]},'risk_detected_source_doc_ids':['d1','d2'],'filtered_source_doc_ids':['d1','d2'],'recovered_source_doc_ids':[]}],dataset='toy')[0]
out['stage28_fpr_above_one']=dict(risk_false_positive_rate=m.risk_false_positive_rate,false_positive=m.risk_false_positive_doc_ids,source_count=m.source_count)
Path('/tmp/logicguard_review_20261016/defense_probe.json').write_text(json.dumps(out,indent=2,ensure_ascii=False))
print('stage28_fpr_above_one:',out['stage28_fpr_above_one'])
