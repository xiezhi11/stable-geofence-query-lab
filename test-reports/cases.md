# Case Replay Report

| Sample | Input version | Clock | Cleanup | Pollution source |
| --- | --- | --- | --- | --- |
| test_overlap_priority_then_version | 3 | 2026-01-01T00:00:00Z | verified_clean | - |
| test_event_time_selects_different_versions_and_ignores_server_time | 2 | 2026-12-31T00:00:00Z | verified_clean | - |
| test_failed_zone_update_is_atomic | 2 | 2026-01-01T00:00:00Z | verified_clean | - |
| test_fixed_clock_batch_pagination_and_restart | 1 | 2026-01-01T00:00:00Z | verified_clean | - |
| test_pagination_filters_total_and_next_page_are_consistent | 2 | 2026-01-01T00:00:00Z | verified_clean | - |
| test_sqlite_fixture_persists_confirmed_result_and_can_reset | 1 | 2026-01-01T00:00:00Z | verified_clean | - |
| test_batch_preserves_order_and_keeps_valid_results_after_failure | 2 | 2026-01-01T00:00:00Z | verified_clean | - |
| test_nonexistent_zone_reference_and_expired_version_have_distinct_codes | 2 | 2026-01-01T00:00:00Z | verified_clean | - |
| test_revoked_zone_keeps_history_but_rejects_new_events | 3 | 2026-01-01T00:00:00Z | verified_clean | - |
| test_validation_error_paths_are_stable[payload0-latitude] | 2 | 2026-01-01T00:00:00Z | verified_clean | - |
| test_validation_error_paths_are_stable[payload3-zone_version] | 2 | 2026-01-01T00:00:00Z | verified_clean | - |
| test_validation_error_paths_are_stable[payload4-event_id] | 2 | 2026-01-01T00:00:00Z | verified_clean | - |
| test_validation_error_paths_are_stable[payload1-longitude] | 2 | 2026-01-01T00:00:00Z | verified_clean | - |
| test_late_cross_day_event_accepted_after_end_but_closed_after_late_until | 1 | 2026-01-02T04:00:00Z | verified_clean | - |
| test_restart_preserves_confirmed_match_without_timezone_dependence | 2 | 2026-01-01T00:00:00Z | verified_clean | - |
| test_http_error_contract_has_stable_code_and_no_stack_path | 1 | 2026-01-01T00:00:00Z | verified_clean | - |
| test_concurrent_page_reads_do_not_duplicate_or_skip | 2 | 2026-01-01T00:00:00Z | verified_clean | - |
| test_boundary_circle_and_polygon_are_included | 2 | 2026-01-01T00:00:00Z | verified_clean | - |
| test_reset_interface_clears_zones_events_windows_and_clock | 1 | 2026-09-21T04:41:34.210988Z | verified_clean | - |
| test_duplicate_returns_first_confirmation_even_if_later_submission_closed | 2 | 2026-01-04T00:00:00Z | verified_clean | - |
| test_validation_error_paths_are_stable[payload2-timestamp] | 2 | 2026-01-01T00:00:00Z | verified_clean | - |
| test_batch_uses_starting_snapshot_when_zones_change_during_processing | 3 | 2026-01-01T00:00:00Z | verified_clean | - |
| test_pagination_is_stable_when_new_events_are_inserted | 2 | 2026-01-01T00:00:00Z | verified_clean | - |
