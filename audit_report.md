# Radius Python Backend Audit Report

## File: d:\Radius\apps\api\src\app\auth.py
- **Functions Implemented**: should_auto_verify_email, hash_password, verify_password, create_session, decode_session, create_action_token, consume_action_token, provision_domain_user_and_org, user_from_provider
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API, Database (SQLAlchemy)

## File: d:\Radius\apps\api\src\app\config.py
- **Classes Implemented**: Settings
- **Functions Implemented**: get_settings
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API

## File: d:\Radius\apps\api\src\app\database.py
- **Classes Implemented**: Base
- **Functions Implemented**: get_db
- **Stubs/Placeholders**: Class: Base
- **TODOs**: None
- **Integrations Mentioned**: Database (SQLAlchemy)

## File: d:\Radius\apps\api\src\app\main.py
- **Functions Implemented**: initialize_database
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\apps\api\src\app\models.py
- **Classes Implemented**: User, AuthAccount, AuthToken, AuthSession
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: Database (SQLAlchemy)

## File: d:\Radius\apps\api\src\app\routes_auth.py
- **Functions Implemented**: send_email_message, public_user, set_session, current_user, signup, login, logout, me, refresh, forgot_password, reset_password, verify_email, resend_verification, oauth_config, oauth_start, oauth_callback
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API, Database (SQLAlchemy)

## File: d:\Radius\apps\api\src\app\schemas.py
- **Classes Implemented**: Credentials, Signup, Login, ForgotPassword, ResetPassword, VerifyToken, UserResponse
- **Functions Implemented**: password_strength, password_strength
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\apps\api\src\radius_api\auth.py
- **Classes Implemented**: ApiPrincipal
- **Functions Implemented**: _configured_api_keys, get_api_principal, ensure_same_organization
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\apps\api\src\radius_api\config.py
- **Classes Implemented**: ApiSettings
- **Functions Implemented**: get_api_settings
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API

## File: d:\Radius\apps\api\src\radius_api\dependencies.py
- **Classes Implemented**: AppContainer
- **Functions Implemented**: get_container, configure_sql_storage, _new_session, _acquire_request_session, _release_request_session, get_repository_service, get_analysis_service, get_testing_service, get_confidence_service, get_graph_store, get_idempotency_store, repository_service, analysis_service, testing_service, confidence_service
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: Database (SQLAlchemy)

## File: d:\Radius\apps\api\src\radius_api\idempotency.py
- **Classes Implemented**: IdempotencyRecord, IdempotencyStore, InMemoryIdempotencyStore, SqlAlchemyIdempotencyStore
- **Functions Implemented**: request_hash, replay_or_validate, get, save, __init__, get, save, __init__, get, save, _to_record
- **Stubs/Placeholders**: Function: get, Function: save
- **TODOs**: None
- **Integrations Mentioned**: Database (SQLAlchemy)

## File: d:\Radius\apps\api\src\radius_api\main.py
- **Functions Implemented**: radius_error_handler, create_app, initialize_auth_database
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API

## File: d:\Radius\apps\api\src\radius_api\seed.py
- **Functions Implemented**: seed_demo_user, _populate_stores, _seed_sql_database, seed_open_source_results
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API, Database (SQLAlchemy)

## File: d:\Radius\apps\api\src\radius_api\routes\analyses.py
- **Functions Implemented**: start_analysis, list_analyses, get_analysis, rerun_analysis, get_blast_radius
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\apps\api\src\radius_api\routes\confidence.py
- **Functions Implemented**: get_confidence
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\apps\api\src\radius_api\routes\github_webhooks.py
- **Functions Implemented**: handle_github_webhook, _handle_payload, _handle_installation_sync, _handle_push, _handle_pull_request, _connect_repository, _validate_signature, _webhook_organization_id, _pull_request_status, _record_installation_id
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API

## File: d:\Radius\apps\api\src\radius_api\routes\graph.py
- **Functions Implemented**: get_graph, get_graph_nodes, get_graph_edges, _ensure_analysis_access
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\apps\api\src\radius_api\routes\health.py
- **Classes Implemented**: HealthResponse
- **Functions Implemented**: get_health, get_readiness
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: Database (SQLAlchemy)

## File: d:\Radius\apps\api\src\radius_api\routes\repositories.py
- **Functions Implemented**: connect_repository, list_repositories, get_repository, disconnect_repository
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API

## File: d:\Radius\apps\api\src\radius_api\routes\tests.py
- **Functions Implemented**: get_selected_tests, ingest_test_results, get_test_run_result
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Test utility or setup file (no direct test cases found).

## File: d:\Radius\apps\api\src\radius_api\schemas\analyses.py
- **Classes Implemented**: StartAnalysisRequest
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\apps\api\src\radius_api\schemas\github_webhooks.py
- **Classes Implemented**: GitHubUserPayload, GitHubRepositoryPayload, GitHubPullRequestBranchPayload, GitHubPullRequestPayload, GitHubWebhookResult
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API

## File: d:\Radius\apps\api\src\radius_api\schemas\repositories.py
- **Classes Implemented**: ConnectRepositoryRequest
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API

## File: d:\Radius\apps\api\tests\conftest.py
- **Functions Implemented**: clear_api_settings_cache
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Test utility or setup file (no direct test cases found).

## File: d:\Radius\apps\api\tests\test_analyses.py
- **Functions Implemented**: test_analysis_endpoints_start_list_get_and_rerun, test_missing_blast_radius_returns_not_found_envelope, test_start_analysis_replays_idempotent_response
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API
- **Test Status**: Contains test cases.

## File: d:\Radius\apps\api\tests\test_auth_dev_experience.py
- **Functions Implemented**: test_db_engine, test_db, test_client, test_create_action_token_logs_verification_url, test_create_action_token_logs_reset_password_url, test_signup_endpoint_logs_dev_token, test_forgot_password_endpoint_logs_dev_token, test_should_auto_verify_email_resolution, test_signup_auto_verify_disabled_by_default, test_signup_auto_verify_enabled_with_env_flag, test_signup_auto_verify_enabled_with_radius_env, test_signup_provisions_domain_organization_and_user, test_domain_org_provisioning_usable_for_repositories, test_user_from_provider_provisions_domain_models, override_get_db
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API, Database (SQLAlchemy)
- **Test Status**: Contains test cases.

## File: d:\Radius\apps\api\tests\test_github_webhooks.py
- **Functions Implemented**: test_pull_request_webhook_creates_analysis_and_replays_delivery, test_github_webhook_rejects_invalid_signature, _webhook_body, _github_headers
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API
- **Test Status**: Contains test cases.

## File: d:\Radius\apps\api\tests\test_health.py
- **Functions Implemented**: test_health_endpoint_returns_service_metadata, test_readiness_endpoint_returns_ok_for_memory_storage, test_api_allows_dashboard_cors_preflight
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Contains test cases.

## File: d:\Radius\apps\api\tests\test_idempotency.py
- **Functions Implemented**: test_sqlalchemy_idempotency_store_saves_and_reads_response
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: Database (SQLAlchemy)
- **Test Status**: Contains test cases.

## File: d:\Radius\apps\api\tests\test_phase1_artifacts.py
- **Functions Implemented**: test_phase1_artifact_endpoints_return_graph_tests_and_confidence, test_missing_graph_artifact_uses_not_found_envelope
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API
- **Test Status**: Contains test cases.

## File: d:\Radius\apps\api\tests\test_repositories.py
- **Functions Implemented**: test_repository_endpoints_connect_list_get_and_disconnect, test_repository_not_found_uses_error_envelope, test_repository_requires_auth_context, test_connect_repository_replays_idempotent_response
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API
- **Test Status**: Contains test cases.

## File: d:\Radius\apps\api\tests\test_test_results_ingestion.py
- **Functions Implemented**: _setup_analysis, test_ingest_junit_xml_successful, test_ingest_junit_xml_with_failures_reduces_confidence, test_ingest_json_results, test_ingest_test_results_organization_authorization, test_get_test_run_results_endpoint
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API
- **Test Status**: Contains test cases.

## File: d:\Radius\apps\api\tests\test_test_selection_api.py
- **Functions Implemented**: _create_test_case, _setup_analysis, test_get_selected_tests_json_returns_optimization_metrics, test_get_selected_tests_cli_format_returns_plaintext, test_get_selected_tests_cli_format_empty_selection
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API
- **Test Status**: Contains test cases.

## File: d:\Radius\apps\api\tests\__init__.py
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Test utility or setup file (no direct test cases found).

## File: d:\Radius\apps\worker\src\radius_worker\config.py
- **Classes Implemented**: WorkerSettings
- **Functions Implemented**: _parse_installation_id
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API

## File: d:\Radius\apps\worker\src\radius_worker\orchestrator.py
- **Classes Implemented**: ExecuteAnalysisCommand, AnalysisExecutionResult, Phase1AnalysisOrchestrator
- **Functions Implemented**: __init__, execute, _execute, _run_semantic_cpg_poc, _analyze_changes, _require_graph_snapshot, _affected_file_paths
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: Gemini AI

## File: d:\Radius\apps\worker\src\radius_worker\queue.py
- **Classes Implemented**: InMemoryAnalysisQueue
- **Functions Implemented**: __init__, enqueue, claim_next, __len__
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\apps\worker\src\radius_worker\runner.py
- **Classes Implemented**: SqlAlchemyWorkerRuntime
- **Functions Implemented**: run_worker, create_sql_worker_runtime, run_worker_once, run_worker_loop, create_local_orchestrator, load_persisted_analysis_command, _create_sql_orchestrator, _repository_cache_path, _safe_path_segment, _github_settings, _github_clone_headers, _publish_github_result, _github_installation_id, _github_report, run_once, run_loop, _claim_job, _queue
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API, Database (SQLAlchemy)

## File: d:\Radius\apps\worker\tests\test_cpg_multilang_orchestrator.py
- **Functions Implemented**: _create_test_repository, _create_orchestrator, test_multilang_cpg_nodes_extracted_and_slices_computed, test_multilang_cpg_prunes_benign_callers_with_ai, test_diff_hunk_precision_only_slices_modified_symbol, spy_extract_caller_slice
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: Gemini AI
- **Mocking**: Detected use of mocking (likely mock integrations)
- **Test Status**: Contains test cases.

## File: d:\Radius\apps\worker\tests\test_orchestrator.py
- **Functions Implemented**: test_phase1_orchestrator_executes_backend_spine, test_in_memory_analysis_queue_claims_each_analysis_once, _write_repository
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Contains test cases.

## File: d:\Radius\apps\worker\tests\test_persisted_webhook_flow.py
- **Functions Implemented**: test_signed_webhook_runs_through_sql_worker_to_confidence, _create_database, _webhook_body, _github_headers, _create_git_repository, _write_repository, _git
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API, Database (SQLAlchemy)
- **Test Status**: Contains test cases.

## File: d:\Radius\apps\worker\tests\test_runner.py
- **Classes Implemented**: FakeJob, FakeQueue, FakeOrchestrator, FakeRuntime, FakeGitClient, RealGitClient, DisabledGitHubClient, Token, TokenGitHubClient, PublishingGitHubClient
- **Functions Implemented**: test_run_worker_reports_ready, test_run_worker_once_claims_executes_and_completes_job, test_run_worker_once_marks_job_failed_on_error, test_load_persisted_analysis_command_prepares_repository_checkout, test_load_persisted_analysis_command_passes_clone_headers, test_github_clone_headers_use_stored_installation_id, test_publish_github_result_builds_report_from_persisted_confidence, test_sqlalchemy_worker_runtime_executes_persisted_job, _session_factory, _persist_analysis_context, _create_git_repository, _write_repository, _git, __init__, __init__, claim_next, complete, fail, __init__, execute, __init__, run_loop, __init__, clone_or_fetch, checkout, clone_or_fetch, checkout, create_installation_token, __init__, __init__, create_installation_token, __init__, list_check_runs_for_ref, create_check_run, list_issue_comments, create_issue_comment
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API, Database (SQLAlchemy)
- **Test Status**: Contains test cases.

## File: d:\Radius\apps\worker\tests\__init__.py
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Test utility or setup file (no direct test cases found).

## File: d:\Radius\packages\analysis\src\radius_analysis\diff_hunks.py
- **Functions Implemented**: _normalize_path, parse_diff_modified_lines
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\analysis\src\radius_analysis\ai\pruner.py
- **Classes Implemented**: SemanticPruner
- **Functions Implemented**: __init__, evaluate_impact
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: Gemini AI

## File: d:\Radius\packages\analysis\src\radius_analysis\application\services.py
- **Classes Implemented**: AnalysisApplicationService
- **Functions Implemented**: __init__, start_analysis, rerun_analysis, get_analysis, list_analyses, mark_running, complete_analysis, fail_analysis, cancel_analysis, record_changed_files, analyze_diff, analyze_repository_diff, save_blast_radius, get_blast_radius, compute_blast_radius, _get_required, _parse_status, _parse_change_type, _traverse_reverse_dependencies, _normalize_graph_path, _count_symbols_for_files, _count_modules_for_files, _collect_reverse_dependency
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\analysis\src\radius_analysis\domain\entities.py
- **Classes Implemented**: ChangedFile, BlastRadius, Analysis
- **Functions Implemented**: __post_init__, __post_init__, mark_running, complete, fail, cancel
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\analysis\src\radius_analysis\domain\enums.py
- **Classes Implemented**: AnalysisStatus, ChangedFileType
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\analysis\src\radius_analysis\domain\events.py
- **Classes Implemented**: AnalysisStarted, AnalysisCompleted, AnalysisFailed
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\analysis\src\radius_analysis\domain\value_objects.py
- **Classes Implemented**: CommitSha, FilePath
- **Functions Implemented**: __post_init__, __post_init__
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\analysis\src\radius_analysis\dto\commands.py
- **Classes Implemented**: StartAnalysisCommand, RerunAnalysisCommand, AnalysisListQuery, ChangedFileInput, RecordChangedFilesCommand, SaveBlastRadiusCommand, AnalyzeDiffCommand, AnalyzeRepositoryDiffCommand, ComputeBlastRadiusCommand
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\analysis\src\radius_analysis\dto\responses.py
- **Classes Implemented**: ChangedFileResponse, ChangeAnalysisResponse, AnalysisResponse, BlastRadiusResponse, AnalysisDetailResponse
- **Functions Implemented**: from_entity, from_entity, from_entity, from_entity
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\analysis\src\radius_analysis\infrastructure\git_diff_provider.py
- **Classes Implemented**: SubprocessGitDiffProvider
- **Functions Implemented**: get_diff
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\analysis\src\radius_analysis\infrastructure\in_memory.py
- **Classes Implemented**: InMemoryAnalysisStore
- **Functions Implemented**: __init__, get_by_id, list, save, update_status, replace_changed_files, save_blast_radius, get_blast_radius
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\analysis\src\radius_analysis\infrastructure\sqlalchemy_job_queue.py
- **Classes Implemented**: AnalysisJob, SqlAlchemyAnalysisJobQueue
- **Functions Implemented**: __init__, enqueue, claim_next, complete, fail, requeue, recover_stale_jobs, get_by_analysis_id, _require_job, _to_dto
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: Database (SQLAlchemy)

## File: d:\Radius\packages\analysis\src\radius_analysis\infrastructure\sqlalchemy_store.py
- **Classes Implemented**: SqlAlchemyAnalysisStore
- **Functions Implemented**: __init__, get_by_id, list, save, update_status, replace_changed_files, save_blast_radius, get_blast_radius, _analysis_query, _require_analysis, _to_domain, _changed_file_to_domain, _blast_radius_to_domain
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: Database (SQLAlchemy)

## File: d:\Radius\packages\analysis\src\radius_analysis\infrastructure\unified_diff_change_analyzer.py
- **Classes Implemented**: _FileChange, UnifiedDiffChangeAnalyzer
- **Functions Implemented**: analyze_diff, _start_change, _normalize_path, _merge
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\analysis\src\radius_analysis\infrastructure\__init__.py
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: Database (SQLAlchemy)

## File: d:\Radius\packages\analysis\src\radius_analysis\interfaces\analysis_store.py
- **Classes Implemented**: AnalysisStore
- **Functions Implemented**: get_by_id, list, save, update_status, replace_changed_files, save_blast_radius, get_blast_radius
- **Stubs/Placeholders**: Function: get_by_id, Function: list, Function: save, Function: update_status, Function: replace_changed_files, Function: save_blast_radius, Function: get_blast_radius
- **TODOs**: None

## File: d:\Radius\packages\analysis\src\radius_analysis\interfaces\change_analyzer.py
- **Classes Implemented**: GitChangeAnalyzer, GitDiffProvider
- **Functions Implemented**: analyze_diff, get_diff
- **Stubs/Placeholders**: Function: analyze_diff, Function: get_diff
- **TODOs**: None

## File: d:\Radius\packages\analysis\src\radius_analysis\interfaces\pipeline.py
- **Classes Implemented**: AnalysisPipeline
- **Functions Implemented**: enqueue
- **Stubs/Placeholders**: Function: enqueue
- **TODOs**: None

## File: d:\Radius\packages\confidence\src\radius_confidence\application\services.py
- **Classes Implemented**: ConfidenceApplicationService
- **Functions Implemented**: __init__, generate_report, get_report, recalculate_from_test_results, _risk_level, _recommendations
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\confidence\src\radius_confidence\domain\entities.py
- **Classes Implemented**: ImpactEvidence, TestEvidence, ConfidenceEvidence, ConfidenceReport
- **Functions Implemented**: __post_init__, __post_init__
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\confidence\src\radius_confidence\domain\enums.py
- **Classes Implemented**: RiskLevel, EvidenceCategory, EvidenceImpact
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\confidence\src\radius_confidence\domain\value_objects.py
- **Classes Implemented**: ConfidenceScore, CoveragePercent
- **Functions Implemented**: __post_init__, __post_init__
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\confidence\src\radius_confidence\dto\commands.py
- **Classes Implemented**: GenerateConfidenceReportCommand
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\confidence\src\radius_confidence\dto\responses.py
- **Classes Implemented**: ConfidenceEvidenceResponse, ConfidenceReportResponse
- **Functions Implemented**: from_entity, from_entity
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\confidence\src\radius_confidence\infrastructure\in_memory.py
- **Classes Implemented**: InMemoryConfidenceStore
- **Functions Implemented**: __init__, save_report, get_by_analysis_id
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\confidence\src\radius_confidence\infrastructure\scoring.py
- **Classes Implemented**: DeterministicConfidenceScorer
- **Functions Implemented**: score, _apply_test_penalties, _apply_coverage_penalties, _apply_impact_penalties, _negative
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\confidence\src\radius_confidence\infrastructure\sqlalchemy_store.py
- **Classes Implemented**: SqlAlchemyConfidenceStore
- **Functions Implemented**: __init__, save_report, get_by_analysis_id
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: Database (SQLAlchemy)

## File: d:\Radius\packages\confidence\src\radius_confidence\infrastructure\__init__.py
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: Database (SQLAlchemy)

## File: d:\Radius\packages\confidence\src\radius_confidence\interfaces\scoring.py
- **Classes Implemented**: ConfidenceScorer
- **Functions Implemented**: score
- **Stubs/Placeholders**: Function: score
- **TODOs**: None

## File: d:\Radius\packages\confidence\src\radius_confidence\interfaces\store.py
- **Classes Implemented**: ConfidenceStore
- **Functions Implemented**: save_report, get_by_analysis_id
- **Stubs/Placeholders**: Function: save_report, Function: get_by_analysis_id
- **TODOs**: None

## File: d:\Radius\packages\github\src\radius_github\client.py
- **Classes Implemented**: GitHubAppSettings, InstallationToken, GitHubAppClient
- **Functions Implemented**: _check_run_payload, enabled, __init__, create_installation_token, create_check_run, update_check_run, list_check_runs_for_ref, create_issue_comment, update_issue_comment, list_issue_comments, _jwt, _request
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API

## File: d:\Radius\packages\github\src\radius_github\publisher.py
- **Classes Implemented**: GitHubAnalysisReport, GitHubAnalysisPublisher
- **Functions Implemented**: _risk_badge, _check_conclusion, _markdown_report, _latest_check_run, _existing_radius_comment, __init__, publish_in_progress, publish
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API

## File: d:\Radius\packages\github\src\radius_github\__init__.py
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API

## File: d:\Radius\packages\graph\src\radius_graph\cpg.py
- **Classes Implemented**: CodePropertyGraph
- **Functions Implemented**: _file_matches_module, __init__, add_import, add_symbol, _resolve_reference, add_reference
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\graph\src\radius_graph\models.py
- **Classes Implemented**: Node
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\graph\src\radius_graph\slicer.py
- **Classes Implemented**: GraphSlicer
- **Functions Implemented**: __init__, extract_caller_slice
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\graph\src\radius_graph\application\services.py
- **Classes Implemented**: GraphApplicationService
- **Functions Implemented**: __init__, build_graph, _add_parsed_file, file_node_id, symbol_node_id, import_node_id, export_node_id, module_node_id, _edge_sort_key
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\graph\src\radius_graph\domain\entities.py
- **Classes Implemented**: GraphNode, GraphEdge, DependencyGraph, GraphSnapshot
- **Functions Implemented**: __post_init__, __post_init__, node_ids, reverse_dependencies, node_count, edge_count
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\graph\src\radius_graph\domain\enums.py
- **Classes Implemented**: GraphNodeType, GraphEdgeType
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\graph\src\radius_graph\domain\value_objects.py
- **Classes Implemented**: GraphNodeId, GraphVersion
- **Functions Implemented**: __post_init__, __post_init__
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\graph\src\radius_graph\dto\commands.py
- **Classes Implemented**: BuildGraphCommand
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\graph\src\radius_graph\dto\responses.py
- **Classes Implemented**: GraphNodeResponse, GraphEdgeResponse, GraphSnapshotResponse
- **Functions Implemented**: from_entity, from_entity, from_entity
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\graph\src\radius_graph\infrastructure\in_memory.py
- **Classes Implemented**: InMemoryGraphStore, InMemoryGraphTraversal
- **Functions Implemented**: __init__, save_snapshot, get_snapshot, __init__, reverse_dependencies
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\graph\src\radius_graph\infrastructure\module_resolver.py
- **Classes Implemented**: ModuleResolver
- **Functions Implemented**: __init__, resolve, _build_index, _candidates, _relative_python_candidates, _relative_path_candidates, _put, _normalize_path, _normalize_source
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\graph\src\radius_graph\infrastructure\sqlalchemy_store.py
- **Classes Implemented**: SqlAlchemyGraphStore
- **Functions Implemented**: __init__, save_snapshot, get_snapshot
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: Database (SQLAlchemy)

## File: d:\Radius\packages\graph\src\radius_graph\infrastructure\__init__.py
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: Database (SQLAlchemy)

## File: d:\Radius\packages\graph\src\radius_graph\interfaces\graph_store.py
- **Classes Implemented**: GraphStore
- **Functions Implemented**: save_snapshot, get_snapshot
- **Stubs/Placeholders**: Function: save_snapshot, Function: get_snapshot
- **TODOs**: None

## File: d:\Radius\packages\graph\src\radius_graph\interfaces\traversal.py
- **Classes Implemented**: GraphTraversal
- **Functions Implemented**: reverse_dependencies
- **Stubs/Placeholders**: Function: reverse_dependencies
- **TODOs**: None

## File: d:\Radius\packages\parser\src\radius_parser\core.py
- **Classes Implemented**: ParserEngine
- **Functions Implemented**: __init__, parse_python, parse_typescript
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\parser\src\radius_parser\models.py
- **Classes Implemented**: Symbol, Reference, Import
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\parser\src\radius_parser\application\services.py
- **Classes Implemented**: ParserApplicationService
- **Functions Implemented**: __init__, parse_repository, parse_repository_result, _filter_changed_paths
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\parser\src\radius_parser\domain\entities.py
- **Classes Implemented**: SourceFile, Symbol, ImportReference, ExportReference, ParsedSourceFile, RepositoryParseResult
- **Functions Implemented**: __post_init__, __post_init__, file_count, symbol_count
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\parser\src\radius_parser\domain\enums.py
- **Classes Implemented**: SourceLanguage, SymbolType, SymbolVisibility
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\parser\src\radius_parser\domain\value_objects.py
- **Classes Implemented**: SourcePath, FileChecksum, SymbolName, SourceLocation
- **Functions Implemented**: __post_init__, __post_init__, __post_init__, __post_init__
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\parser\src\radius_parser\dto\commands.py
- **Classes Implemented**: ParseRepositoryCommand
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\parser\src\radius_parser\dto\responses.py
- **Classes Implemented**: SourceFileResponse, ParsedSourceFileResponse, RepositoryParseResponse
- **Functions Implemented**: from_entity, from_entity
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\parser\src\radius_parser\extractors\python.py
- **Classes Implemented**: PythonExtractor
- **Functions Implemented**: extract_symbols, extract_calls, extract_imports, traverse, traverse, traverse
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\parser\src\radius_parser\extractors\typescript.py
- **Classes Implemented**: TypeScriptExtractor
- **Functions Implemented**: extract_symbols, extract_calls, extract_imports, traverse, traverse, traverse
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\parser\src\radius_parser\infrastructure\ecmascript_parser.py
- **Classes Implemented**: TypeScriptLikeParser, JavaScriptParser, TypeScriptParser
- **Functions Implemented**: __init__, parse, _read_source, _symbol_from_line, _exports_from_line, __init__, __init__
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\parser\src\radius_parser\infrastructure\filesystem_discovery.py
- **Classes Implemented**: FilesystemSourceDiscovery
- **Functions Implemented**: discover, _is_ignored, _checksum
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\parser\src\radius_parser\infrastructure\parser_registry.py
- **Classes Implemented**: StaticLanguageParserRegistry
- **Functions Implemented**: default_language_parser_registry, __init__, get_parser
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\parser\src\radius_parser\infrastructure\python_parser.py
- **Classes Implemented**: PythonAstParser
- **Functions Implemented**: parse, _read_source, _import_references, _from_import_reference, _method_symbols, _symbol, _location, _explicit_exports, _public_symbol_names, _symbol_location_by_name
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\parser\src\radius_parser\interfaces\discovery.py
- **Classes Implemented**: SourceDiscovery
- **Functions Implemented**: discover
- **Stubs/Placeholders**: Function: discover
- **TODOs**: None

## File: d:\Radius\packages\parser\src\radius_parser\interfaces\language_parser.py
- **Classes Implemented**: LanguageParser, LanguageParserRegistry
- **Functions Implemented**: parse, get_parser
- **Stubs/Placeholders**: Function: parse, Function: get_parser
- **TODOs**: None

## File: d:\Radius\packages\repository\src\radius_repository\application\services.py
- **Classes Implemented**: RepositoryApplicationService
- **Functions Implemented**: __init__, connect_repository, get_repository, list_repositories, disconnect_repository, upsert_branch, upsert_pull_request, get_pull_request_by_repository_and_number, _parse_status, _parse_visibility, _parse_pull_request_status
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API

## File: d:\Radius\packages\repository\src\radius_repository\domain\entities.py
- **Classes Implemented**: Commit, Branch, Repository, PullRequest
- **Functions Implemented**: disconnect, full_name
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API

## File: d:\Radius\packages\repository\src\radius_repository\domain\enums.py
- **Classes Implemented**: RepositoryProvider, RepositoryVisibility, RepositoryStatus, PullRequestStatus
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API

## File: d:\Radius\packages\repository\src\radius_repository\domain\events.py
- **Classes Implemented**: RepositoryConnected, RepositoryUpdated, RepositorySynchronizationStarted
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\repository\src\radius_repository\domain\value_objects.py
- **Classes Implemented**: RepositoryId, OrganizationId, BranchName, CommitHash, RepositoryFullName
- **Functions Implemented**: __post_init__, __post_init__, __post_init__, value
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\repository\src\radius_repository\dto\commands.py
- **Classes Implemented**: ConnectRepositoryCommand, RepositoryListQuery, UpsertBranchCommand, UpsertPullRequestCommand
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API

## File: d:\Radius\packages\repository\src\radius_repository\dto\responses.py
- **Classes Implemented**: BranchResponse, RepositoryResponse, RepositoryDetailResponse, PullRequestResponse
- **Functions Implemented**: from_entity, from_entity, from_entity, from_entity
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API

## File: d:\Radius\packages\repository\src\radius_repository\infrastructure\in_memory.py
- **Classes Implemented**: InMemoryRepositoryStore
- **Functions Implemented**: __init__, get_by_id, get_by_github_repository_id, list_by_organization, save, update_status, upsert_branch, get_pull_request_by_repository_and_number, upsert_pull_request
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API

## File: d:\Radius\packages\repository\src\radius_repository\infrastructure\local_git.py
- **Classes Implemented**: LocalGitRepositoryClient
- **Functions Implemented**: _with_extra_headers, clone_or_fetch, checkout, _run
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\repository\src\radius_repository\infrastructure\sqlalchemy_store.py
- **Classes Implemented**: SqlAlchemyRepositoryStore
- **Functions Implemented**: __init__, get_by_id, get_by_github_repository_id, list_by_organization, save, update_status, upsert_branch, get_pull_request_by_repository_and_number, upsert_pull_request, _repository_query, _to_domain, _branch_to_domain, _pull_request_to_domain
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API, Database (SQLAlchemy)

## File: d:\Radius\packages\repository\src\radius_repository\infrastructure\__init__.py
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: Database (SQLAlchemy)

## File: d:\Radius\packages\repository\src\radius_repository\interfaces\git_provider.py
- **Classes Implemented**: ProviderRepository, GitProviderClient
- **Functions Implemented**: get_repository
- **Stubs/Placeholders**: Function: get_repository
- **TODOs**: None
- **Integrations Mentioned**: GitHub API

## File: d:\Radius\packages\repository\src\radius_repository\interfaces\git_repository.py
- **Classes Implemented**: GitRepositoryClient
- **Functions Implemented**: clone_or_fetch, checkout
- **Stubs/Placeholders**: Function: clone_or_fetch, Function: checkout
- **TODOs**: None

## File: d:\Radius\packages\repository\src\radius_repository\interfaces\repository_store.py
- **Classes Implemented**: RepositoryStore
- **Functions Implemented**: get_by_id, get_by_github_repository_id, list_by_organization, save, update_status, upsert_branch, get_pull_request_by_repository_and_number, upsert_pull_request
- **Stubs/Placeholders**: Function: get_by_id, Function: get_by_github_repository_id, Function: list_by_organization, Function: save, Function: update_status, Function: upsert_branch, Function: get_pull_request_by_repository_and_number, Function: upsert_pull_request
- **TODOs**: None
- **Integrations Mentioned**: GitHub API

## File: d:\Radius\packages\repository\src\radius_repository\interfaces\sync.py
- **Classes Implemented**: RepositorySyncService
- **Functions Implemented**: synchronize
- **Stubs/Placeholders**: Function: synchronize
- **TODOs**: None

## File: d:\Radius\packages\shared\src\radius_shared\config.py
- **Classes Implemented**: RuntimeEnvironment, LogLevel, RadiusBaseSettings
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\shared\src\radius_shared\errors.py
- **Classes Implemented**: ErrorDetail, RadiusError, ValidationError, NotFoundError, AccessDeniedError, ConflictError
- **Functions Implemented**: __init__
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\shared\src\radius_shared\logging.py
- **Classes Implemented**: JsonFormatter
- **Functions Implemented**: configure_logging, get_logger, format
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\shared\src\radius_shared\database\base.py
- **Classes Implemented**: Base, UuidPrimaryKeyMixin, TimestampMixin, TableNameMixin
- **Functions Implemented**: __tablename__
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: Database (SQLAlchemy)

## File: d:\Radius\packages\shared\src\radius_shared\database\enums.py
- **Classes Implemented**: UserRole, RepositoryProvider, RepositoryVisibility, RepositoryStatus, PullRequestStatus, AnalysisStatus, ChangedFileType, RiskLevel, AnalysisJobStatus
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API

## File: d:\Radius\packages\shared\src\radius_shared\database\models.py
- **Classes Implemented**: Organization, User, Repository, Branch, PullRequest, Analysis, ChangedFile, GraphSnapshot, GraphNode, GraphEdge, BlastRadius, TestRun, TestCase, TestSelection, SelectedTest, TestRunPlan, ConfidenceReport, ConfidenceEvidence, AnalysisJob, IdempotencyKey
- **Functions Implemented**: enum_values, slug
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API, Database (SQLAlchemy)

## File: d:\Radius\packages\shared\src\radius_shared\database\session.py
- **Classes Implemented**: DatabaseSettings
- **Functions Implemented**: create_database_engine, create_session_factory, session_scope
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: Database (SQLAlchemy)

## File: d:\Radius\packages\shared\src\radius_shared\dto\responses.py
- **Classes Implemented**: ErrorResponse, ApiResponse
- **Functions Implemented**: success_response, error_response
- **Stubs/Placeholders**: None detected.
- **TODOs**: None

## File: d:\Radius\packages\testing\src\radius_testing\__init__.py
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Test utility or setup file (no direct test cases found).

## File: d:\Radius\packages\testing\src\radius_testing\application\services.py
- **Classes Implemented**: TestingApplicationService
- **Functions Implemented**: __init__, discover_tests, select_tests, plan_test_run, get_selection, execute_test_run, get_run_result, ingest_test_results
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Contains test cases.

## File: d:\Radius\packages\testing\src\radius_testing\application\__init__.py
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Test utility or setup file (no direct test cases found).

## File: d:\Radius\packages\testing\src\radius_testing\domain\entities.py
- **Classes Implemented**: TestCase, SelectedTest, TestSelection, TestRunPlan, TestRunResult
- **Functions Implemented**: selected_count, skipped_count, time_saved_percent, cli_args, pending
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Contains test cases.

## File: d:\Radius\packages\testing\src\radius_testing\domain\enums.py
- **Classes Implemented**: TestFramework, TestType, TestSelectionReason, TestRunStatus
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Contains test cases.

## File: d:\Radius\packages\testing\src\radius_testing\domain\value_objects.py
- **Classes Implemented**: TestPath, SourcePath, TestName
- **Functions Implemented**: __post_init__, __post_init__, __post_init__
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Contains test cases.

## File: d:\Radius\packages\testing\src\radius_testing\domain\__init__.py
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Test utility or setup file (no direct test cases found).

## File: d:\Radius\packages\testing\src\radius_testing\dto\commands.py
- **Classes Implemented**: DiscoverTestsCommand, SelectTestsCommand, PlanTestRunCommand, ExecuteTestRunCommand
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Test utility or setup file (no direct test cases found).

## File: d:\Radius\packages\testing\src\radius_testing\dto\responses.py
- **Classes Implemented**: TestCaseResponse, TestDiscoveryResponse, SelectedTestResponse, TestSelectionResponse, TestRunPlanResponse, TestRunResultResponse
- **Functions Implemented**: from_entity, from_entity, from_entity, from_entity, from_entity
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Contains test cases.

## File: d:\Radius\packages\testing\src\radius_testing\dto\__init__.py
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Test utility or setup file (no direct test cases found).

## File: d:\Radius\packages\testing\src\radius_testing\infrastructure\discovery.py
- **Classes Implemented**: ConventionalTestDiscoverer
- **Functions Implemented**: discover, _is_ignored, _is_test_path, _framework, _target_path, _target_candidate
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Test utility or setup file (no direct test cases found).

## File: d:\Radius\packages\testing\src\radius_testing\infrastructure\in_memory.py
- **Classes Implemented**: InMemoryTestStore
- **Functions Implemented**: __init__, save_test_cases, list_test_cases, save_selection, get_selection, save_run_plan, get_run_plan, save_run_result, get_run_result
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Test utility or setup file (no direct test cases found).

## File: d:\Radius\packages\testing\src\radius_testing\infrastructure\junit_parser.py
- **Classes Implemented**: JUnitReportParser
- **Functions Implemented**: parse, _parse_json, _parse_xml
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Test utility or setup file (no direct test cases found).

## File: d:\Radius\packages\testing\src\radius_testing\infrastructure\planner.py
- **Classes Implemented**: StaticTestCommandPlanner
- **Functions Implemented**: plan
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Test utility or setup file (no direct test cases found).

## File: d:\Radius\packages\testing\src\radius_testing\infrastructure\selection.py
- **Classes Implemented**: PathBasedTestSelector
- **Functions Implemented**: select, _select_conventional, _candidate_tests, _normalize
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Test utility or setup file (no direct test cases found).

## File: d:\Radius\packages\testing\src\radius_testing\infrastructure\sqlalchemy_store.py
- **Classes Implemented**: SqlAlchemyTestStore
- **Functions Implemented**: __init__, save_test_cases, list_test_cases, save_selection, get_selection, save_run_plan, get_run_plan, save_run_result, get_run_result, _test_case_to_domain
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: Database (SQLAlchemy)
- **Test Status**: Test utility or setup file (no direct test cases found).

## File: d:\Radius\packages\testing\src\radius_testing\infrastructure\subprocess_runner.py
- **Classes Implemented**: SubprocessTestRunner
- **Functions Implemented**: __init__, run
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Test utility or setup file (no direct test cases found).

## File: d:\Radius\packages\testing\src\radius_testing\infrastructure\__init__.py
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: Database (SQLAlchemy)
- **Test Status**: Test utility or setup file (no direct test cases found).

## File: d:\Radius\packages\testing\src\radius_testing\interfaces\discovery.py
- **Classes Implemented**: TestDiscoverer
- **Functions Implemented**: discover
- **Stubs/Placeholders**: Function: discover
- **TODOs**: None
- **Test Status**: Contains test cases.

## File: d:\Radius\packages\testing\src\radius_testing\interfaces\runner.py
- **Classes Implemented**: TestCommandPlanner, TestRunner
- **Functions Implemented**: plan, run
- **Stubs/Placeholders**: Function: plan, Function: run
- **TODOs**: None
- **Test Status**: Contains test cases.

## File: d:\Radius\packages\testing\src\radius_testing\interfaces\selection.py
- **Classes Implemented**: TestSelector
- **Functions Implemented**: select
- **Stubs/Placeholders**: Function: select
- **TODOs**: None
- **Test Status**: Contains test cases.

## File: d:\Radius\packages\testing\src\radius_testing\interfaces\store.py
- **Classes Implemented**: TestStore
- **Functions Implemented**: save_test_cases, list_test_cases, save_selection, get_selection, save_run_plan, get_run_plan, save_run_result, get_run_result
- **Stubs/Placeholders**: Function: save_test_cases, Function: list_test_cases, Function: save_selection, Function: get_selection, Function: save_run_plan, Function: get_run_plan, Function: save_run_result, Function: get_run_result
- **TODOs**: None
- **Test Status**: Contains test cases.

## File: d:\Radius\packages\testing\src\radius_testing\interfaces\__init__.py
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Test utility or setup file (no direct test cases found).

## File: d:\Radius\tests\test_end_to_end_target.py
- **Classes Implemented**: MockTargetTestRunner
- **Functions Implemented**: _init_git_target_repo, _apply_target_modifications_and_get_diff, test_end_to_end_target_verification_flow, run
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API
- **Mocking**: Detected use of mocking (likely mock integrations)
- **Test Status**: Contains test cases.

## File: d:\Radius\tests\test_oss_targets.py
- **Classes Implemented**: MockOssTestRunner
- **Functions Implemented**: test_real_oss_python_target_bottle, test_real_oss_typescript_target_emittery, run
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API
- **Mocking**: Detected use of mocking (likely mock integrations)
- **Test Status**: Contains test cases.

## d:\Radius\pyproject.toml
- **Type**: Configuration file
- **TODOs**: 0
- **Lines**: 84

## File: d:\Radius\conftest.py
- **Functions Implemented**: isolate_monorepo_test_environment
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Integrations Mentioned**: GitHub API
- **Test Status**: Test utility or setup file (no direct test cases found).

## File: d:\Radius\test_e2e.py
- **Functions Implemented**: run_e2e
- **Stubs/Placeholders**: None detected.
- **TODOs**: None
- **Test Status**: Test utility or setup file (no direct test cases found).
