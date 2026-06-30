# Signal Gap Official Request Batches

Generated from the local-source action plan. Each batch tracks one missing signal family and the counties that need an official read API, authorization-gated adapter path, production adapter, or official unavailable-source record.

## pump_or_gate_status

- Batch id: `signal-gap-batch/pump_or_gate_status`
- Dispatch status: `not_sent`
- Sent at: `None`
- Follow-up due at: `None`
- Official reply ref: `None`
- County count: 13
- Private evidence hint: `private-ops://local-source/signal-gap-batch/pump_or_gate_status`
- Counties: 連江縣, 金門縣, 臺東縣, 苗栗縣, 澎湖縣, 南投縣, 嘉義市, 基隆市, 宜蘭縣, 新北市, 新竹縣, 桃園市, 臺中市
- Requested counterparties:
  - 連江縣政府公開資料或防災水利窗口
  - 金門縣政府 / KWIS 維運窗口
  - 臺東縣政府公開資料或水利防災維運窗口
  - 苗栗縣政府公開資料或水利防災維運窗口
  - 澎湖縣政府公開資料或水利防災維運窗口
  - 南投縣政府公開資料或水利防災維運窗口
  - 嘉義市政府公開資料或水利防災維運窗口
  - 基隆市政府公開資料或水利防災維運窗口
  - 宜蘭縣政府公開資料或水利防災維運窗口
  - 新北市政府公開資料或水利防災維運窗口
  - 新竹縣政府公開資料或水利防災維運窗口
  - 桃園市政府公開資料或水利防災維運窗口
  - 臺中市政府公開資料或水利防災維運窗口
- Required read API fields: `observed_at`, `station_or_device_id`, `measurement_value`, `measurement_unit_or_type`, `longitude_latitude_or_joinable_station_metadata`, `official_source_url_and_license`
- Production operational requirements: `freshness_policy`, `raw_snapshot_retention_policy`, `monitored_scheduler_cadence`, `hosted_egress_review`, `worker_persisted_evidence_path`
- Packet generator command: `PYTHONPATH=apps/api python scripts/local-source-request-packets.py --format markdown --signal-type pump_or_gate_status --county 連江縣 --county 金門縣 --county 臺東縣 --county 苗栗縣 --county 澎湖縣 --county 南投縣 --county 嘉義市 --county 基隆市 --county 宜蘭縣 --county 新北市 --county 新竹縣 --county 桃園市 --county 臺中市`
- Completion gate: Each county must provide a latest-observation read API, an authorization-gated adapter path, or an official unavailable-source record for pump_or_gate_status, plus production ops evidence.
- Completion evidence targets:
  - signal_family_gap_evidence / pump_or_gate_status; accepted statuses: accepted, authorization_gated_adapter, official_unavailable, production_adapter; evidence_ref hint: private-ops://local-source/signal-gap/連江縣/pump_or_gate_status
  - signal_family_gap_evidence / pump_or_gate_status; accepted statuses: accepted, authorization_gated_adapter, official_unavailable, production_adapter; evidence_ref hint: private-ops://local-source/signal-gap/金門縣/pump_or_gate_status
  - signal_family_gap_evidence / pump_or_gate_status; accepted statuses: accepted, authorization_gated_adapter, official_unavailable, production_adapter; evidence_ref hint: private-ops://local-source/signal-gap/臺東縣/pump_or_gate_status
  - signal_family_gap_evidence / pump_or_gate_status; accepted statuses: accepted, authorization_gated_adapter, official_unavailable, production_adapter; evidence_ref hint: private-ops://local-source/signal-gap/苗栗縣/pump_or_gate_status
  - signal_family_gap_evidence / pump_or_gate_status; accepted statuses: accepted, authorization_gated_adapter, official_unavailable, production_adapter; evidence_ref hint: private-ops://local-source/signal-gap/澎湖縣/pump_or_gate_status
  - signal_family_gap_evidence / pump_or_gate_status; accepted statuses: accepted, authorization_gated_adapter, official_unavailable, production_adapter; evidence_ref hint: private-ops://local-source/signal-gap/南投縣/pump_or_gate_status
  - signal_family_gap_evidence / pump_or_gate_status; accepted statuses: accepted, authorization_gated_adapter, official_unavailable, production_adapter; evidence_ref hint: private-ops://local-source/signal-gap/嘉義市/pump_or_gate_status
  - signal_family_gap_evidence / pump_or_gate_status; accepted statuses: accepted, authorization_gated_adapter, official_unavailable, production_adapter; evidence_ref hint: private-ops://local-source/signal-gap/基隆市/pump_or_gate_status
  - signal_family_gap_evidence / pump_or_gate_status; accepted statuses: accepted, authorization_gated_adapter, official_unavailable, production_adapter; evidence_ref hint: private-ops://local-source/signal-gap/宜蘭縣/pump_or_gate_status
  - signal_family_gap_evidence / pump_or_gate_status; accepted statuses: accepted, authorization_gated_adapter, official_unavailable, production_adapter; evidence_ref hint: private-ops://local-source/signal-gap/新北市/pump_or_gate_status
  - signal_family_gap_evidence / pump_or_gate_status; accepted statuses: accepted, authorization_gated_adapter, official_unavailable, production_adapter; evidence_ref hint: private-ops://local-source/signal-gap/新竹縣/pump_or_gate_status
  - signal_family_gap_evidence / pump_or_gate_status; accepted statuses: accepted, authorization_gated_adapter, official_unavailable, production_adapter; evidence_ref hint: private-ops://local-source/signal-gap/桃園市/pump_or_gate_status
  - signal_family_gap_evidence / pump_or_gate_status; accepted statuses: accepted, authorization_gated_adapter, official_unavailable, production_adapter; evidence_ref hint: private-ops://local-source/signal-gap/臺中市/pump_or_gate_status

## flood_depth

- Batch id: `signal-gap-batch/flood_depth`
- Dispatch status: `not_sent`
- Sent at: `None`
- Follow-up due at: `None`
- Official reply ref: `None`
- County count: 3
- Private evidence hint: `private-ops://local-source/signal-gap-batch/flood_depth`
- Counties: 連江縣, 澎湖縣, 臺北市
- Requested counterparties:
  - 連江縣政府公開資料或防災水利窗口
  - 澎湖縣政府公開資料或水利防災維運窗口
  - 臺北市政府公開資料或水利防災維運窗口
- Required read API fields: `observed_at`, `station_or_device_id`, `measurement_value`, `measurement_unit_or_type`, `longitude_latitude_or_joinable_station_metadata`, `official_source_url_and_license`
- Production operational requirements: `freshness_policy`, `raw_snapshot_retention_policy`, `monitored_scheduler_cadence`, `hosted_egress_review`, `worker_persisted_evidence_path`
- Packet generator command: `PYTHONPATH=apps/api python scripts/local-source-request-packets.py --format markdown --signal-type flood_depth --county 連江縣 --county 澎湖縣 --county 臺北市`
- Completion gate: Each county must provide a latest-observation read API, an authorization-gated adapter path, or an official unavailable-source record for flood_depth, plus production ops evidence.
- Completion evidence targets:
  - signal_family_gap_evidence / flood_depth; accepted statuses: accepted, authorization_gated_adapter, official_unavailable, production_adapter; evidence_ref hint: private-ops://local-source/signal-gap/連江縣/flood_depth
  - signal_family_gap_evidence / flood_depth; accepted statuses: accepted, authorization_gated_adapter, official_unavailable, production_adapter; evidence_ref hint: private-ops://local-source/signal-gap/澎湖縣/flood_depth
  - signal_family_gap_evidence / flood_depth; accepted statuses: accepted, authorization_gated_adapter, official_unavailable, production_adapter; evidence_ref hint: private-ops://local-source/signal-gap/臺北市/flood_depth

## sewer_water_level

- Batch id: `signal-gap-batch/sewer_water_level`
- Dispatch status: `not_sent`
- Sent at: `None`
- Follow-up due at: `None`
- Official reply ref: `None`
- County count: 1
- Private evidence hint: `private-ops://local-source/signal-gap-batch/sewer_water_level`
- Counties: 連江縣
- Requested counterparties:
  - 連江縣政府公開資料或防災水利窗口
- Required read API fields: `observed_at`, `station_or_device_id`, `measurement_value`, `measurement_unit_or_type`, `longitude_latitude_or_joinable_station_metadata`, `official_source_url_and_license`
- Production operational requirements: `freshness_policy`, `raw_snapshot_retention_policy`, `monitored_scheduler_cadence`, `hosted_egress_review`, `worker_persisted_evidence_path`
- Packet generator command: `PYTHONPATH=apps/api python scripts/local-source-request-packets.py --format markdown --signal-type sewer_water_level --county 連江縣`
- Completion gate: Each county must provide a latest-observation read API, an authorization-gated adapter path, or an official unavailable-source record for sewer_water_level, plus production ops evidence.
- Completion evidence targets:
  - signal_family_gap_evidence / sewer_water_level; accepted statuses: accepted, authorization_gated_adapter, official_unavailable, production_adapter; evidence_ref hint: private-ops://local-source/signal-gap/連江縣/sewer_water_level
