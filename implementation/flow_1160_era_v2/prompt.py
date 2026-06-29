"""Prompt construction for flow_1160_era_v2."""

from __future__ import annotations

from implementation.flow_1160_era.prompt import build_prompt as build_v1_prompt


V2_GUIDANCE = """

V2 IR additions available in dataset["fjspb"] and REQUIRED for this variant:
- Schema guardrail: precedence_pairs are list/tuple rows like [a, b], but
  branch_priority_pairs are dict rows. For every branch priority row, read
  pair["higher_task_id"] and pair["lower_task_id"] and add
  start[higher_task_id] <= start[lower_task_id]. Do not parse
  branch_priority_pairs as [higher, lower], and do not turn P1/P2/P3 priority
  into serial completion order or optional route selection.
- material_edges: normalized projectAllNodeList.materialData records with
  src_node_id/dst_node_id, src_task_id/dst_task_id, material/barcode fields,
  quantity, plate_oper_type, push_type, transfer_mode, and enforcement tags.
  You must read material_edges and add CP-SAT precedence for every row with
  hard_precedence_candidate=True and src_task_id/dst_task_id present. This is
  in addition to precedence_pairs, not a replacement. Do not invent quantity
  units; quantity conservation may remain audit/commented logic unless you can
  model it from explicit fields.
- material_inventory_events: conservative quantity-flow rows derived from
  material_edges that have explicit src_task_id, dst_task_id, and positive
  quantity. Group them by inventory_key. For each group, add a CP-SAT
  AddReservoirConstraint with +quantity at the source task end and -quantity at
  the destination task start, min_level=0, and max_level=sum(group quantities).
  This enforces temporal stock non-negativity from explicit platform quantities.
- material_lineage_links: plate lineage hints derived from material_edges.
  prePlateNums has been cross-checked against project 1160 data and the
  platform AI short answer as a source plate label, not a numeric list. Read
  this data for lineage/audit and to avoid losing plate identity context, but
  do not build arithmetic sum conservation from prePlateNums. quantityConsumeRule
  and plateOperType currently lack confirmed enum semantics, so do not infer
  consume/copy/transfer rules from those enum values alone.
- material_flow_groups: merge/split groups for audit and future conservation.
  Do not invent full merge/split production balance if the raw platform rows do
  not expose a clear total produced quantity; keep those as audit metadata until
  explicit fields exist.
- constraint_realization_boundaries: the source of truth for remaining real
  modeling boundaries. This is an interface/seed-controlled state, not a static
  hard-coded verdict. Read boundary["interface"] and boundary["state"] first.
  Only state.required_hard_constraints rows may be treated as mandatory CP-SAT
  hard constraints. state.audit_controls and state.blocked_controls are
  non-hard context. state.experimental_controls are reproducible
  seed-controlled exploration hints and still have hard_constraint=False unless
  explicit platform fields are present. Do not promote full_merge_split_balance,
  initial_material_stock, position_in_out_inventory, or plate_identity_no_overlap
  into hard constraints just because the profile is seeded_experimental.
- history_policy: the source of truth for historical runtime result visibility.
  The default is strict_cold_start, mirroring multi_bot_era's no-incumbent
  interface: candidate-visible IR must not expose or replay non-fixed runtime
  start/end result fields. Do not infer logistics durations from hidden
  historical startTime/endTime spans. historical_replay is only for explicit
  audit/replay runs, not for cold-start FUTS planning.
- logistics_events: non-main-task transport/scan/load/stack metadata. Treat
  rows with enforcement="audit_no_overlap_candidate", duration>0, and resources
  as real CP-SAT fixed-present logistics intervals. Add NoOverlap per logistics
  resource, connect predecessor_task_ids/successor_task_ids to the event
  interval, and include logistics event end variables in the modeled makespan
  so transport/stacking time can actually bind the objective. Logistics
  intervals are not returned in assignments. If a logistics event has
  buffer_ids, add that same fixed-present interval to each referenced buffer's
  capacity calendar as demand 1.
- In strict_cold_start, logistics events may have resources and buffer_ids but
  duration=0 with duration_source="missing_planning_duration_no_history". These
  rows preserve topology/resource/buffer context only. Do not replace the
  missing duration with a hidden runtime span, a guessed observed value, or a
  hard-coded constant. Add direct predecessor/successor precedence where
  applicable and keep the missing planning duration as a data requirement.
- logistics_events may also include enforcement="precedence_only" rows. These
  can add direct predecessor_task_ids -> successor_task_ids precedence when
  both sides are present, but they do not need resource intervals.
- buffers and logistics_resources: platform-derived resource definitions.
  buffers come from devicePosition counts; buffer["capacity"] is the platform
  capacity for that buffer/device. Build buffer_to_intervals from
  logistics_events[*].buffer_ids and add AddCumulative(intervals, [1...],
  capacity) per buffer. Use logistics_resources to group event intervals by
  resource and add AddNoOverlap per single-capacity logistics resource.
- rolling_state and task run_status/duration_source/actual_start/actual_end:
  support future rolling scheduling. In strict_cold_start, actual_start and
  actual_end are intentionally None for non-fixed historical rows. You must read rolling_state.cur_ptr and
  existing_machine_occupancy. Existing occupancy intervals must be inserted into
  machine cumulative calendars before AddCumulative is posted. In this offline
  benchmark, do not freeze all DONE historical tasks unless is_fixed=True.
- The returned assignments remain task-only. Do not return logistics_events as
  assignments, but do not omit their CP-SAT constraints from the model.
- If CP-SAT returns neither OPTIMAL nor FEASIBLE, return {"assignments": []}.
  Do not construct a greedy/list fallback assignment table from cur_ptr,
  first eligible machine, or task duration. Returning unverified assignments is
  not a real landed constraint model.

This is not optional documentation: a v2 candidate that ignores material_edges,
material_inventory_events, material_lineage_links,
constraint_realization_boundaries, history_policy, logistics_events, buffers, or rolling_state
is not a v2 solver. Preserve all v1 hard constraints, then add the explicit v2
constraints above. Never replay historical start/end times as the returned
schedule.
"""


def build_prompt(*args, **kwargs) -> str:
  base = build_v1_prompt(*args, **kwargs)
  marker = "\nParent candidate code:\n"
  if marker in base:
    return base.replace(marker, V2_GUIDANCE + marker)
  return base + V2_GUIDANCE
