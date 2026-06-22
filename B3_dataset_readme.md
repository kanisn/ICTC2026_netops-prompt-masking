# B-3 Synthetic Config Dataset

- Total samples: 50
- Real production data: not used
- C3 samples: 11 / 50 (22.0%)
- Main task: natural-language request → normalized network config/command

## Columns

| Column | Meaning |
|---|---|
| sample_id | Sample identifier |
| task_type | Config task type |
| natural_language_request_ko | Korean natural-language request given to the model |
| sensitive_fields_json | Labeled sensitive fields in JSON string |
| sensitive_categories | Part-A sensitive categories covered by the sample |
| expected_answer_normalized | Expected normalized command/config |
| c3_required | Whether consistent pseudonymization is intentionally tested |
| c3_relation_type | Relation pattern for C3 cases |
| notes | Short annotation note |

## Task distribution

{
  "firewall_config": 10,
  "qos_config": 10,
  "sdn_flow_config": 10,
  "ran_handover_config": 8,
  "slice_policy_config": 6,
  "edge_acl_config": 2,
  "operator_history_config": 2,
  "rag_doc_config": 2
}

## Sensitive category coverage

{
  "User identity": 50,
  "Location and mobility": 19,
  "Policy and configuration": 50,
  "Traffic metadata": 38,
  "Network topology": 24,
  "Internal RAG documents": 4,
  "Operator interaction history": 2
}
