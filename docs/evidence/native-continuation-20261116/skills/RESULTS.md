# Compact Skill catalog continuation

The prior compact model projection removed the function description containing the selected Skill purpose/version catalog. This was an observed omission: the new test fails before the fix with missing `description`, preserved in `before.log`.

The model-facing projection now keeps `load_skill` metadata while instruction bodies still load on demand. The persisted `schemas()` projection is unchanged. The test drives the real registry, Skill installation/loading, AgentSession requests and snapshot restore; no model request or tool replay occurs during restore.

Final targeted command:

```sh
python -m unittest tests.test_pa_skills tests.test_inference_backend.InferenceBackendTests.test_compact_model_receives_path_semantics_without_changing_stored_contract -v
```

Result: **7 PASS** (`after-r2.log`). `after-r1.log` preserves the earlier command error that used the wrong class name for the HTTP test (the six Skill tests passed in that invocation). These are implementation/transport tests with scripted model responses, not measured real-model Skill-selection accuracy.
