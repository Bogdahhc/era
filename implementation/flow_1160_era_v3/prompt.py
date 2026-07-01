"""Prompt construction for flow_1160_era_v3."""

from __future__ import annotations

from implementation.flow_1160_era.prompt import build_prompt as build_v1_prompt


V3_GUIDANCE = """

V3 IR additions available in dataset["fjspb"] and REQUIRED for this variant:
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
  in addition to precedence_pairs, not a replacement. For these material
  transfers, the planning constraint must reserve logistics time. Prefer
  dataset["fjspb"]["device_transfer_times"] as a selected-machine-pair matrix:
  for every src_machine/dst_machine choice pair, add a conditional CP-SAT
  constraint OnlyEnforceIf([src_machine_chosen, dst_machine_chosen]) with
  start[dst_task_id] >= end[src_task_id] + max(src_task.min_wait,
  pair.transfer_seconds). Use isaac_motion_timing["transfer_seconds"] only as
  a fallback if a pair is missing. Do not leave material transfer as zero-time
  teleportation. Do not invent quantity units; quantity conservation may remain
  audit/commented logic unless you can model it from explicit fields.
- material_inventory_events: conservative quantity-flow rows derived from
  material_edges that have explicit src_task_id, dst_task_id, and positive
  quantity. Group them by inventory_key. For each group, add a CP-SAT
  AddReservoirConstraint with +quantity at the source task end and -quantity at
  the destination task start, min_level=0, and max_level=sum(group quantities).
  This enforces temporal stock non-negativity from explicit platform quantities.
- material_conservation_model: machine-readable realism boundary for material
  conservation. Read it before modeling quantities. Its hard_ready section
  currently permits only edge_inventory_nonnegative via material_inventory_events.
  initial_stock_candidates, merge_split_quantity_audit, plate labels,
  plateOperType, pushType, and quantityConsumeRule are audit-only unless the
  platform exports stable stock_item_id, explicit initial quantity/position,
  and consume/copy/split rules. Do not promote blocked_full_hard_constraints to
  hard constraints.
- platform_realism_sources: direct platform endpoint evidence fetched alongside
  the project cache, including deviceMaterial initial load candidates,
  materialSetting/barcodeSetting catalogs, devicePosition plateBarcode
  occupancy candidates, all_nodes apsLoadingTime/apsUnloadingTime fields,
  deviceRunning state, and dispatch queue state. Read endpoint_counts,
  device_material_loads, aps_loading_time_candidates, and
  blocked_hard_constraints before changing duration or stock modeling. These
  sources currently have no hard_ready rows. Do not add apsLoadingTime to task
  duration until its unit and whether task duration already includes it are
  validated. Do not turn deviceMaterial counts into initial stock constraints
  without stable stock_item_id, explicit quantity, and initial position binding.
  platform_realism_sources.self_filled_assumption_profiles records explicit
  fallback assumptions after platform AI failed to provide verifiable field
  semantics. Treat these as experiment proposals, not default hard constraints:
  cite the profile name if you use one, keep hard_ready_default=false profiles
  non-hard unless the boundary/profile explicitly promotes them, and report the
  expected makespan direction.
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
- isaac_motion_timing: conservative synthetic planning parameters for the
  pick/move/place/drop/safety transfer model. This is candidate-visible by
  design and is not derived from historical runtime spans. You must read
  isaac_motion_timing["transfer_seconds"] as the fallback transfer gap, so the
  generated schedule already includes logistics time before Isaac/headless
  monitoring.
- device_transfer_times: graph-distance/motion-class matrix for
  source/destination machine pairs. Same-device or nearby transfers use
  rotation/short move durations; distant transfers use a shortest-path graph
  distance on the synthetic layout and linear move duration. This is a
  synthetic cold-start planning model, not historical replay. Do not replace it
  with a single global cap or hard-coded constant; use it conditionally with
  machine assignment literals when adding material_edges transfer gaps.
- buffers and logistics_resources: platform-derived resource definitions.
  buffers come from devicePosition counts; buffer["capacity"] is the platform
  capacity for that buffer/device. Build buffer_to_intervals from
  logistics_events[*].buffer_ids and add AddCumulative(intervals, [1...],
  capacity) per buffer. Use logistics_resources to group event intervals by
  resource and add AddNoOverlap per single-capacity logistics resource.

- device_commands: v3 command-level IR. Read every command row with command_id,
  task_id, kind, resource_ids, duration, duration_source, predecessor_command_ids,
  predecessor_task_ids, successor_task_ids, from_position_id, to_position_id,
  plate_id, and effects. Build command interval variables for device_run commands
  and for logistics commands that have explicit positive duration/resources. Bind
  each device_run command to its task start/end. Preserve zero-duration logistics
  topology as precedence only in strict_cold_start.
- positions, plate_states, robot_resources, command_templates, and
  command_realization_boundaries: these are the v3 boundary source for physical
  command modeling. Add robot/resource NoOverlap and position capacity calendars
  only when command_realization_boundaries marks the needed fields hard-ready.
  Do not invent from/to positions, stable plate identity, pick/place durations,
  movement matrices, or online replan state from historical spans or constants.
- Return both {"assignments": [...], "command_assignments": [...]}. The
  task-level assignments remain compatible with the v1 scorer. command_assignments
  must include at least every cmd:task:<task_id>:run device_run command with
  command_id, start, end, resource_id, task_id, kind, and duration_source. Include
  logistics command rows only when they are actually modeled as command intervals
  or precedence events. A task-only v3 result is rejected.
- Scoring includes an Isaac-motion penalty as a backstop. The executor expands
  material_edges into conservative pick/move/place/drop robot actions and
  subtracts score for late transfers, robot/device/plate collisions, and
  deadlocks. If your solver runs an external Isaac Sim pass, return an optional
  isaac_conflicts list with task_id/src_task_id/dst_task_id/task_ids fields;
  each external Isaac conflict is also penalized. The primary requirement is to
  include device_transfer_times during CP-SAT generation so logistics time is
  part of the produced schedule, not only an after-the-fact penalty.
- FUTS adaptive Isaac feedback: when feedback_context contains
  recent_isaac_logistics_processes, treat it as concrete evidence from the
  previous simulated logistics process. Before changing transfer-gap handling,
  machine-choice heuristics, or path preferences, inspect and use specific rows
  from tightest_transfers, late_transfers, longest_transfers,
  busiest_device_pairs, conflict_task_ids, first_conflict, or first_deadlock.
  Any change intended to shorten time must be grounded in a named task pair,
  device pair, transfer_id/edge_id, slack value, or Isaac conflict/deadlock from
  that context. Do not blindly try smaller gaps, random machine swaps, or
  hard-coded device preferences without a cited process reason.
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

This is not optional documentation: a v3 candidate that ignores material_edges,
material_inventory_events, material_conservation_model,
platform_realism_sources, material_lineage_links,
constraint_realization_boundaries, history_policy, logistics_events, buffers, isaac_motion_timing, device_transfer_times, rolling_state,
device_commands, positions, plate_states, robot_resources, command_templates,
command_realization_boundaries, or command_assignments is not a v3 solver. Preserve all v1 hard constraints, then add the explicit v3
constraints above. Never replay historical start/end times as the returned
schedule.
"""


def build_prompt(*args, **kwargs) -> str:
  base = build_v1_prompt(*args, **kwargs)
  marker = "\nParent candidate code:\n"
  if marker in base:
    return base.replace(marker, V3_GUIDANCE + marker)
  return base + V3_GUIDANCE
